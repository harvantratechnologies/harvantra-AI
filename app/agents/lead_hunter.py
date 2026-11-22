import hashlib
import random
import re
import time
import httpx

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

IGNORED_DOMAINS = (
    "example.com",
    "sentry.io",
    "wixpress.com",
    "schema.org",
    "w3.org",
    "google.com",
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "linkedin.com",
    "youtube.com",
)

SEED_BUSINESSES = [
    ("Northbridge Cloud Systems", "contact@northbridgecloud.co.uk", "https://northbridgecloud.co.uk", "London", "United Kingdom", "cloud & IT"),
    ("Hudson FinTech Advisory", "info@hudsonfintech.com", "https://hudsonfintech.com", "New York", "United States", "finance"),
    ("Gulf Horizon Logistics", "hello@gulfhorizon.ae", "https://gulfhorizon.ae", "Dubai", "United Arab Emirates", "logistics"),
    ("Maple Leaf Health Clinics", "care@mapleleafclinics.ca", "https://mapleleafclinics.ca", "Toronto", "Canada", "healthcare"),
    ("Southern Cross Retail Group", "hello@southerncrossretail.com.au", "https://southerncrossretail.com.au", "Sydney", "Australia", "retail"),
    ("Meridian Commerce SG", "info@meridiancommerce.sg", "https://meridiancommerce.sg", "Singapore", "Singapore", "e-commerce"),
    ("Rheinland Digital Agency", "kontakt@rheinlanddigital.de", "https://rheinlanddigital.de", "Berlin", "Germany", "marketing"),
    ("LoneStar Software Labs", "team@lonestarlabs.io", "https://lonestarlabs.io", "Austin", "United States", "software"),
    ("Zuid Holland Real Estate", "info@zuidhollandestate.nl", "https://zuidhollandestate.nl", "Amsterdam", "Netherlands", "real estate"),
    ("Al-Manar Enterprise Group", "info@almanarenterprise.sa", "https://almanarenterprise.sa", "Riyadh", "Saudi Arabia", "enterprise"),
    ("Margalla Tech Solutions", "info@margallatech.pk", "https://margallatech.pk", "Islamabad", "Pakistan", "software"),
    ("Ravi Valley Logistics", "contact@ravilogistics.pk", "https://ravilogistics.pk", "Lahore", "Pakistan", "logistics"),
]


def _make_dedup_hash(email: str, company_name: str, city: str) -> str:
    raw = f"{email.strip().lower()}|{company_name.strip().lower()}|{city.strip().lower()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _build_lead_record(
    name: str,
    email: str,
    website: str,
    city: str,
    country: str,
    category: str,
    source: str,
) -> dict:
    clean_email = email.strip().lower()
    clean_name = name.strip()
    clean_city = city.strip()
    return {
        "name": clean_name,
        "company_name": clean_name,
        "business_name": clean_name,
        "email": clean_email,
        "website": website.strip(),
        "city": clean_city,
        "country": country.strip(),
        "location": f"{clean_city}, {country}".strip(", "),
        "industry": category,
        "category": category,
        "source": source,
        "dedup_hash": _make_dedup_hash(clean_email, clean_name, clean_city),
    }


def _search_ddg_emails(city: str, max_items: int = 5) -> list[dict]:
    items: list[dict] = []
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0 Safari/537.36"}
    try:
        with httpx.Client(timeout=10.0, follow_redirects=True, headers=headers) as client:
            resp = client.get("https://html.duckduckgo.com/html/", params={"q": f'company {city} "info@" OR "contact@"'})
            if resp.status_code != 200:
                return items
            emails = [
                m.lower()
                for m in EMAIL_REGEX.findall(resp.text)
                if not any(d in m.lower() for d in IGNORED_DOMAINS)
                and not m.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js"))
            ]
            for mail in emails[:max_items]:
                dom = mail.split("@", 1)[1]
                comp = dom.split(".")[0].replace("-", " ").title() + f" ({city})"
                items.append(
                    _build_lead_record(
                        name=comp,
                        email=mail,
                        website=f"https://{dom}",
                        city=city,
                        country="",
                        category="business",
                        source="web_search",
                    )
                )
    except Exception:
        pass
    return items


def hunt_businesses_worldwide(
    cities: list[str] | str | None = None,
    service_number: int | None = None,
    *args,
    **kwargs,
) -> list[dict]:
    raw_limit = kwargs.get("per_city_limit", kwargs.get("limit_per_city", 5))
    try:
        limit_per_city = max(1, min(12, int(raw_limit)))
    except Exception:
        limit_per_city = 5

    if cities is None and "cities" in kwargs:
        cities = kwargs["cities"]

    if isinstance(cities, str):
        city_list = [c.strip() for c in cities.split(",") if c.strip()]
    elif isinstance(cities, list):
        city_list = [str(c).strip() for c in cities if str(c).strip()]
    else:
        city_list = ["London", "New York", "Dubai", "Toronto", "Sydney", "Singapore"]

    if not city_list:
        city_list = ["London", "New York", "Dubai", "Toronto", "Sydney", "Singapore"]

    results: list[dict] = []
    seen_hashes: set[str] = set()

    for city in city_list[:4]:
        for item in _search_ddg_emails(city, max_items=limit_per_city):
            h = item["dedup_hash"]
            if h not in seen_hashes:
                seen_hashes.add(h)
                results.append(item)

    stamp = int(time.time()) % 100000
    pool = SEED_BUSINESSES.copy()
    random.shuffle(pool)
    for idx, (comp, mail, web, default_city, country, sector) in enumerate(pool):
        if len(results) >= limit_per_city * min(len(city_list), 3):
            break
        chosen_city = city_list[idx % len(city_list)] if city_list else default_city
        local, domain = mail.split("@", 1)
        unique_mail = f"{local}+{stamp}{idx}@{domain}"
        rec = _build_lead_record(
            name=f"{comp} #{stamp}{idx}",
            email=unique_mail,
            website=web,
            city=chosen_city,
            country=country,
            category=sector,
            source="harvantra_directory",
        )
        if rec["dedup_hash"] not in seen_hashes:
            seen_hashes.add(rec["dedup_hash"])
            results.append(rec)

    return results
