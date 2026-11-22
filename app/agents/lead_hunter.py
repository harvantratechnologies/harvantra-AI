import random
import re
import httpx

OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
MAILTO_REGEX = re.compile(r"mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", re.IGNORECASE)

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

CITY_COORDS = {
    "london": (51.5074, -0.1278, "United Kingdom"),
    "new york": (40.7128, -74.0060, "United States"),
    "dubai": (25.2048, 55.2708, "United Arab Emirates"),
    "toronto": (43.6532, -79.3832, "Canada"),
    "sydney": (-33.8688, 151.2093, "Australia"),
    "singapore": (1.3521, 103.8198, "Singapore"),
    "berlin": (52.5200, 13.4050, "Germany"),
    "austin": (30.2672, -97.7431, "United States"),
    "chicago": (41.8781, -87.6298, "United States"),
    "san francisco": (37.7749, -122.4194, "United States"),
    "amsterdam": (52.3676, 4.9041, "Netherlands"),
    "paris": (48.8566, 2.3522, "France"),
    "tokyo": (35.6762, 139.6503, "Japan"),
    "riyadh": (24.7136, 46.6753, "Saudi Arabia"),
    "doha": (25.2854, 51.5310, "Qatar"),
    "islamabad": (33.6844, 73.0479, "Pakistan"),
    "rawalpindi": (33.5651, 73.0169, "Pakistan"),
    "lahore": (31.5204, 74.3587, "Pakistan"),
    "karachi": (24.8607, 67.0011, "Pakistan"),
}


def _resolve_city_coords(city: str) -> tuple[float, float, str] | None:
    key = city.strip().lower()
    if key in CITY_COORDS:
        return CITY_COORDS[key]
    try:
        with httpx.Client(
            timeout=8.0,
            headers={"User-Agent": "HarvantraAI/1.0 (+https://harvantratechnologies.github.io/)"},
        ) as client:
            r = client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": city, "format": "json", "limit": 1, "addressdetails": 1},
            )
            data = r.json()
            if data:
                lat = float(data[0]["lat"])
                lon = float(data[0]["lon"])
                country = data[0].get("address", {}).get("country", "")
                CITY_COORDS[key] = (lat, lon, country)
                return lat, lon, country
    except Exception:
        pass
    return None


def extract_email_from_website(website_url: str) -> str:
    if not website_url:
        return ""
    if not website_url.startswith(("http://", "https://")):
        website_url = "https://" + website_url

    base = website_url.rstrip("/")
    urls_to_try = [base, base + "/contact", base + "/contact-us"]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
    }

    for url in urls_to_try:
        try:
            with httpx.Client(timeout=6.0, follow_redirects=True, headers=headers) as client:
                resp = client.get(url)
                if resp.status_code >= 400:
                    continue
                html = resp.text

                for mail in MAILTO_REGEX.findall(html):
                    m_low = mail.strip().lower()
                    if EMAIL_REGEX.fullmatch(m_low) and not any(d in m_low for d in IGNORED_DOMAINS):
                        return m_low

                for mail in EMAIL_REGEX.findall(html):
                    m_low = mail.strip().lower()
                    if (
                        not any(d in m_low for d in IGNORED_DOMAINS)
                        and not m_low.endswith(
                            (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js", ".woff", ".ttf")
                        )
                    ):
                        return m_low
        except Exception:
            continue
    return ""


def _query_overpass(query: str) -> list[dict]:
    for mirror in OVERPASS_MIRRORS:
        try:
            with httpx.Client(timeout=20.0) as client:
                resp = client.post(mirror, data={"data": query})
                if resp.status_code == 200:
                    return resp.json().get("elements", [])
        except Exception:
            continue
    return []


def hunt_businesses_worldwide(
    cities: list[str] | str | None = None,
    service_number: int | None = None,
    limit_per_city: int = 8,
    *args,
    **kwargs,
) -> list[dict]:
    if isinstance(cities, str):
        city_list = [c.strip() for c in cities.split(",") if c.strip()]
    elif isinstance(cities, list):
        city_list = [str(c).strip() for c in cities if str(c).strip()]
    else:
        city_list = ["London", "New York", "Dubai", "Toronto", "Sydney", "Singapore"]

    if not city_list:
        city_list = ["London", "New York", "Dubai", "Toronto", "Sydney", "Singapore"]

    random.shuffle(city_list)

    results: list[dict] = []
    seen_emails: set[str] = set()

    for city in city_list[:4]:
        coords = _resolve_city_coords(city)
        if not coords:
            continue
        lat, lon, default_country = coords

        query = f"""
        [out:json][timeout:18];
        (
          node["name"]["email"](around:8000,{lat},{lon});
          way["name"]["email"](around:8000,{lat},{lon});
          node["name"]["contact:email"](around:8000,{lat},{lon});
          way["name"]["contact:email"](around:8000,{lat},{lon});
          node["name"]["website"]["office"](around:8000,{lat},{lon});
          way["name"]["website"]["office"](around:8000,{lat},{lon});
          node["name"]["website"]["shop"](around:8000,{lat},{lon});
          way["name"]["website"]["amenity"](around:8000,{lat},{lon});
        );
        out center 35;
        """

        elements = _query_overpass(query)
        random.shuffle(elements)

        city_count = 0
        for el in elements:
            if city_count >= limit_per_city:
                break
            tags = el.get("tags", {})
            name = tags.get("name", "").strip()
            if not name:
                continue

            website = (tags.get("website") or tags.get("contact:website") or "").strip()
            email = (tags.get("email") or tags.get("contact:email") or "").strip().lower()

            if not email and website:
                email = extract_email_from_website(website)

            if not email or not EMAIL_REGEX.fullmatch(email):
                continue
            if any(d in email for d in IGNORED_DOMAINS) or email in seen_emails:
                continue

            seen_emails.add(email)
            category = (
                tags.get("office")
                or tags.get("shop")
                or tags.get("amenity")
                or tags.get("craft")
                or "business"
            )
            country = tags.get("addr:country") or default_country

            results.append(
                {
                    "name": name,
                    "company_name": name,
                    "business_name": name,
                    "email": email,
                    "website": website,
                    "city": city,
                    "country": country,
                    "location": f"{city}, {country}".strip(", "),
                    "industry": category,
                    "category": category,
                    "source": "overpass_global_crawler",
                }
            )
            city_count += 1

    return results
