import re
from typing import Dict
import httpx


def fetch_public_website_summary(website: str | None) -> Dict:
    if not website:
        return {
            "reachable": False,
            "extracted_email": None,
            "snippet": "No public website listed on map.",
        }

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; HarvantraResearchBot/1.0; +https://harvantratechnologies.github.io/)"
    }

    try:
        with httpx.Client(timeout=12.0, follow_redirects=True, headers=headers) as client:
            resp = client.get(website)
            if resp.status_code >= 400:
                return {
                    "reachable": False,
                    "extracted_email": None,
                    "snippet": f"Website returned HTTP {resp.status_code}.",
                }

            html = resp.text or ""
            emails = re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", html)
            filtered_emails = [
                e for e in emails if not e.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js"))
            ]
            found_email = filtered_emails[0] if filtered_emails else None

            title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
            title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else ""

            clean_text = re.sub(r"<script.*?>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
            clean_text = re.sub(r"<style.*?>.*?</style>", " ", clean_text, flags=re.DOTALL | re.IGNORECASE)
            clean_text = re.sub(r"<[^>]+>", " ", clean_text)
            clean_text = re.sub(r"\s+", " ", clean_text).strip()[:1200]

            snippet = f"Title: {title}. Content: {clean_text}" if title else clean_text
            return {
                "reachable": True,
                "extracted_email": found_email,
                "snippet": snippet[:1400],
            }
    except Exception as exc:
        return {
            "reachable": False,
            "extracted_email": None,
            "snippet": f"Could not fetch public website cleanly: {str(exc)[:120]}",
        }
