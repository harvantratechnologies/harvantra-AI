from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agents.business_researcher import fetch_public_website_summary
from app.agents.email_agent import dispatch_email_outreach
from app.agents.lead_hunter import hunt_businesses_osm
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

app = FastAPI(title=settings.APP_NAME, version="0.3.0")

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


class InboundWebhookPayload(BaseModel):
    sender_email: str
    message_text: str
    channel: str = "email"


def run_hunting_cycle() -> None:
    db = SessionLocal()
    try:
        setting = db.query(SystemSetting).first()
        if not setting or not setting.hunting_active:
            return

        db.add(
            AgentJobLog(
                agent_name="Autonomous_Pipeline",
                status="running",
                details=f"Hunting + Research + Outreach cycle started for: {setting.target_cities}",
            )
        )
        db.commit()

        cities = [c.strip() for c in (setting.target_cities or "Islamabad,Rawalpindi").split(",") if c.strip()]
        raw_businesses = hunt_businesses_osm(cities=cities, per_city_limit=10)
        services = db.query(ServiceCatalog).all()
        service_by_num = {s.number: s for s in services}

        added_count = 0
        drafted_count = 0

        for item in raw_businesses:
            exists = db.query(Lead).filter(Lead.dedup_hash == item["dedup_hash"]).first()
            if exists:
                continue

            site_info = fetch_public_website_summary(item.get("website"))
            email = item.get("email") or site_info.get("extracted_email")

            analysis = analyze_and_match_service(
                business_name=item["business_name"],
                category=item.get("category") or "business",
                city=item.get("city") or "Islamabad",
                website=item.get("website"),
                website_snippet=site_info.get("snippet", ""),
                services=services,
            )

            matched_svc = service_by_num.get(analysis["service_number"])

            lead = Lead(
                business_name=item["business_name"],
                website=item.get("website"),
                email=email,
                phone=item.get("phone"),
                category=item.get("category"),
                city=item.get("city"),
                country=item.get("country", "Pakistan"),
                source=item.get("source", "openstreetmap_overpass"),
                dedup_hash=item["dedup_hash"],
                research_summary=analysis["research_summary"],
                identified_needs=analysis["identified_needs"],
                matched_service_id=matched_svc.id if matched_svc else None,
                match_reason=analysis["match_reason"],
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
                wa_msg = OutreachMessage(
                    lead_id=lead.id,
                    channel="whatsapp",
                    subject=None,
                    body=msgs["whatsapp_body"],
                    status="draft",
                )
                db.add(email_msg)
                db.add(wa_msg)
                db.commit()
                db.refresh(email_msg)
                drafted_count += 1

                if lead.email:
                    dispatch_email_outreach(db, lead, email_msg)

        db.add(
            AgentJobLog(
                agent_name="Autonomous_Pipeline",
                status="completed",
                details=f"Fetched {len(raw_businesses)} entries; added {added_count} new leads; generated {drafted_count} personalized outreach packages.",
            )
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        try:
            db.add(
                AgentJobLog(
                    agent_name="Autonomous_Pipeline",
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
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_services(db)
        setting = db.query(SystemSetting).first()
        if not setting:
            db.add(SystemSetting(hunting_active=False, ai_provider=settings.AI_PROVIDER))
            db.commit()
    finally:
        db.close()

    if not scheduler.running:
        scheduler.add_job(run_hunting_cycle, "interval", minutes=15, id="hunting_loop", replace_existing=True)
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
        "ai_provider": setting.ai_provider if setting else settings.AI_PROVIDER,
        "active_services_count": services_count,
        "total_leads_count": leads_count,
        "outreach_drafts_or_sent": outreach_count,
        "emails_sent": sent_count,
        "needs_human_attention": human_alerts,
        "suppressed_contacts": suppressed_count,
        "target_cities": setting.target_cities if setting else "Islamabad,Rawalpindi",
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
        setting = SystemSetting(hunting_active=payload.active)
        db.add(setting)
    else:
        setting.hunting_active = payload.active
    db.commit()
    db.refresh(setting)

    if setting.hunting_active and scheduler.running:
        scheduler.add_job(run_hunting_cycle, "date", run_date=datetime.now(), id="immediate_hunt", replace_existing=True)

    return {"hunting_active": setting.hunting_active, "updated_by": current_user}


@app.get("/api/leads")
def list_leads(db: Session = Depends(get_db), current_user: str = Depends(get_current_user)):
    leads = db.query(Lead).order_by(Lead.id.desc()).limit(50).all()
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
      <title>Harvantra AI – Autonomous Command Center</title>
      <style>
        body { font-family: Arial, sans-serif; background: #0b1120; color: #f8fafc; margin: 0; padding: 24px; }
        .card { max-width: 900px; margin: 20px auto; background: #111827; padding: 24px; border-radius: 12px; border: 1px solid #1f2937; }
        input, textarea { width: 100%; padding: 10px; margin: 8px 0 14px; border-radius: 8px; border: 1px solid #374151; background: #0f172a; color: #fff; box-sizing: border-box; }
        button { padding: 12px 18px; border: none; border-radius: 8px; background: #2563eb; color: #fff; font-weight: bold; cursor: pointer; }
        button:hover { background: #1d4ed8; }
        .hunt-btn { width: 100%; background: #16a34a; margin-top: 10px; font-size: 15px; }
        .hunt-btn.stop { background: #dc2626; }
        .lead-item { background: #0f172a; border: 1px solid #1e293b; border-radius: 8px; padding: 14px; margin-top: 12px; }
        .msg-box { background: #090d16; border-left: 3px solid #38bdf8; padding: 10px; margin-top: 8px; font-size: 13px; white-space: pre-wrap; }
        pre { background: #090d16; padding: 12px; border-radius: 8px; overflow-x: auto; font-size: 12px; }
      </style>
    </head>
    <body>
      <div class="card" id="loginBox" style="max-width:460px;">
        <h2>Harvantra AI Login</h2>
        <p style="color:#94a3b8;font-size:14px;">Sign in to Harvantra AI Command Center</p>
        <input id="username" placeholder="Username" />
        <input id="password" type="password" placeholder="Password" />
        <button style="width:100%;" onclick="login()">Login</button>
        <p id="loginMsg" style="color:#f87171;"></p>
      </div>

      <div class="card" id="dashBox" style="display:none;">
        <h2>Harvantra AI – Autonomous Client Acquisition</h2>
        <p id="statusText" style="color:#94a3b8;"></p>
        <button id="huntBtn" class="hunt-btn" onclick="toggleHunting()">START AI CLIENT HUNTING</button>
        <div style="margin-top:12px;">
          <button onclick="loadAll()">Refresh Status, Leads &amp; Inbox</button>
        </div>
        <pre id="output">Loading...</pre>

        <h3>Discovered Leads &amp; Tailored Outreach Messages</h3>
        <div id="leadsList">Loading...</div>

        <h3 style="margin-top:28px;">AI Reply Simulator &amp; Conversation Log</h3>
        <input id="simEmail" placeholder="Lead Email (e.g. info@example.com)" />
        <textarea id="simMsg" rows="2" placeholder="Simulate client reply (e.g. Can you send pricing for VAPT?)"></textarea>
        <button onclick="simulateReply()">Test AI Reply Agent</button>
        <div id="convList" style="margin-top:12px;"></div>
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
          await loadAll();
        }

        async function loadAll() {
          const headers = { "Authorization": "Bearer " + token };
          const sRes = await fetch("/api/status", { headers });
          const data = await sRes.json();
          isHunting = data.hunting_active;
          const btn = document.getElementById("huntBtn");
          btn.innerText = isHunting ? "STOP AI CLIENT HUNTING (RUNNING IN BACKGROUND)" : "START AI CLIENT HUNTING";
          btn.className = isHunting ? "hunt-btn stop" : "hunt-btn";
          document.getElementById("statusText").innerText =
            `User: ${data.user} | Services: ${data.active_services_count} | Leads: ${data.total_leads_count} | Emails Sent: ${data.emails_sent} | Human Alerts: ${data.needs_human_attention}`;
          document.getElementById("output").innerText = JSON.stringify(data, null, 2);

          const lRes = await fetch("/api/leads", { headers });
          const leads = await lRes.json();
          const container = document.getElementById("leadsList");
          container.innerHTML = leads.length ? leads.map(l => `
            <div class="lead-item">
              <strong>${l.business_name}</strong> (${l.city || "Pakistan"} - ${l.category || "N/A"}) | Status: <b>${l.status}</b><br/>
              <span style="color:#38bdf8;">Matched Service: ${l.matched_service}</span><br/>
              <span style="color:#94a3b8;font-size:13px;">Website: ${l.website || "N/A"} | Email: ${l.email || "N/A"}</span>
              <p style="font-size:13px;margin:6px 0;">${l.research_summary || ""}</p>
              ${l.outreach_body ? `<div class="msg-box"><strong>Outreach (${l.outreach_status} - ${l.outreach_note || "Ready"}):</strong>\nSubject: ${l.outreach_subject}\n\n${l.outreach_body}</div>` : ""}
            </div>
          `).join("") : "<p style='color:#94a3b8;'>Click START AI CLIENT HUNTING and wait 30 seconds.</p>";

          const cRes = await fetch("/api/conversations", { headers });
          const convs = await cRes.json();
          document.getElementById("convList").innerHTML = convs.map(c => `
            <div class="lead-item">
              <strong>${c.business_name}</strong> [${c.channel} | ${c.direction} | Intent: ${c.intent}] ${c.needs_human_attention ? "⚠️ HUMAN ALERT" : ""}<br/>
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
          await loadAll();
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
