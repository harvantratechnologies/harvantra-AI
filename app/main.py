from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import authenticate_admin, create_access_token, get_current_user
from app.config import settings
from app.database import Base, SessionLocal, engine, get_db
from app.models import ServiceCatalog, SystemSetting
from app.seed_services import seed_services

app = FastAPI(title=settings.APP_NAME, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class LoginRequest(BaseModel):
    username: str
    password: str


class HuntingToggleRequest(BaseModel):
    active: bool


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


@app.get("/health")
def health_check():
    return {"status": "ok", "app": settings.APP_NAME}


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
    return {
        "user": current_user,
        "hunting_active": setting.hunting_active if setting else False,
        "ai_provider": setting.ai_provider if setting else settings.AI_PROVIDER,
        "active_services_count": services_count,
        "target_cities": setting.target_cities if setting else "Islamabad,Rawalpindi",
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
    return {"hunting_active": setting.hunting_active, "updated_by": current_user}


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


@app.get("/", response_class=HTMLResponse)
def home():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1.0" />
      <title>Harvantra AI – Stage 1 Command Center</title>
      <style>
        body { font-family: Arial, sans-serif; background: #0b1120; color: #f8fafc; margin: 0; padding: 30px; }
        .card { max-width: 520px; margin: 40px auto; background: #111827; padding: 24px; border-radius: 12px; border: 1px solid #1f2937; }
        input { width: 100%; padding: 10px; margin: 8px 0 16px; border-radius: 8px; border: 1px solid #374151; background: #0f172a; color: #fff; box-sizing: border-box; }
        button { width: 100%; padding: 12px; border: none; border-radius: 8px; background: #2563eb; color: #fff; font-weight: bold; cursor: pointer; }
        button:hover { background: #1d4ed8; }
        .hunt-btn { background: #16a34a; margin-top: 12px; }
        .hunt-btn.stop { background: #dc2626; }
        pre { background: #090d16; padding: 12px; border-radius: 8px; overflow-x: auto; font-size: 12px; }
      </style>
    </head>
    <body>
      <div class="card" id="loginBox">
        <h2>Harvantra AI Login</h2>
        <p style="color:#94a3b8;font-size:14px;">Sign in to test Stage 1 Backend &amp; Neon DB</p>
        <input id="username" placeholder="Username (e.g. haris)" />
        <input id="password" type="password" placeholder="Password" />
        <button onclick="login()">Login</button>
        <p id="loginMsg" style="color:#f87171;"></p>
      </div>

      <div class="card" id="dashBox" style="display:none;">
        <h2>Harvantra AI Command Center</h2>
        <p id="statusText" style="color:#94a3b8;"></p>
        <button id="huntBtn" class="hunt-btn" onclick="toggleHunting()">START AI CLIENT HUNTING</button>
        <pre id="output">Loading...</pre>
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
          await refreshStatus();
        }

        async function refreshStatus() {
          const res = await fetch("/api/status", {
            headers: { "Authorization": "Bearer " + token }
          });
          const data = await res.json();
          isHunting = data.hunting_active;
          const btn = document.getElementById("huntBtn");
          btn.innerText = isHunting ? "STOP AI CLIENT HUNTING (ACTIVE)" : "START AI CLIENT HUNTING";
          btn.className = isHunting ? "hunt-btn stop" : "hunt-btn";
          document.getElementById("statusText").innerText =
            `Logged in as ${data.user} | Active Services: ${data.active_services_count} | Cities: ${data.target_cities}`;
          document.getElementById("output").innerText = JSON.stringify(data, null, 2);
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
          await refreshStatus();
        }
      </script>
    </body>
    </html>
    """
