from datetime import datetime
from email.message import EmailMessage
import os
import smtplib
from sqlalchemy.orm import Session
from app.core.safety_guard import can_send_outreach
from app.models import AuditLog, ConversationLog, Lead, OutreachMessage


def send_email_via_smtp(to_email: str, subject: str, body: str) -> tuple[bool, str]:
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_password = os.getenv("SMTP_PASSWORD", "").strip()
    from_email = os.getenv("SMTP_FROM_EMAIL", smtp_user).strip()

    if not (smtp_host and smtp_user and smtp_password and from_email):
        return False, "SMTP credentials not configured (saved as draft)."

    msg = EmailMessage()
    msg["From"] = f"Haris Hassan - Harvantra Technologies <{from_email}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20) as server:
                server.login(smtp_user, smtp_password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
                server.starttls()
                server.login(smtp_user, smtp_password)
                server.send_message(msg)
        return True, "Sent automatically"
    except Exception as exc:
        return False, str(exc)[:300]


def dispatch_email_outreach(db: Session, lead: Lead, outreach: OutreachMessage) -> OutreachMessage:
    eligible, reason = can_send_outreach(db, lead, "email")
    if not eligible:
        outreach.status = "draft"
        outreach.error_message = reason
        db.commit()
        return outreach

    sent, info = send_email_via_smtp(
        lead.email,
        outreach.subject or "Harvantra Technologies — IT & Security Solutions",
        outreach.body,
    )
    if sent:
        outreach.status = "sent"
        outreach.sent_at = datetime.utcnow()
        outreach.error_message = None
        lead.status = "contacted"
        db.add(
            ConversationLog(
                lead_id=lead.id,
                channel="email",
                direction="outbound",
                intent="initial_outreach",
                message_text=f"Subject: {outreach.subject}\n\n{outreach.body}",
                needs_human_attention=False,
            )
        )
        db.add(
            AuditLog(
                actor="email_agent",
                action="email_sent",
                target_type="lead",
                target_id=str(lead.id),
                metadata_json=f'{{"to":"{lead.email}"}}',
            )
        )
    else:
        outreach.status = "draft"
        outreach.error_message = info

    db.commit()
    db.refresh(outreach)
    return outreach
