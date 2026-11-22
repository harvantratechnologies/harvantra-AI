import hashlib
from typing import Dict, List
import httpx


OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]


def build_dedup_hash(name: str, city: str, website: str | None = None, phone: str | None = None) -> str:
    raw = f"{(name or '').strip().lower()}|{(city or '').strip().lower()}|{(website or '').strip().lower()}|{(phone or '').strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _build_query(city: str, limit: int = 20) -> str:
    safe_city = city.replace('"', "").strip()
    return f"""
    [out:json][timeout:25];
    area["name"="{safe_city}"]["admin_level"~"6|7|8"]->.searchArea;
    (
      nwr["office"](area.searchArea);
      nwr["craft"](area.searchArea);
      nwr["shop"~"computer|electronics|it|telecom|software|mobile_phone"](area.searchArea);
    );
    out center {limit};
    """


def hunt_businesses_osm(cities: List[str], per_city_limit: int = 15) -> List[Dict]:
    discovered: List[Dict] = []
    headers = {"User-Agent": "HarvantraAI/1.0 (harvantratechnologies.github.io)"}

    for city in cities:
        city_clean = city.strip()
        if not city_clean:
            continue

        query = _build_query(city_clean, limit=per_city_limit)
        data = None

        for endpoint in OVERPASS_ENDPOINTS:
            try:
                with httpx.Client(timeout=30.0, headers=headers) as client:
                    resp = client.post(endpoint, data={"data": query})
                    if resp.status_code == 200:
                        data = resp.json()
                        break
            except Exception:
                continue

        if not data or "elements" not in data:
            continue

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
            category = (
                tags.get("office")
                or tags.get("shop")
                or tags.get("craft")
                or tags.get("amenity")
                or "business"
            )

            discovered.append(
                {
                    "business_name": name.strip()[:200],
                    "website": website.strip()[:300] if website else None,
                    "email": email.strip()[:200] if email else None,
                    "phone": phone.strip()[:60] if phone else None,
                    "category": str(category).strip()[:120],
                    "city": city_clean[:100],
                    "country": "Pakistan",
                    "source": "openstreetmap_overpass",
                    "dedup_hash": build_dedup_hash(name, city_clean, website, phone),
                }
            )

    return discovered
