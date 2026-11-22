import random
import re
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
    "apple.com",
    "microsoft.com",
    "cloudflare.com",
)

GLOBAL_CITIES = [
    ("London", "United Kingdom"),
    ("New York", "United States"),
    ("Dubai", "United Arab Emirates"),
    ("Toronto", "Canada"),
    ("Sydney", "Australia"),
    ("Singapore", "Singapore"),
    ("Berlin", "Germany"),
    ("Austin", "United States"),
    ("Amsterdam", "Netherlands"),
    ("Riyadh", "Saudi Arabia"),
    ("Doha", "Qatar"),
    ("Islamabad", "Pakistan"),
    ("Lahore", "Pakistan"),
    ("Karachi", "Pakistan"),
]

BUSINESS_SECTORS = [
    "software company",
    "digital marketing agency",
    "logistics company",
    "private clinic",
    "e-commerce store",
    "consulting firm",
    "real estate agency",
    "financial advisory",
    "hospitality group",
    "construction company",
]


def _clean_domain(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]", "", text.lower())
    return cleaned[:24] if cleaned else ""


def _fetch_ddg_businesses(city: str, sector: str, max_items: int = 6) -> list[dict]:
    found: list[dict] = []
    query = f'{sector} {city} "@" OR "info@" OR "contact@"'
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        with httpx.Client(timeout=12.0, follow_redirects=True, headers=headers) as client:
            resp = client.get("https://html.duckduckgo.com/html/", params={"q": query})
            if resp.status_code != 200:
                return found
            html = resp.text

            # Extract emails directly from snippets
            emails = [
                m.lower()
                for m in EMAIL_REGEX.findall(html)
                if not any(d in m.lower() for d in IGNORED_DOMAINS)
                and not m.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".js", ".css"))
            ]

            # Extract result titles as business names
            raw_titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', html, re.DOTALL)
            titles = [re.sub(r"<[^>]+>", "", t).strip() for t in raw_titles if re.sub(r"<[^>]+>", "", t).strip()]

            for idx, mail in enumerate(emails[:max_items]):
                biz_name = titles[idx] if idx < len(titles) else f"{city.title()} {sector.title()} #{idx + 1}"
                biz_name = biz_name[:80]
                domain = mail.split("@", 1)[1]
                found.append(
                    {
                        "name": biz_name,
                        "company_name": biz_name,
                        "business_name": biz_name,
                        "email": mail,
                        "website": f"https://{domain}",
                        "city": city,
                        "country": "",
                        "location": city,
                        "industry": sector,
                        "category": sector,
                        "source": "harvantra_web_discovery",
                    }
                )
    except Exception:
        pass
    return found


def _fetch_overpass_quick(city: str, max_items: int = 6) -> list[dict]:
    city_coords = {
        "london": (51.5074, -0.1278),
        "new york": (40.7128, -74.0060),
        "dubai": (25.2048, 55.2708),
        "toronto": (43.6532, -79.3832),
        "sydney": (-33.8688, 151.2093),
        "singapore": (1.3521, 103.8198),
        "berlin": (52.5200, 13.4050),
        "austin": (30.2672, -97.7431),
        "islamabad": (33.6844, 73.0479),
        "lahore": (31.5204, 74.3587),
        "karachi": (24.8607, 67.0011),
    }
    coords = city_coords.get(city.strip().lower())
    if not coords:
        return []

    lat, lon = coords
    query = f"""
    [out:json][timeout:12];
    (
      node["name"]["email"](around:10000,{lat},{lon});
      way["name"]["email"](around:10000,{lat},{lon});
      node["name"]["contact:email"](around:10000,{lat},{lon});
    );
    out center 20;
    """
    out: list[dict] = []
    for mirror in ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"):
        try:
            with httpx.Client(timeout=14.0) as client:
                r = client.post(mirror, data={"data": query})
                if r.status_code == 200:
                    for el in r.json().get("elements", []):
                        if len(out) >= max_items:
                            break
                        tags = el.get("tags", {})
                        name = (tags.get("name") or "").strip()
                        email = (tags.get("email") or tags.get("contact:email") or "").strip().lower()
                        if name and email and EMAIL_REGEX.fullmatch(email) and not any(d in email for d in IGNORED_DOMAINS):
                            website = (tags.get("website") or tags.get("contact:website") or f"https://{email.split('@')[1]}").strip()
                            cat = tags.get("office") or tags.get("shop") or tags.get("amenity") or "business"
                            out.append(
                                {
                                    "name": name,
                                    "company_name": name,
                                    "business_name": name,
                                    "email": email,
                                    "website": website,
                                    "city": city,
                                    "country": tags.get("addr:country", ""),
                                    "location": city,
                                    "industry": cat,
                                    "category": cat,
                                    "source": "overpass_direct_email",
                                }
                            )
                    if out:
                        return out
        except Exception:
            continue
    return out


def hunt_businesses_worldwide(
    cities: list[str] | str | None = None,
    service_number: int | None = None,
    *args,
    **kwargs,
) -> list[dict]:
    raw_limit = kwargs.get("per_city_limit", kwargs.get("limit_per_city", 6))
    try:
        limit_per_city = max(1, min(15, int(raw_limit)))
    except Exception:
        limit_per_city = 6

    if cities is None and "cities" in kwargs:
        cities = kwargs["cities"]

    if isinstance(cities, str):
        parsed = [(c.strip(), "") for c in cities.split(",") if c.strip()]
    elif isinstance(cities, list):
        parsed = [(str(c).strip(), "") for c in cities if str(c).strip()]
    else:
        parsed = []

    target_cities = parsed if parsed else GLOBAL_CITIES
    random.shuffle(target_cities)
    sectors = BUSINESS_SECTORS.copy()
    random.shuffle(sectors)

    results: list[dict] = []
    seen_emails: set[str] = set()

    for city, default_country in target_cities[:4]:
        city_leads: list[dict] = []

        # Source 1: Overpass direct emails
        for item in _fetch_overpass_quick(city, max_items=limit_per_city):
            mail = item["email"]
            if mail not in seen_emails:
                seen_emails.add(mail)
                if not item.get("country") and default_country:
                    item["country"] = default_country
                city_leads.append(item)
                if len(city_leads) >= limit_per_city:
                    break

        # Source 2: Web search discovery across different business sectors
        if len(city_leads) < limit_per_city:
            for sector in sectors[:3]:
                if len(city_leads) >= limit_per_city:
                    break
                for item in _fetch_ddg_businesses(city, sector, max_items=limit_per_city - len(city_leads)):
                    mail = item["email"]
                    if mail not in seen_emails:
                        seen_emails.add(mail)
                        if not item.get("country") and default_country:
                            item["country"] = default_country
                        city_leads.append(item)
                        if len(city_leads) >= limit_per_city:
                            break
