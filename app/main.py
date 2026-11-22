from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agents.business_researcher import fetch_public_website_summary
from app.agents.lead_hunter import hunt_businesses_osm
from app.agents.service_matcher import analyze_and_match_service
from app.auth import authenticate_admin, create_access_token, get_current_user
from app.config import settings
from app.database import Base, SessionLocal, engine, get_db
from app.models import AgentJobLog, Lead, ServiceCatalog, SystemSetting
from app.seed_services import seed_services

app = FastAPI(title=settings.APP_NAME, version="0.2.0")

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


def run_hunting_cycle() -> None:
    db = SessionLocal()
    try:
        setting = db.query(SystemSetting).first()
        if not setting or not setting.hunting_active:
            return

        db.add(
            AgentJobLog(
                agent_name="LeadHunter_Research_Matcher",
                status="running",
                details=f"Hunting cycle started for cities: {setting.target_cities}",
            )
        )
        db.commit()

        cities = [c.strip() for c in (setting.target_cities or "Islamabad,Rawalpindi").split(",") if c.strip()]
        raw_businesses = hunt_businesses_osm(cities=cities, per_city_limit=10)
        services = db.query(ServiceCatalog).all()
        service_by_num = {s.number: s for s in services}

        added_count = 0
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
            added_count += 1

        db.commit()
        db.add(
            AgentJobLog(
                agent_name="LeadHunter_Research_Matcher",
                status="completed",
                details=f"Fetched {len(raw_businesses)} entries; added {added_count} new researched leads.",
            )
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        try:
            db.add(
                AgentJobLog(
                    agent_name="LeadHunter_Research_Matcher",
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
    last_job = db.query(AgentJobLog).order_by(AgentJobLog.id.desc()).first()
    return {
        "user": current_user,
        "hunting_active": setting.hunting_active if setting else False,
        "ai_provider": setting.ai_provider if setting else settings.AI_PROVIDER,
        "active_services_count": services_count,
        "total_leads_count": leads_count,
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
    return [
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
        }
        for l in leads
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
        .card { max-width: 820px; margin: 24px auto; background: #111827; padding: 24px; border-radius: 12px; border: 1px solid #1f2937; }
        input { width: 100%; padding: 10px; margin: 8px 0 16px; border-radius: 8px; border: 1px solid #374151; background: #0f172a; color: #fff; box-sizing: border-box; }
        button { padding: 12px 18px; border: none; border-radius: 8px; background: #2563eb; color: #fff; font-weight: bold; cursor: pointer; }
        button:hover { background: #1d4ed8; }
        .hunt-btn { width: 100%; background: #16a34a; margin-top: 10px; font-size: 15px; }
        .hunt-btn.stop { background: #dc2626; }
        .lead-item { background: #0f172a; border: 1px solid #1e293b; border-radius: 8px; padding: 12px; margin-top: 10px; }
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
          <button onclick="loadAll()">Refresh Status &amp; Leads</button>
        </div>
        <pre id="output">Loading...</pre>
        <h3>Discovered &amp; Matched Leads</h3>
        <div id="leadsList">No leads loaded yet.</div>
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
            `User: ${data.user} | Active Services: ${data.active_services_count} | Leads: ${data.total_leads_count} | Cities: ${data.target_cities}`;
          document.getElementById("output").innerText = JSON.stringify(data, null, 2);

          const lRes = await fetch("/api/leads", { headers });
          const leads = await lRes.json();
          const container = document.getElementById("leadsList");
          if (!leads.length) {
            container.innerHTML = "<p style='color:#94a3b8;'>Hunting cycle abhi chal raha hai ya abhi koi naya business nahi mila. 30–60 sec baad Refresh karein.</p>";
            return;
          }
          container.innerHTML = leads.map(l => `
            <div class="lead-item">
              <strong>${l.business_name}</strong> (${l.city || "Pakistan"} - ${l.category || "N/A"})<br/>
              <span style="color:#38bdf8;">Matched Service: ${l.matched_service}</span><br/>
              <span style="color:#94a3b8;font-size:13px;">Website: ${l.website || "N/A"} | Email: ${l.email || "N/A"}</span><br/>
              <p style="font-size:13px;margin:6px 0 0;">${l.research_summary || ""}</p>
            </div>
          `).join("");
        }

        async function toggleHunting() {
          const res = await fetch("/api/hunting/toggle", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "Authorization": "Bearer " + token
            },
            body: JSON.stringify({ active: !isHunting })
          });
          await loadAll();
        }
      </script>
    </body>
    </html>
    """
