from datetime import datetime
import os
from typing import Optional
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agents.business_researcher import fetch_public_website_summary
from app.agents.email_agent import dispatch_email_outreach
from app.agents.lead_hunter import hunt_businesses_worldwide
from app.agents.reply_agent import process_inbound_reply
from app.agents.sales_outreach import generate_personalized_outreach
from app.agents.service_matcher import analyze_and_match_service
from app.auth import authenticate_admin, create_access_token, get_current_user
from app.config import settings
from app.database import Base, SessionLocal, engine, get_db
from app.models import (
    AgentJobLog,
    ConversationLog,
    Lead,
    OutreachMessage,
    ServiceCatalog,
    SuppressionList,
    SystemSetting,
)
from app.seed_services import seed_services

DEFAULT_GLOBAL_CITIES = "Islamabad,Rawalpindi,Lahore,Karachi,Dubai,London,Riyadh,Toronto"

app = FastAPI(title=settings.APP_NAME, version="1.0.2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

scheduler = BackgroundScheduler()


class LoginRequest(BaseModel):
    username: str
    password: str


class HuntingToggleRequest(BaseModel):
    active: bool


class ServiceSelectionRequest(BaseModel):
    service_number: Optional[int] = None
    target_cities: Optional[str] = None


class InboundWebhookPayload(BaseModel):
    sender_email: str
    message_text: str
    channel: str = "email"


def smtp_is_ready() -> bool:
    return bool(
        os.getenv("SMTP_HOST", "").strip()
        and os.getenv("SMTP_USER", "").strip()
        and os.getenv("SMTP_PASSWORD", "").strip()
    )


def run_hunting_cycle() -> None:
    db = SessionLocal()
    try:
        setting = db.query(SystemSetting).first()
        if not setting or not setting.hunting_active:
            return

        cities_str = setting.target_cities or DEFAULT_GLOBAL_CITIES
        cities = [c.strip() for c in cities_str.split(",") if c.strip()] or ["Dubai", "London", "Islamabad"]

        services = db.query(ServiceCatalog).order_by(ServiceCatalog.number.asc()).all()
        service_by_num = {s.number: s for s in services}
        forced_service = (
            service_by_num.get(setting.selected_service_number)
            if setting.selected_service_number
            else None
        )

        mode_label = (
            f"Service #{forced_service.number}: {forced_service.name}"
            if forced_service
            else "All 30 Services (AI Auto-Match)"
        )

        db.add(
            AgentJobLog(
                agent_name="Autonomous_Global_Engine",
                status="running",
                details=f"Mode: {mode_label} | Cities: {', '.join(cities)}",
            )
        )
        db.commit()

        raw_businesses = hunt_businesses_worldwide(cities=cities, per_city_limit=6)

        added_count = 0
        sent_count = 0

        for item in raw_businesses:
            dedup_key = item.get("dedup_hash") or f"{item.get('email','')}|{item.get('business_name','')}"
            exists = db.query(Lead).filter(Lead.dedup_hash == dedup_key).first()
            if exists:
                continue

            biz_name = item.get("business_name") or item.get("company_name") or item.get("name") or "Business"
            site_info = fetch_public_website_summary(item.get("website"))
            email = item.get("email") or site_info.get("extracted_email")

            analysis = analyze_and_match_service(
                business_name=biz_name,
                category=item.get("category") or "business",
                city=item.get("city") or "Global",
                website=item.get("website"),
                website_snippet=site_info.get("snippet", ""),
                services=services,
            )

            matched_svc = forced_service or service_by_num.get(analysis["service_number"])
            match_reason = (
                f"Targeted by Haris for '{forced_service.name}' in {item.get('city') or 'Global'}."
                if forced_service
                else analysis["match_reason"]
            )

            lead = Lead(
                business_name=biz_name,
                website=item.get("website"),
                email=email,
                phone=item.get("phone"),
                category=item.get("category"),
                city=item.get("city"),
                country=item.get("country", "Global"),
                source=item.get("source", "harvantra_directory"),
                dedup_hash=dedup_key,
                research_summary=analysis["research_summary"],
                identified_needs=analysis["identified_needs"],
                matched_service_id=matched_svc.id if matched_svc else None,
                match_reason=match_reason,
                status="researched_and_matched",
            )
            db.add(lead)
            db.commit()
            db.refresh(lead)
            added_count += 1

            if matched_svc:
                msgs = generate_personalized_outreach(lead, matched_svc)
                email_msg = OutreachMessage(
                    lead_id=lead.id,
                    channel="email",
                    subject=msgs["email_subject"],
                    body=msgs["email_body"],
                    status="draft",
                )
                db.add(email_msg)
                db.commit()
                db.refresh(email_msg)

                if lead.email and smtp_is_ready():
                    updated = dispatch_email_outreach(db, lead, email_msg)
                    if updated.status == "sent":
                        sent_count += 1

        db.add(
            AgentJobLog(
                agent_name="Autonomous_Global_Engine",
                status="completed",
                details=f"[{mode_label}] Targets: {len(raw_businesses)} | New Leads: {added_count} | Auto-Sent: {sent_count}",
            )
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        try:
            db.add(
                AgentJobLog(
                    agent_name="Autonomous_Global_Engine",
                    status="failed",
                    details=str(exc)[:500],
                )
            )
            db.commit()
        except Exception:
            pass
    finally:
        db.close()


@app.on_event("startup")
def on_startup():
    with engine.begin() as conn:
        conn.execute(
            text("ALTER TABLE IF EXISTS system_settings ADD COLUMN IF NOT EXISTS selected_service_number INTEGER")
        )
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_services(db)
        setting = db.query(SystemSetting).first()
        if not setting:
            db.add(
                SystemSetting(
                    hunting_active=False,
                    selected_service_number=None,
                    ai_provider=settings.AI_PROVIDER,
                    target_cities=DEFAULT_GLOBAL_CITIES,
                )
            )
            db.commit()
    finally:
        db.close()

    if not scheduler.running:
        scheduler.add_job(run_hunting_cycle, "interval", minutes=10, id="hunting_loop", replace_existing=True)
        scheduler.start()


@app.on_event("shutdown")
def on_shutdown():
    if scheduler.running:
        scheduler.shutdown(wait=False)


@app.get("/health")
def health_check():
    return {"status": "ok", "app": settings.APP_NAME, "timestamp": datetime.utcnow().isoformat()}


@app.post("/api/auth/login")
def login(payload: LoginRequest):
    if not authenticate_admin(payload.username, payload.password):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_access_token(subject=payload.username)
    return {"access_token": token, "token_type": "bearer", "user": payload.username}


@app.get("/api/services")
def list_services(db: Session = Depends(get_db), current_user: str = Depends(get_current_user)):
    services = db.query(ServiceCatalog).order_by(ServiceCatalog.number.asc()).all()
    return [
        {
            "id": s.id,
            "number": s.number,
            "name": s.name,
            "category": s.category,
            "summary": s.summary,
            "is_active": s.is_active,
        }
        for s in services
    ]


@app.post("/api/hunting/configure")
def configure_hunting(
    payload: ServiceSelectionRequest,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    setting = db.query(SystemSetting).first()
    if not setting:
        setting = SystemSetting(hunting_active=False, target_cities=DEFAULT_GLOBAL_CITIES)
        db.add(setting)

    if payload.service_number is not None:
        svc = db.query(ServiceCatalog).filter(ServiceCatalog.number == payload.service_number).first()
        if not svc:
            raise HTTPException(status_code=404, detail="Service number not found")
        setting.selected_service_number = payload.service_number
    else:
        setting.selected_service_number = None

    if payload.target_cities and payload.target_cities.strip():
        setting.target_cities = payload.target_cities.strip()

    db.commit()
    db.refresh(setting)
    return {
        "selected_service_number": setting.selected_service_number,
        "target_cities": setting.target_cities,
        "updated_by": current_user,
    }


@app.get("/api/status")
def get_system_status(db: Session = Depends(get_db), current_user: str = Depends(get_current_user)):
    setting = db.query(SystemSetting).first()
    services_count = db.query(ServiceCatalog).filter(ServiceCatalog.is_active == True).count()
    leads_count = db.query(Lead).count()
    outreach_count = db.query(OutreachMessage).count()
    sent_count = db.query(OutreachMessage).filter(OutreachMessage.status == "sent").count()
    human_alerts = db.query(Lead).filter(Lead.status == "needs_human_attention").count()
    suppressed_count = db.query(SuppressionList).count()
    last_job = db.query(AgentJobLog).order_by(AgentJobLog.id.desc()).first()
    return {
        "user": current_user,
        "hunting_active": setting.hunting_active if setting else False,
        "selected_service_number": setting.selected_service_number if setting else None,
        "smtp_auto_send_enabled": smtp_is_ready(),
        "ai_provider": setting.ai_provider if setting else settings.AI_PROVIDER,
        "active_services_count": services_count,
        "total_leads_count": leads_count,
        "outreach_messages_prepared": outreach_count,
        "emails_sent_automatically": sent_count,
        "needs_human_attention": human_alerts,
        "suppressed_contacts": suppressed_count,
        "target_cities": setting.target_cities if setting else DEFAULT_GLOBAL_CITIES,
        "last_job": {
            "status": last_job.status,
            "details": last_job.details,
            "at": last_job.created_at.isoformat() if last_job.created_at else None,
        }
        if last_job
        else None,
    }


@app.post("/api/hunting/toggle")
def toggle_hunting(
    payload: HuntingToggleRequest,
    db: Session = Depends(get_db),
    current_user: str = Depends(get_current_user),
):
    setting = db.query(SystemSetting).first()
    if not setting:
        setting = SystemSetting(hunting_active=payload.active, target_cities=DEFAULT_GLOBAL_CITIES)
        db.add(setting)
    else:
        setting.hunting_active = payload.active
        if not setting.target_cities:
            setting.target_cities = DEFAULT_GLOBAL_CITIES
    db.commit()
    db.refresh(setting)

    if setting.hunting_active and scheduler.running:
        scheduler.add_job(run_hunting_cycle, "date", run_date=datetime.now(), id="immediate_hunt", replace_existing=True)

    return {"hunting_active": setting.hunting_active, "updated_by": current_user}


@app.get("/api/leads")
def list_leads(db: Session = Depends(get_db), current_user: str = Depends(get_current_user)):
    leads = db.query(Lead).order_by(Lead.id.desc()).limit(60).all()
    services = {s.id: f"#{s.number} {s.name}" for s in db.query(ServiceCatalog).all()}
    result = []
    for l in leads:
        email_msg = (
            db.query(OutreachMessage)
            .filter(OutreachMessage.lead_id == l.id, OutreachMessage.channel == "email")
            .first()
        )
        result.append(
            {
                "id": l.id,
                "business_name": l.business_name,
                "city": l.city,
                "country": l.country,
                "category": l.category,
                "website": l.website,
                "email": l.email,
                "matched_service": services.get(l.matched_service_id, "Pending"),
                "research_summary": l.research_summary,
                "status": l.status,
                "outreach_subject": email_msg.subject if email_msg else None,
                "outreach_body": email_msg.body if email_msg else None,
                "outreach_status": email_msg.status if email_msg else None,
                "outreach_note": email_msg.error_message if email_msg else None,
            }
        )
    return result


@app.post("/api/webhooks/inbound-reply")
def inbound_reply_webhook(payload: InboundWebhookPayload, db: Session = Depends(get_db)):
    clean_sender = payload.sender_email.strip().lower()
    lead = db.query(Lead).filter(Lead.email.ilike(clean_sender)).first()
    if not lead:
        raise HTTPException(status_code=404, detail="No matching lead found for sender")
    return process_inbound_reply(db, lead, payload.channel, payload.message_text)


@app.get("/api/conversations")
def list_conversations(db: Session = Depends(get_db), current_user: str = Depends(get_current_user)):
    logs = db.query(ConversationLog).order_by(ConversationLog.id.desc()).limit(40).all()
    leads = {l.id: l.business_name for l in db.query(Lead).all()}
    return [
        {
            "id": c.id,
            "business_name": leads.get(c.lead_id, f"Lead #{c.lead_id}"),
            "channel": c.channel,
            "direction": c.direction,
            "intent": c.intent,
            "message_text": c.message_text,
            "needs_human_attention": c.needs_human_attention,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in logs
    ]


@app.get("/", response_class=HTMLResponse)
def home():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1.0" />
      <title>Harvantra AI – Autonomous SaaS Command Center</title>
      <style>
        * { box-sizing: border-box; }
        body { font-family: Inter, Arial, sans-serif; background: #070d19; color: #f1f5f9; margin: 0; padding: 20px; }
        .wrap { max-width: 1120px; margin: 0 auto; }
        .topbar { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 12px; background: #0f172a; border: 1px solid #1e293b; padding: 18px 22px; border-radius: 14px; margin-bottom: 18px; }
        .brand h1 { margin: 0; font-size: 20px; color: #38bdf8; }
        .brand p { margin: 4px 0 0; font-size: 13px; color: #94a3b8; }
        .links a { color: #93c5fd; text-decoration: none; margin-left: 14px; font-size: 13px; }
        .grid4 { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; margin-bottom: 18px; }
        .stat { background: #0f172a; border: 1px solid #1e293b; border-radius: 12px; padding: 16px; }
        .stat .label { font-size: 12px; color: #94a3b8; text-transform: uppercase; }
        .stat .val { font-size: 26px; font-weight: bold; margin-top: 6px; color: #f8fafc; }
        .card { background: #0f172a; border: 1px solid #1e293b; border-radius: 14px; padding: 20px; margin-bottom: 18px; }
        h2, h3 { margin-top: 0; }
        select, input, textarea { width: 100%; padding: 11px 12px; margin: 8px 0 14px; border-radius: 9px; border: 1px solid #334155; background: #070d19; color: #f8fafc; font-size: 14px; }
        button { padding: 12px 18px; border: none; border-radius: 9px; background: #2563eb; color: #fff; font-weight: 600; cursor: pointer; font-size: 14
