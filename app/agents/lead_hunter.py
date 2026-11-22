import re
import httpx

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
MAILTO_REGEX = re.compile(r'mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', re.IGNORECASE)
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
)


def extract_email_from_website(website_url: str) -> str:
    if not website_url:
        return ""
    if not website_url.startswith(("http://", "https://")):
        website_url = "https://" + website_url

    urls_to_try = [website_url.rstrip("/"), website_url.rstrip("/") + "/contact"]
    headers = {"User-Agent": "Mozilla/5.0 (compatible; HarvantraBot/1.0; +https://harvantratechnologies.github.io/)"}

    for url in urls_to_try:
        try:
            with httpx.Client(timeout=8.0, follow_redirects=True, headers=headers) as client:
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
                        and not m_low.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js"))
                    ):
                        return m_low
        except Exception:
            continue
    return ""


def hunt_businesses_worldwide(cities: list[str] | None = None, limit_per_city: int = 12) -> list[dict]:
    if not cities:
        cities = ["London", "New York", "Dubai", "Toronto", "Sydney", "Singapore"]

    results = []
    seen_emails = set()

    for raw_city in cities:
        city = raw_city.strip()
        if not city:
            continue

        query = f"""
        [out:json][timeout:25];
        area["name"="{city}"]["boundary"="administrative"]->.searchArea;
        (
          node["name"]["email"](area.searchArea);
          way["name"]["email"](area.searchArea);
          node["name"]["contact:email"](area.searchArea);
          way["name"]["contact:email"](area.searchArea);
          node["name"]["website"]["office"](area.searchArea);
          way["name"]["website"]["office"](area.searchArea);
          node["name"]["website"]["shop"](area.searchArea);
          way["name"]["website"]["shop"](area.searchArea);
          node["name"]["website"]["amenity"](area.searchArea);
        );
        out center 40;
        """

        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(OVERPASS_URL, data={"data": query})
                resp.raise_for_status()
                elements = resp.json().get("elements", [])
        except Exception:
            elements = []

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
            results.append(
                {
                    "company_name": name,
                    "business_name": name,
                    "email": email,
                    "website": website,
                    "city": city,
                    "location": city,
                    "country": tags.get("addr:country", ""),
                    "industry": category,
                    "category": category,
                    "source": "overpass_global_crawler",
                }
            )
            city_count += 1

    return results
