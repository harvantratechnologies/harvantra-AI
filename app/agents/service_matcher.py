import json
import re
from typing import Dict, List, Optional
import httpx
from app.config import settings
from app.models import ServiceCatalog


def _fallback_match(category: str, services: List[ServiceCatalog]) -> Dict:
    cat = (category or "").lower()
    target_num = 30
    if any(k in cat for k in ["it", "software", "computer", "telecom"]):
        target_num = 3
    elif any(k in cat for k in ["bank", "finance", "hospital", "clinic", "health"]):
        target_num = 17
    elif any(k in cat for k in ["shop", "retail", "commerce", "store"]):
        target_num = 26

    chosen = next((s for s in services if s.number == target_num), services[0] if services else None)
    return {
        "service_number": chosen.number if chosen else 1,
        "research_summary": f"Public business entry in category '{category or 'general'}' without confirmed vulnerability scan.",
        "identified_needs": "General IT reliability, data protection, and security posture review.",
        "match_reason": "Selected based on business category and standard operational risk profile (no unverified vulnerability claimed).",
    }


def analyze_and_match_service(
    business_name: str,
    category: str,
    city: str,
    website: Optional[str],
    website_snippet: str,
    services: List[ServiceCatalog],
) -> Dict:
    active_services = [s for s in services if s.is_active] or services
    if not active_services:
        return _fallback_match(category, services)

    if not settings.GROQ_API_KEY:
        return _fallback_match(category, active_services)

    service_lines = "\n".join(
        [f"{s.number}. {s.name} ({s.category}) - {s.summary}" for s in active_services]
    )

    prompt = f"""
You are the AI Business Research & Service Matching Agent for Harvantra Technologies.
Never claim that a business has a confirmed security vulnerability or breach.
Clearly frame findings as public observations and potential IT/security opportunities.

Business Name: {business_name}
Category: {category}
City: {city}
Website: {website or "None"}
Public Website Observations: {website_snippet}

Choose ONLY ONE most relevant service number (1 to 30) from this catalog:
{service_lines}

Return ONLY valid JSON with these exact keys:
{{
  "service_number": <integer 1-30>,
  "research_summary": "<2-3 sentences based only on public info>",
  "identified_needs": "<potential IT/security opportunity>",
  "match_reason": "<why this 1 service fits best>"
}}
"""

    try:
        with httpx.Client(timeout=25.0) as client:
            resp = client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.GROQ_MODEL,
                    "temperature": 0.2,
                    "messages": [
                        {"role": "system", "content": "You output strict JSON only."},
                        {"role": "user", "content": prompt},
                    ],
                },
            )
            if resp.status_code != 200:
                return _fallback_match(category, active_services)

            content = resp.json()["choices"][0]["message"]["content"].strip()
            match = re.search(r"\{.*\}", content, re.DOTALL)
            parsed = json.loads(match.group(0) if match else content)

            svc_num = int(parsed.get("service_number", 30))
            if not any(s.number == svc_num for s in active_services):
                svc_num = active_services[0].number

            return {
                "service_number": svc_num,
                "research_summary": str(parsed.get("research_summary", ""))[:1000],
                "identified_needs": str(parsed.get("identified_needs", ""))[:600],
                "match_reason": str(parsed.get("match_reason", ""))[:600],
            }
    except Exception:
        return _fallback_match(category, active_services)
