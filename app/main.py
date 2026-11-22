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

app = FastAPI(title=settings.APP_NAME, version="1.0.1")

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
    service_number: Optional[int] = None  # None = Auto-match across all 30 services
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
            exists = db.query(Lead).filter(Lead.dedup_hash == item["dedup_hash"]).first()
            if exists:
                continue

            site_info = fetch_public_website_summary(item.get("website"))
            email = item.get("email") or site_info.get("extracted_email")

            analysis = analyze_and_match_service(
                business_name=item["business_name"],
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
                business_name=item["business_name"],
                website=item.get("website"),
                email=email,
                phone=item.get("phone"),
                category=item.get("category"),
                city=item.get("city"),
                country=item.get("country", "Global"),
                source=item.get("source", "openstreetmap_overpass"),
                dedup_hash=item["dedup_hash"],
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
        button { padding: 12px 18px; border: none; border-radius: 9px; background: #2563eb; color: #fff; font-weight: 600; cursor: pointer; font-size: 14px; }
        button:hover { background: #1d4ed8; }
        .hunt-btn { width: 100%; background: #16a34a; font-size: 16px; padding: 15px; margin-top: 8px; }
        .hunt-btn:hover { background: #15803d; }
        .hunt-btn.stop { background: #dc2626; }
        .hunt-btn.stop:hover { background: #b91c1c; }
        .row2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 14px; }
        .lead-card { background: #070d19; border: 1px solid #1e293b; border-radius: 11px; padding: 15px; margin-top: 12px; }
        .badge { display: inline-block; padding: 3px 9px; border-radius: 999px; font-size: 11px; font-weight: 600; background: #1e293b; color: #38bdf8; }
        .msg-box { background: #0d1526; border-left: 3px solid #38bdf8; padding: 12px; margin-top: 10px; border-radius: 6px; font-size: 13px; white-space: pre-wrap; line-height: 1.45; }
      </style>
    </head>
    <body>
      <div class="wrap">
        <div class="card" id="loginBox" style="max-width:440px; margin: 60px auto;">
          <h2>Harvantra AI Login</h2>
          <p style="color:#94a3b8;font-size:14px;">Sign in to your autonomous client acquisition dashboard</p>
          <input id="username" placeholder="Username" />
          <input id="password" type="password" placeholder="Password" />
          <button style="width:100%;" onclick="login()">Login to Dashboard</button>
          <p id="loginMsg" style="color:#f87171;margin-top:10px;"></p>
        </div>

        <div id="dashBox" style="display:none;">
          <div class="topbar">
            <div class="brand">
              <h1>Harvantra AI – Autonomous Client Engine</h1>
              <p>Founder: Haris Hassan | Worldwide Client Hunting &amp; 30-Service Outreach</p>
            </div>
            <div class="links">
              <a href="https://harvantratechnologies.github.io/" target="_blank">Website</a>
              <a href="https://www.linkedin.com/in/haris-hassan-65b0523a8/" target="_blank">LinkedIn</a>
              <a href="https://github.com/harvantratechnologies" target="_blank">GitHub</a>
            </div>
          </div>

          <div class="grid4">
            <div class="stat"><div class="label">Total Leads</div><div class="val" id="mLeads">0</div></div>
            <div class="stat"><div class="label">Auto-Emails Sent</div><div class="val" id="mSent">0</div></div>
            <div class="stat"><div class="label">SMTP Auto-Send</div><div class="val" id="mSmtp">OFF</div></div>
            <div class="stat"><div class="label">Human Alerts</div><div class="val" id="mAlerts">0</div></div>
          </div>

          <div class="card">
            <h3>1. Select Service &amp; Worldwide Targets</h3>
            <div class="row2">
              <div>
                <label style="font-size:13px;color:#cbd5e1;">Choose Service (All 30 or Specific 1–30)</label>
                <select id="serviceSelect"></select>
              </div>
              <div>
                <label style="font-size:13px;color:#cbd5e1;">Target Worldwide Cities (comma separated)</label>
                <input id="citiesInput" placeholder="Dubai,London,Riyadh,Toronto,Islamabad,Lahore,Karachi" />
              </div>
            </div>
            <div style="display:flex;gap:10px;flex-wrap:wrap;">
              <button onclick="saveConfig()">Save Service &amp; Cities</button>
              <button onclick="loadAll()" style="background:#334155;">Refresh Dashboard</button>
            </div>

            <button id="huntBtn" class="hunt-btn" onclick="toggleHunting()">START AI CLIENT HUNTING</button>
            <p id="jobStatus" style="color:#94a3b8;font-size:13px;margin-top:10px;"></p>
          </div>

          <div class="card">
            <h3>2. Discovered Worldwide Clients &amp; Personalized Outreach (With Your Links)</h3>
            <div id="leadsList">Loading...</div>
          </div>

          <div class="card">
            <h3>3. Client Reply Handler &amp; Conversation Log</h3>
            <input id="simEmail" placeholder="Client Email" />
            <textarea id="simMsg" rows="2" placeholder="Paste or simulate client reply..."></textarea>
            <button onclick="simulateReply()">Process Client Reply</button>
            <div id="convList" style="margin-top:12px;"></div>
          </div>
        </div>
      </div>

      <script>
        let token = "";
        let isHunting = false;

        async function login() {
          const username = document.getElementById("username").value;
          const password = document.getElementById("password").value;
          const res = await fetch("/api/auth/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, password })
          });
          const data = await res.json();
          if (!res.ok) {
            document.getElementById("loginMsg").innerText = data.detail || "Login failed";
            return;
          }
          token = data.access_token;
          document.getElementById("loginBox").style.display = "none";
          document.getElementById("dashBox").style.display = "block";
          await loadServices();
          await loadAll();
        }

        async function loadServices() {
          const res = await fetch("/api/services", {
            headers: { "Authorization": "Bearer " + token }
          });
          const services = await res.json();
          const sel = document.getElementById("serviceSelect");
          sel.innerHTML = `<option value="">All 30 Harvantra Services (AI Auto-Match per Client)</option>` +
            services.map(s => `<option value="${s.number}">#${s.number} — ${s.name}</option>`).join("");
        }

        async function saveConfig() {
          const rawVal = document.getElementById("serviceSelect").value;
          const service_number = rawVal ? parseInt(rawVal, 10) : null;
          const target_cities = document.getElementById("citiesInput").value;
          const res = await fetch("/api/hunting/configure", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "Authorization": "Bearer " + token
            },
            body: JSON.stringify({ service_number, target_cities })
          });
          if (res.ok) {
            alert("Service & target cities saved!");
            await loadAll();
          }
        }

        async function loadAll() {
          const headers = { "Authorization": "Bearer " + token };
          const sRes = await fetch("/api/status", { headers });
          const data = await sRes.json();

          isHunting = data.hunting_active;
          document.getElementById("mLeads").innerText = data.total_leads_count;
          document.getElementById("mSent").innerText = data.emails_sent_automatically;
          document.getElementById("mSmtp").innerText = data.smtp_auto_send_enabled ? "ACTIVE" : "DRAFT ONLY";
          document.getElementById("mAlerts").innerText = data.needs_human_attention;
          document.getElementById("citiesInput").value = data.target_cities || "";
          if (data.selected_service_number) {
            document.getElementById("serviceSelect").value = String(data.selected_service_number);
          }

          const btn = document.getElementById("huntBtn");
          btn.innerText = isHunting ? "STOP AI CLIENT HUNTING (RUNNING AUTOMATICALLY)" : "START AI CLIENT HUNTING";
          btn.className = isHunting ? "hunt-btn stop" : "hunt-btn";

          const lastJob = data.last_job ? `${data.last_job.status}: ${data.last_job.details}` : "Ready for one-click hunt.";
          document.getElementById("jobStatus").innerText = `Status: ${lastJob}`;

          const lRes = await fetch("/api/leads", { headers });
          const leads = await lRes.json();
          const container = document.getElementById("leadsList");
          container.innerHTML = leads.length ? leads.map(l => `
            <div class="lead-card">
              <div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;">
                <strong>${l.business_name}</strong>
                <span class="badge">${l.matched_service}</span>
              </div>
              <div style="color:#94a3b8;font-size:13px;margin-top:4px;">
                Location: ${l.city || "Global"}, ${l.country || ""} | Category: ${l.category || "N/A"} | Email: ${l.email || "N/A"}
              </div>
              <p style="font-size:13px;margin:8px 0;">${l.research_summary || ""}</p>
              ${l.outreach_body ? `<div class="msg-box"><strong>Message [${l.outreach_status}]:</strong> ${l.outreach_note || ""}\nSubject: ${l.outreach_subject}\n\n${l.outreach_body}</div>` : ""}
            </div>
          `).join("") : "<p style='color:#94a3b8;'>Click START AI CLIENT HUNTING to discover global clients and generate messages.</p>";

          const cRes = await fetch("/api/conversations", { headers });
          const convs = await cRes.json();
          document.getElementById("convList").innerHTML = convs.map(c => `
            <div class="lead-card">
              <strong>${c.business_name}</strong> [${c.direction} | ${c.intent}] ${c.needs_human_attention ? "⚠️ HUMAN ALERT" : ""}<br/>
              <div class="msg-box">${c.message_text}</div>
            </div>
          `).join("");
        }

        async function toggleHunting() {
          await fetch("/api/hunting/toggle", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "Authorization": "Bearer " + token
            },
            body: JSON.stringify({ active: !isHunting })
          });
          setTimeout(loadAll, 2000);
        }

        async function simulateReply() {
          const sender_email = document.getElementById("simEmail").value;
          const message_text = document.getElementById("simMsg").value;
          const res = await fetch("/api/webhooks/inbound-reply", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ sender_email, message_text, channel: "email" })
          });
          const data = await res.json();
          alert(res.ok ? `Intent: ${data.intent} | Human Alert: ${data.needs_human_attention}` : data.detail);
          await loadAll();
        }
      </script>
    </body>
    </html>
    """
