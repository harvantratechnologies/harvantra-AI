import hashlib
from typing import Dict, List
import httpx

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

GLOBAL_SEED_PROSPECTS: List[Dict] = [
    {
        "business_name": "Gulf Cloud & IT Solutions",
        "website": "https://example.com",
        "email": "info@gulfcloud-demo.example.com",
        "phone": "+971-4-000-0001",
        "category": "cloud_it_services",
        "city": "Dubai",
        "country": "UAE",
        "source": "global_directory",
    },
    {
        "business_name": "Thames FinTech & Advisory",
        "website": "https://example.org",
        "email": "contact@thamesfintech-demo.example.com",
        "phone": "+44-20-0000-0002",
        "category": "fintech",
        "city": "London",
        "country": "UK",
        "source": "global_directory",
    },
    {
        "business_name": "Riyadh Enterprise Systems",
        "website": "https://example.net",
        "email": "hello@riyadhenterprise-demo.example.com",
        "phone": "+966-11-000-0003",
        "category": "enterprise_it",
        "city": "Riyadh",
        "country": "Saudi Arabia",
        "source": "global_directory",
    },
    {
        "business_name": "Maple Commerce Group",
        "website": "https://example.edu",
        "email": "ops@maplecommerce-demo.example.com",
        "phone": "+1-416-000-0004",
        "category": "ecommerce_retail",
        "city": "Toronto",
        "country": "Canada",
        "source": "global_directory",
    },
    {
        "business_name": "Margalla Software & Security",
        "website": "https://harvantratechnologies.github.io/",
        "email": "hello@margallasoft-demo.example.com",
        "phone": "+92-51-000-0005",
        "category": "software",
        "city": "Islamabad",
        "country": "Pakistan",
        "source": "global_directory",
    },
]


def build_dedup_hash(name: str, city: str, website: str | None = None, phone: str | None = None) -> str:
    raw = f"{(name or '').strip().lower()}|{(city or '').strip().lower()}|{(website or '').strip().lower()}|{(phone or '').strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _build_query(city: str, limit: int = 12) -> str:
    safe_city = city.replace('"', "").strip()
    return f"""
    [out:json][timeout:20];
    area["name"="{safe_city}"]["admin_level"~"4|5|6|7|8"]->.searchArea;
    (
      nwr["office"](area.searchArea);
      nwr["shop"~"computer|electronics|it|telecom|software"](area.searchArea);
    );
    out center {limit};
    """


def hunt_businesses_worldwide(cities: List[str], per_city_limit: int = 8) -> List[Dict]:
    discovered: List[Dict] = []
    seen_hashes = set()
    headers = {"User-Agent": "HarvantraAI/1.0 (harvantratechnologies.github.io)"}

    for city in cities:
        city_clean = city.strip()
        if not city_clean:
            continue

        query = _build_query(city_clean, limit=per_city_limit)
        data = None

        for endpoint in OVERPASS_ENDPOINTS:
            try:
                with httpx.Client(timeout=20.0, headers=headers) as client:
                    resp = client.post(endpoint, data={"data": query})
                    if resp.status_code == 200:
                        data = resp.json()
                        break
            except Exception:
                continue

        if data and "elements" in data:
            for el in data.get("elements", [])[:per_city_limit]:
                tags = el.get("tags", {}) or {}
                name = tags.get("name") or tags.get("name:en")
                if not name:
                    continue

                website = tags.get("website") or tags.get("contact:website")
                if website and not website.startswith(("http://", "https://")):
                    website = "https://" + website

                email = tags.get("email") or tags.get("contact:email")
                phone = tags.get("phone") or tags.get("contact:phone") or tags.get("mobile")
                category = tags.get("office") or tags.get("shop") or tags.get("craft") or "business"
                country = tags.get("addr:country") or "Global"

                dedup = build_dedup_hash(name, city_clean, website, phone)
                if dedup not in seen_hashes:
                    seen_hashes.add(dedup)
                    discovered.append(
                        {
                            "business_name": name.strip()[:200],
                            "website": website.strip()[:300] if website else None,
                            "email": email.strip()[:200] if email else None,
                            "phone": phone.strip()[:60] if phone else None,
                            "category": str(category).strip()[:120],
                            "city": city_clean[:100],
                            "country": str(country)[:100],
                            "source": "openstreetmap_overpass",
                            "dedup_hash": dedup,
                        }
                    )

    if not discovered:
        for item in GLOBAL_SEED_PROSPECTS:
            dedup = build_dedup_hash(item["business_name"], item["city"], item["website"], item["phone"])
            if dedup not in seen_hashes:
                seen_hashes.add(dedup)
                discovered.append({**item, "dedup_hash": dedup})

    return discovered
