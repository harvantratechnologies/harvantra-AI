import json
import re
from typing import Dict
import httpx
from app.config import settings
from app.models import Lead, ServiceCatalog

COMPANY_WEBSITE = "https://harvantratechnologies.github.io/"
FOUNDER_LINKEDIN = "https://www.linkedin.com/in/haris-hassan-65b0523a8/"
COMPANY_GITHUB = "https://github.com/harvantratechnologies"


def _ensure_links(text: str) -> str:
    links_block = (
        f"\n\nHarvantra Technologies Links:\n"
        f"- Website: {COMPANY_WEBSITE}\n"
        f"- LinkedIn: {FOUNDER_LINKEDIN}\n"
        f"- GitHub Portfolio: {COMPANY_GITHUB}"
    )
    out = text.strip()
    if COMPANY_WEBSITE not in out:
        out += f"\nWebsite: {COMPANY_WEBSITE}"
    if FOUNDER_LINKEDIN not in out:
        out += f"\nLinkedIn: {FOUNDER_LINKEDIN}"
    if COMPANY_GITHUB not in out:
        out += f"\nGitHub: {COMPANY_GITHUB}"
    if "Unsubscribe" not in out:
        out += f"\n\nReply 'Unsubscribe' if you do not wish to receive future messages.{links_block}"
    return out


def generate_personalized_outreach(lead: Lead, service: ServiceCatalog) -> Dict:
    location_label = f"{lead.city}, {lead.country}" if lead.city and lead.country else (lead.city or lead.country or "globally")
    fallback_subject = f"{service.name} for {lead.business_name} | Harvantra Technologies"
    fallback_email = _ensure_links(
        f"Hello {lead.business_name} Team,\n\n"
        f"I am Haris Hassan, Founder of Harvantra Technologies. While reviewing businesses operating in {location_label}, "
        f"I noticed your presence in {lead.category or 'your industry'} and wanted to share how our {service.name} "
        f"service can support your organization.\n\n"
        f"{service.summary} {lead.match_reason or ''}\n\n"
        f"Would you be open to a quick 10-minute discussion this week to explore if this aligns with your current goals?\n\n"
        f"Best regards,\n"
        f"Haris Hassan\n"
        f"Founder, Harvantra Technologies"
    )
    fallback_whatsapp = (
        f"Hello {lead.business_name}, I'm Haris Hassan (Founder, Harvantra Technologies). "
        f"We help organizations in {location_label} with {service.name}. "
        f"Website: {COMPANY_WEBSITE} | LinkedIn: {FOUNDER_LINKEDIN} | GitHub: {COMPANY_GITHUB}"
    )

    if not settings.GROQ_API_KEY:
        return {
            "email_subject": fallback_subject,
            "email_body": fallback_email,
            "whatsapp_body": fallback_whatsapp,
        }

    prompt = f"""
Write a respectful, personalized B2B outreach email and short WhatsApp message on behalf of:
- Founder: Haris Hassan
- Company: Harvantra Technologies
- Website: {COMPANY_WEBSITE}
- LinkedIn: {FOUNDER_LINKEDIN}
- GitHub Portfolio: {COMPANY_GITHUB}

Target Business:
- Name: {lead.business_name}
- Location: {location_label}
- Category: {lead.category}
- Public Observation: {lead.research_summary}
- Target Service: #{service.number} {service.name} ({service.summary})
- Relevance Note: {lead.match_reason}

Rules:
1. NEVER claim they have a confirmed vulnerability or security breach.
2. Include all three links ({COMPANY_WEBSITE}, {FOUNDER_LINKEDIN}, {COMPANY_GITHUB}) cleanly in the email.
3. Keep the email clear, persuasive, and concise (130-180 words).
4. Return ONLY valid JSON with keys: "email_subject", "email_body", "whatsapp_body".
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
                    "temperature": 0.35,
                    "messages": [
                        {"role": "system", "content": "Output strict JSON only."},
                        {"role": "user", "content": prompt},
                    ],
                },
            )
            if resp.status_code != 200:
                return {
                    "email_subject": fallback_subject,
                    "email_body": fallback_email,
                    "whatsapp_body": fallback_whatsapp,
                }
            content = resp.json()["choices"][0]["message"]["content"].strip()
            match = re.search(r"\{.*\}", content, re.DOTALL)
            parsed = json.loads(match.group(0) if match else content)
            email_body = _ensure_links(str(parsed.get("email_body", fallback_email)))
            return {
                "email_subject": str(parsed.get("email_subject", fallback_subject))[:250],
                "email_body": email_body,
                "whatsapp_body": str(parsed.get("whatsapp_body", fallback_whatsapp)),
            }
    except Exception:
        return {
            "email_subject": fallback_subject,
            "email_body": fallback_email,
            "whatsapp_body": fallback_whatsapp,
        }
