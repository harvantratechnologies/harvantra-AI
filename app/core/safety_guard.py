from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models import AuditLog, Lead, OutreachMessage, SuppressionList, SystemSetting


def normalize_contact(value: str | None) -> str:
    return (value or "").strip().lower()


def is_contact_suppressed(db: Session, email: str | None = None, phone: str | None = None) -> bool:
    candidates = [normalize_contact(email), normalize_contact(phone)]
    candidates = [c for c in candidates if c]
    if not candidates:
        return False
    found = db.query(SuppressionList).filter(SuppressionList.contact_value.in_(candidates)).first()
    return found is not None


def add_to_suppression_list(db: Session, contact_value: str, channel: str = "all", reason: str = "opt_out") -> None:
    clean = normalize_contact(contact_value)
    if not clean:
        return
    existing = db.query(SuppressionList).filter(SuppressionList.contact_value == clean).first()
    if not existing:
        db.add(SuppressionList(contact_value=clean, channel=channel, reason=reason))
    lead = db.query(Lead).filter((Lead.email == clean) | (Lead.phone == clean)).first()
    if lead:
        lead.is_suppressed = True
        lead.status = "suppressed"
    db.add(
        AuditLog(
            actor="safety_guard",
            action="contact_suppressed",
            target_type="contact",
            target_id=clean,
            metadata_json=f'{{"channel":"{channel}","reason":"{reason}"}}',
        )
    )
    db.commit()


def can_send_outreach(db: Session, lead: Lead, channel: str) -> tuple[bool, str]:
    if lead.is_suppressed:
        return False, "Lead is marked suppressed"

    if is_contact_suppressed(db, email=lead.email, phone=lead.phone):
        return False, "Contact is on suppression list"

    if channel == "email" and not lead.email:
        return False, "No public email available"

    if channel == "whatsapp":
        if not lead.phone:
            return False, "No phone number available"
        if not lead.whatsapp_opted_in:
            return False, "WhatsApp opt-in required before sending"

    already_sent = (
        db.query(OutreachMessage)
        .filter(
            OutreachMessage.lead_id == lead.id,
            OutreachMessage.channel == channel,
            OutreachMessage.status == "sent",
        )
        .first()
    )
    if already_sent:
        return False, f"Initial {channel} outreach already sent"

    setting = db.query(SystemSetting).first()
    daily_limit = (
        (setting.daily_email_limit if channel == "email" else setting.daily_whatsapp_limit)
        if setting
        else 20
    )

    since = datetime.utcnow() - timedelta(hours=24)
    sent_today = (
        db.query(OutreachMessage)
        .filter(
            OutreachMessage.channel == channel,
            OutreachMessage.status == "sent",
            OutreachMessage.sent_at >= since,
        )
        .count()
    )
    if sent_today >= daily_limit:
        return False, f"Daily {channel} limit ({daily_limit}) reached"

    return True, "Eligible"
