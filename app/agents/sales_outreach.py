import json
import re
from typing import Dict
import httpx
from app.config import settings
from app.models import Lead, ServiceCatalog


def generate_personalized_outreach(lead: Lead, service: ServiceCatalog) -> Dict:
    fallback_subject = f"{service.name} for {lead.business_name} | Harvantra Technologies"
    fallback_email = (
        f"Assalam-o-Alaikum / Hello {lead.business_name} Team,\n\n"
        f"I am Haris Hassan, Founder of Harvantra Technologies. While reviewing public business information "
        f"for organizations in {lead.city or 'Pakistan'}, I noticed your work in {lead.category or 'your sector'} "
        f"and wanted to introduce our {service.name} service.\n\n"
        f"{service.summary} This helps growing organizations strengthen reliability and security without unnecessary overhead.\n\n"
        f"You can learn more about our work here:\n"
        f"- Website: https://harvantratechnologies.github.io/\n"
        f"- Founder LinkedIn: https://www.linkedin.com/in/haris-hassan-65b0523a8/\n"
        f"- GitHub: https://github.com/harvantratechnologies\n\n"
        f"Would you be open to a brief 10-minute introductory call this week to discuss whether this fits your current priorities?\n\n"
        f"Best regards,\n"
        f"Haris Hassan\n"
        f"Founder, Harvantra Technologies\n\n"
        f"---\n"
        f"If you prefer not to receive future emails from us, simply reply with 'Unsubscribe'."
    )
    fallback_whatsapp = (
        f"Hello {lead.business_name} Team, I'm Haris Hassan, Founder of Harvantra Technologies "
        f"(https://harvantratechnologies.github.io/). We help businesses in {lead.city or 'Pakistan'} with "
        f"{service.name}. Would you like a quick overview of how we can support your team?"
    )

    if not settings.GROQ_API_KEY:
        return {
            "email_subject": fallback_subject,
            "email_body": fallback_email,
            "whatsapp_body": fallback_whatsapp,
        }

    prompt = f"""
Write a respectful, personalized, non-spam B2B outreach email and short WhatsApp template message on behalf of:
- Founder: Haris Hassan
- Company: Harvantra Technologies
- Website: https://harvantratechnologies.github.io/
- LinkedIn: https://www.linkedin.com/in/haris-hassan-65b0523a8/
- GitHub: https://github.com/harvantratechnologies

Prospect Details:
- Business: {lead.business_name}
- City: {lead.city}
- Category: {lead.category}
- Public Observation: {lead.research_summary}
- Matched Service: {service.name} ({service.summary})
- Why it fits: {lead.match_reason}

Rules:
1. NEVER claim they have a vulnerability, hack, or security flaw.
2. Keep the email concise (140-190 words), warm, professional, with a clear call to action and an unsubscribe line at the bottom.
3. Return ONLY valid JSON with keys: "email_subject", "email_body", "whatsapp_body".
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
                    "temperature": 0.4,
                    "messages": [
                        {"role": "system", "content": "Output valid JSON only."},
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
            return {
                "email_subject": str(parsed.get("email_subject", fallback_subject))[:250],
                "email_body": str(parsed.get("email_body", fallback_email)),
                "whatsapp_body": str(parsed.get("whatsapp_body", fallback_whatsapp)),
            }
    except Exception:
        return {
            "email_subject": fallback_subject,
            "email_body": fallback_email,
            "whatsapp_body": fallback_whatsapp,
        }
