import json
import re
from typing import Dict
import httpx
from sqlalchemy.orm import Session
from app.agents.email_agent import send_email_via_smtp
from app.config import settings
from app.core.safety_guard import add_to_suppression_list
from app.models import AuditLog, ConversationLog, Lead, ServiceCatalog


def classify_and_draft_reply(lead: Lead, service: ServiceCatalog | None, incoming_text: str) -> Dict:
    lower = incoming_text.lower()
    if any(w in lower for w in ["unsubscribe", "stop", "remove me", "do not contact", "not interested"]):
        return {
            "intent": "opt_out",
            "needs_human_attention": False,
            "auto_reply": "Understood. We have removed your contact from our outreach list and will not send further messages. Wishing your team all the best.",
        }

    if any(w in lower for w in ["price", "pricing", "quote", "cost", "proposal", "contract", "call", "meeting"]):
        return {
            "intent": "quote_or_meeting",
            "needs_human_attention": True,
            "auto_reply": (
                f"Thank you for your response, {lead.business_name} Team! I have shared your inquiry directly with "
                f"Haris Hassan (Founder, Harvantra Technologies) so we can prepare tailored details for "
                f"{service.name if service else 'your requirements'} and arrange a convenient time to connect. "
                f"In the meantime, you can review our portfolio at https://harvantratechnologies.github.io/."
            ),
        }

    if not settings.GROQ_API_KEY:
        return {
            "intent": "question",
            "needs_human_attention": False,
            "auto_reply": (
                f"Thank you for reaching out! At Harvantra Technologies, we provide {service.name if service else 'IT and Cybersecurity solutions'}. "
                f"You can explore our full catalog at https://harvantratechnologies.github.io/ or connect with our Founder Haris Hassan on LinkedIn: "
                f"https://www.linkedin.com/in/haris-hassan-65b0523a8/."
            ),
        }

    prompt = f"""
You are the Customer Support & Reply Agent for Harvantra Technologies (Founder: Haris Hassan).
Website: https://harvantratechnologies.github.io/
LinkedIn: https://www.linkedin.com/in/haris-hassan-65b0523a8/
GitHub: https://github.com/harvantratechnologies

Rules:
1. NEVER quote specific prices, sign contracts, or make custom legal/technical guarantees. If they ask for pricing, quotes, or meetings, set "needs_human_attention": true.
2. If they want to opt out, set "intent": "opt_out".
3. Keep replies polite, concise, accurate, and aligned with Harvantra's service: {service.name if service else 'Cybersecurity & IT Services'}.

Lead: {lead.business_name}
Incoming Message: {incoming_text}

Return ONLY valid JSON:
{{
  "intent": "<interested|question|quote_or_meeting|opt_out|other>",
  "needs_human_attention": <true|false>,
  "auto_reply": "<polite professional response>"
}}
"""
    try:
        with httpx.Client(timeout=20.0) as client:
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
                        {"role": "system", "content": "Output valid JSON only."},
                        {"role": "user", "content": prompt},
                    ],
                },
            )
            content = resp.json()["choices"][0]["message"]["content"].strip()
            match = re.search(r"\{.*\}", content, re.DOTALL)
            parsed = json.loads(match.group(0) if match else content)
            return {
                "intent": str(parsed.get("intent", "question")),
                "needs_human_attention": bool(parsed.get("needs_human_attention", False)),
                "auto_reply": str(parsed.get("auto_reply", "")),
            }
    except Exception:
        return {
            "intent": "question",
            "needs_human_attention": True,
            "auto_reply": "Thank you for your message. Our founder Haris Hassan will review this and get back to you shortly.",
        }


def process_inbound_reply(db: Session, lead: Lead, channel: str, incoming_text: str) -> Dict:
    service = db.query(ServiceCatalog).filter(ServiceCatalog.id == lead.matched_service_id).first()
    result = classify_and_draft_reply(lead, service, incoming_text)

    inbound_log = ConversationLog(
        lead_id=lead.id,
        channel=channel,
        direction="inbound",
        intent=result["intent"],
        message_text=incoming_text,
        needs_human_attention=result["needs_human_attention"],
    )
    db.add(inbound_log)

    if result["intent"] == "opt_out":
        target = lead.email if channel == "email" else lead.phone
        if target:
            add_to_suppression_list(db, target, channel=channel, reason="client_reply_opt_out")
    elif result["needs_human_attention"]:
        lead.status = "needs_human_attention"
    else:
        lead.status = "engaged"

    reply_text = result["auto_reply"]
    sent_status = "drafted"
    if channel == "email" and lead.email and result["intent"] != "opt_out":
        ok, info = send_email_via_smtp(lead.email, f"Re: Harvantra Technologies ({lead.business_name})", reply_text)
        sent_status = "sent" if ok else f"drafted ({info})"

    outbound_log = ConversationLog(
        lead_id=lead.id,
        channel=channel,
        direction="outbound",
        intent=f"reply_to_{result['intent']}",
        message_text=reply_text,
        needs_human_attention=result["needs_human_attention"],
    )
    db.add(outbound_log)
    db.add(
        AuditLog(
            actor="reply_agent",
            action="inbound_reply_processed",
            target_type="lead",
            target_id=str(lead.id),
            metadata_json=f'{{"intent":"{result["intent"]}","human_alert":{str(result["needs_human_attention"]).lower()}}}',
        )
    )
    db.commit()

    return {
        "lead_id": lead.id,
        "business_name": lead.business_name,
        "intent": result["intent"],
        "needs_human_attention": result["needs_human_attention"],
        "auto_reply": reply_text,
        "delivery_status": sent_status,
    }
