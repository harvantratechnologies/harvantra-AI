import streamlit as st
import requests
import pandas as pd
import sqlite3
import re
import time
from datetime import datetime
from urllib.parse import quote

# =====================================================
# APP CONFIG
# =====================================================

st.set_page_config(
    page_title="Harvantra AI",
    page_icon="🛡️",
    layout="wide"
)

APP = "Harvantra AI"
DB = "harvantra_crm.db"

COMPANY = "https://harvantratechnologies.github.io/"
GITHUB = "https://github.com/harvantratechnologies"
LINKEDIN = "https://www.linkedin.com/in/haris-hassan-65b0523a8/"

HEADERS = {
    "User-Agent": "HarvantraAI/1.0 (https://harvantratechnologies.github.io/)"
}

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# =====================================================
# 30 OFFICIAL SERVICES + UNIQUE PITCHES
# =====================================================

SERVICES = {
    "Managed SOC & 24/7 Security Monitoring":
        "We can help your team improve security monitoring, alert visibility and incident readiness through managed SOC support.",

    "SIEM Deployment & Management":
        "We can help centralize security logs, improve event correlation and strengthen security visibility through SIEM deployment and management.",

    "Vulnerability Assessment & Management":
        "We can review your digital assets for security weaknesses, prioritize risks and provide practical remediation recommendations.",

    "Penetration Testing (VAPT)":
        "We can conduct an authorized, scoped security assessment to identify exploitable weaknesses and provide a detailed remediation report.",

    "Incident Response & Digital Forensics":
        "We can support incident investigation, evidence preservation and digital forensics readiness to help your organization respond effectively.",

    "Threat Hunting & Detection Engineering":
        "We can help improve threat detection through security log analysis, threat hunting and detection rule development.",

    "Endpoint Detection & Response (EDR)":
        "We can help review endpoint security coverage, suspicious activity visibility and incident containment readiness.",

    "Network Security Assessment & Hardening":
        "We can assess network exposure, configurations and security controls, then recommend practical hardening improvements.",

    "Firewall Security & Management":
        "We can review firewall policies, access rules and exposed services to help reduce unnecessary network exposure.",

    "Cloud Security — AWS & Azure":
        "We can review AWS and Azure security configurations, access permissions and cloud infrastructure risks.",

    "Cloud Security Posture Management":
        "We can help identify cloud misconfigurations, excessive permissions and security posture gaps.",

    "Identity & Access Management":
        "We can help review identity security, privileged access, authentication and access control configurations.",

    "Zero Trust Security":
        "We can help plan stronger identity verification, least-privilege access and Zero Trust security controls.",

    "Web & API Security Testing":
        "We can assess web applications and APIs for common security weaknesses, authentication issues and configuration risks.",

    "Mobile Application Security Testing":
        "We can review mobile application security, data storage, authentication and application-level weaknesses.",

    "Security Architecture & Risk Assessment":
        "We can help review your security architecture, identify major risks and develop a practical security improvement roadmap.",

    "Security Compliance & GRC":
        "We can support security control reviews, risk documentation and governance and compliance improvement activities.",

    "Security Awareness & Phishing Simulation":
        "We can help improve employee security awareness through training and authorized phishing simulation exercises.",

    "Threat Intelligence & Dark-Web Monitoring":
        "We can help improve threat awareness through relevant threat intelligence and monitoring of exposed organizational information.",

    "Ransomware Protection & Backup Security":
        "We can review backup security, ransomware readiness and recovery procedures to improve business resilience.",

    "Cloud Migration & Infrastructure Management":
        "We can support secure cloud migration planning and infrastructure management for reliable business operations.",

    "Server Management & Hardening":
        "We can review server configurations, unnecessary services and access controls to recommend security hardening.",

    "Network Design, VPN & Secure Remote Access":
        "We can help plan secure network connectivity, VPN configuration and remote access controls.",

    "DevSecOps & CI/CD Security":
        "We can help integrate security checks into development workflows and CI/CD pipelines.",

    "Docker & Container Security":
        "We can review container configurations, image security and runtime permissions to identify container security risks.",

    "Website Security & Maintenance":
        "We can review website security, identify common weaknesses and recommend maintenance and hardening improvements.",

    "Database Security & Management":
        "We can review database access, permissions, configuration and backup security practices.",

    "Backup & Disaster Recovery":
        "We can help assess backup practices and disaster recovery readiness to improve operational resilience.",

    "IT Infrastructure Monitoring":
        "We can help improve infrastructure visibility through monitoring of system health, availability and operational issues.",

    "Managed IT Support & Helpdesk":
        "We can provide managed IT support and helpdesk assistance for routine technical and infrastructure requirements."
}

# =====================================================
# DATABASE
# =====================================================

def db():
    return sqlite3.connect(DB, check_same_thread=False)


def init_db():
    con = db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_name TEXT,
            website TEXT,
            phone TEXT,
            email TEXT,
            address TEXT,
            service TEXT,
            source TEXT,
            status TEXT DEFAULT 'New',
            notes TEXT,
            created_at TEXT
        )
    """)
    con.commit()
    con.close()


def all_leads():
    con = db()
    df = pd.read_sql_query(
        "SELECT * FROM leads ORDER BY id DESC", con
    )
    con.close()
    return df


def save_lead(data):
    con = db()

    con.execute("""
        INSERT INTO leads (
            business_name, website, phone, email,
            address, service, source, status, notes, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("business_name", ""),
        data.get("website", ""),
        data.get("phone", ""),
        data.get("email", ""),
        data.get("address", ""),
        data.get("service", ""),
        data.get("source", ""),
        data.get("status", "New"),
        data.get("notes", ""),
        datetime.now().isoformat(timespec="seconds")
    ))

    con.commit()
    con.close()


def update_status(lead_id, status):
    con = db()
    con.execute(
        "UPDATE leads SET status=? WHERE id=?",
        (status, int(lead_id))
    )
    con.commit()
    con.close()


def delete_lead(lead_id):
    con = db()
    con.execute(
        "DELETE FROM leads WHERE id=?",
        (int(lead_id),)
    )
    con.commit()
    con.close()


def save_discovered(records):
    current = all_leads()
    existing = set()

    if not current.empty:
        existing = set(
            (
                str(r["business_name"]).lower(),
                str(r["website"]).lower()
            )
            for _, r in current.iterrows()
        )

    count = 0

    for r in records:
        key = (
            r["business_name"].lower(),
            r["website"].lower()
        )

        if key in existing:
            continue

        save_lead(r)
        existing.add(key)
        count += 1

    return count


# =====================================================
# FREE GEOCODING - NOMINATIM
# =====================================================

@st.cache_data(ttl=86400, show_spinner=False)
def geocode_location(location):
    response = requests.get(
        NOMINATIM_URL,
        params={
            "q": location,
            "format": "jsonv2",
            "limit": 1
        },
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()
    results = response.json()

    if not results:
        raise ValueError(
            "Location nahi mili. City aur country ka naam check karein."
        )

    return {
        "lat": float(results[0]["lat"]),
        "lon": float(results[0]["lon"]),
        "display_name": results[0]["display_name"]
    }


# =====================================================
# FREE BUSINESS DISCOVERY - OVERPASS
# =====================================================

def discover_businesses(location, radius_km, limit):
    place = geocode_location(location)

    lat = place["lat"]
    lon = place["lon"]
    radius = int(radius_km * 1000)

    # Search only businesses with a website tag.
    query = f"""
    [out:json][timeout:35];
    (
      nwr(around:{radius},{lat},{lon})[name][website];
      nwr(around:{radius},{lat},{lon})[name]["contact:website"];
    );
    out center tags;
    """

    response = requests.post(
        OVERPASS_URL,
        data={"data": query},
        headers=HEADERS,
        timeout=60
    )

    response.raise_for_status()
    elements = response.json().get("elements", [])

    records = []
    seen = set()

    business_keys = [
        "shop", "office", "amenity", "craft",
        "tourism", "healthcare", "industrial",
        "leisure", "club"
    ]

    for item in elements:
        tags = item.get("tags", {})

        name = tags.get("name", "").strip()
        website = (
            tags.get("website")
            or tags.get("contact:website")
            or ""
        ).strip()

        if not name or not website:
            continue

        # Exclude objects without a recognizable business category.
        if not any(key in tags for key in business_keys):
            continue

        if website.startswith("www."):
            website = "https://" + website

        if not website.startswith(("http://", "https://")):
            continue

        key = (name.lower(), website.lower())

        if key in seen:
            continue

        seen.add(key)

        phone = (
            tags.get("contact:phone")
            or tags.get("phone")
            or ""
        )

        email = (
            tags.get("contact:email")
            or tags.get("email")
            or ""
        )

        address = ", ".join(
            x for x in [
                tags.get("addr:street", ""),
                tags.get("addr:city", ""),
                tags.get("addr:state", ""),
                tags.get("addr:country", "")
            ] if x
        )

        if not address:
            address = place["display_name"]

        category = next(
            (key for key in business_keys if key in tags),
            "business"
        )

        records.append({
            "business_name": name,
            "website": website,
            "phone": phone,
            "email": email,
            "address": address,
            "service": list(SERVICES.keys())[0],
            "source": "OpenStreetMap / Overpass",
            "status": "New",
            "notes": f"OSM category: {category}. Verify details before outreach."
        })

        if len(records) >= limit:
            break

    return records


# =====================================================
# OUTREACH MESSAGE GENERATOR
# =====================================================

def generate_email(name, service, website=""):
    pitch = SERVICES[service]

    subject = f"IT & Cybersecurity Support for {name}"

    body = f"""Hello {name} Team,

I hope you are doing well.

I am reaching out from Harvantra Technologies, a Pakistan-based IT and cybersecurity services company.

We provide {service}.

How this may help your organization:
{pitch}

We would welcome an opportunity to understand your requirements and discuss whether our services could be relevant.

Company Website:
{COMPANY}

GitHub Portfolio:
{GITHUB}

Founder LinkedIn:
{LINKEDIN}
"""

    if website:
        body += f"\nYour Website: {website}\n"

    body += """
If this is relevant to your team, please let us know a suitable time for a brief discussion.

If you do not wish to receive further messages, please let us know.

Regards,
Harvantra Technologies
"""

    return subject, body


def generate_whatsapp(name, service, website=""):
    pitch = SERVICES[service]

    message = f"""Hello {name} Team,

I am reaching out from Harvantra Technologies.

We provide {service}.

{pitch}

Company Website:
{COMPANY}

GitHub Portfolio:
{GITHUB}

Founder LinkedIn:
{LINKEDIN}
"""

    if website:
        message += f"\nYour Website: {website}\n"

    message += """
Would your team be open to a brief discussion?

If you do not wish to receive further messages, please let us know.
"""

    return message


def whatsapp_url(phone, message):
    number = re.sub(r"\D", "", str(phone))

    if not number:
        return ""

    return f"https://wa.me/{number}?text={quote(message)}"


def email_url(email, subject, message):
    if not email or "@" not in email:
        return ""

    return (
        f"mailto:{email}"
        f"?subject={quote(subject)}"
        f"&body={quote(message)}"
    )


# =====================================================
# CSV IMPORT / EXPORT
# =====================================================

def import_csv(file):
    df = pd.read_csv(file)
    df.columns = [str(c).strip().lower() for c in df.columns]

    if "business_name" not in df.columns:
        raise ValueError("CSV mein business_name column required hai.")

    count = 0

    for _, row in df.iterrows():
        name = str(row.get("business_name", "")).strip()

        if not name or name.lower() == "nan":
            continue

        service = str(row.get("service", "")).strip()

        if service not in SERVICES:
            service = list(SERVICES.keys())[0]

        save_lead({
            "business_name": name,
            "website": str(row.get("website", "")),
            "phone": str(row.get("phone", "")),
            "email": str(row.get("email", "")),
            "address": str(row.get("address", "")),
            "service": service,
            "source": "CSV Import",
            "status": "New",
            "notes": str(row.get("notes", ""))
        })

        count += 1

    return count


# =====================================================
# MAIN APP
# =====================================================

init_db()

st.title("🛡️ Harvantra AI")
st.caption(
    "Free Business Discovery | 30 Services | Outreach | CRM"
)

st.sidebar.title("Harvantra Technologies")

page = st.sidebar.radio(
    "Navigation",
    [
        "Dashboard",
        "Business Discovery",
        "All Leads CRM",
        "30 Service Categories",
        "Outreach Studio",
        "Add Lead",
        "Import / Export",
        "About & Settings"
    ]
)

# =====================================================
# DASHBOARD
# =====================================================

if page == "Dashboard":
    leads = all_leads()

    total = len(leads)

    def count_status(status):
        return int((leads["status"] == status).sum()) if total else 0

    a, b, c, d, e = st.columns(5)

    a.metric("Total Leads", total)
    b.metric("New", count_status("New"))
    c.metric("Contacted", count_status("Contacted"))
    d.metric("Replied", count_status("Replied"))
    e.metric("Clients", count_status("Client"))

    st.divider()
    st.subheader("Recent Leads")

    if total:
        st.dataframe(
            leads.head(15),
            use_container_width=True,
            hide_index=True
        )

        st.subheader("Lead Status")
        st.bar_chart(leads["status"].value_counts())
    else:
        st.info("Start by discovering or adding your first business leads.")

    st.subheader("Harvantra's 30 Services")
    st.write(f"**{len(SERVICES)} service categories available.**")


# =====================================================
# BUSINESS DISCOVERY
# =====================================================

elif page == "Business Discovery":
    st.header("🌍 Free Business Discovery")

    st.info(
        "No API key required. Searches OpenStreetMap data through Overpass. "
        "Results are limited by available OSM data and public server capacity."
    )

    with st.form("search_form"):
        location = st.text_input(
            "City / Location",
            placeholder="Islamabad, Pakistan"
        )

        radius = st.slider(
            "Search radius (km)",
            1, 2, 3, 5,
            value=3
        )

        limit = st.slider(
            "Maximum results",
            5, 50, 15
        )

        service = st.selectbox(
            "Assign relevant Harvantra service",
            list(SERVICES.keys())
        )

        submit = st.form_submit_button("🔎 Find Businesses")

    if submit:
        if not location.strip():
            st.error("Location enter karein.")
        else:
            try:
                with st.spinner("Searching OpenStreetMap..."):
                    found = discover_businesses(
                        location,
                        radius,
                        limit
                    )

                for item in found:
                    item["service"] = service

                st.session_state["found_leads"] = found

                st.success(f"{len(found)} businesses found.")

            except Exception as error:
                st.error(f"Search failed: {error}")

    found = st.session_state.get("found_leads", [])

    if found:
        st.dataframe(
            pd.DataFrame(found),
            use_container_width=True,
            hide_index=True
        )

        if st.button("💾 Save Results to CRM"):
            saved = save_discovered(found)
            st.success(f"{saved} new leads saved.")


# =====================================================
# ALL LEADS CRM
# =====================================================

elif page == "All Leads CRM":
    st.header("📋 All Leads")

    leads = all_leads()

    if leads.empty:
        st.info("No leads yet.")
    else:
        search = st.text_input("Search business")

        filtered = leads.copy()

        if search:
            filtered = filtered[
                filtered["business_name"].str.contains(
                    search, case=False, na=False
                )
            ]

        st.dataframe(
            filtered,
            use_container_width=True,
            hide_index=True
        )

        st.divider()
        st.subheader("Update Lead Status")

        lead_ids = filtered["id"].tolist()

        if lead_ids:
            selected = st.selectbox("Lead ID", lead_ids)

            statuses = [
                "New", "Qualified", "Contacted", "Replied",
                "Meeting", "Proposal", "Client",
                "Not Interested", "Do Not Contact"
            ]

            status = st.selectbox("New Status", statuses)

            if st.button("Update Status"):
                update_status(selected, status)
                st.success("Status updated. Refresh page to see changes.")

            if st.button("Delete Lead"):
                delete_lead(selected)
                st.success("Lead deleted. Refresh page.")


# =====================================================
# 30 SERVICE CATEGORIES
# =====================================================

elif page == "30 Service Categories":
    st.header("🗂️ Service-Wise Leads")

    leads = all_leads()
    tabs = st.tabs(list(SERVICES.keys()))

    for tab, (service, pitch) in zip(tabs, SERVICES.items()):
        with tab:
            st.write(pitch)

            if leads.empty:
                st.info("No leads available.")
            else:
                subset = leads[leads["service"] == service]

                st.metric("Leads", len(subset))

                if not subset.empty:
                    st.dataframe(
                        subset[[
                            "id", "business_name", "website",
                            "phone", "email", "status"
                        ]],
                        use_container_width=True,
                        hide_index=True
                    )


# =====================================================
# OUTREACH STUDIO
# =====================================================

elif page == "Outreach Studio":
    st.header("✉️ Personalized Outreach Studio")

    leads = all_leads()

    if leads.empty:
        st.warning("First add or discover leads.")
    else:
        choices = {
            f'{r["id"]} - {r["business_name"]}': r
            for _, r in leads.iterrows()
        }

        selected_label = st.selectbox(
            "Choose business",
            list(choices.keys())
        )

        lead = choices[selected_label]

        business = st.text_input(
            "Business name",
            value=str(lead["business_name"])
        )

        website = st.text_input(
            "Business website",
            value=str(lead["website"] or "")
        )

        email = st.text_input(
            "Business email",
            value=str(lead["email"] or "")
        )

        phone = st.text_input(
            "Phone with country code",
            value=str(lead["phone"] or "")
        )

        service = st.selectbox(
            "Select service",
            list(SERVICES.keys()),
            index=(
                list(SERVICES.keys()).index(lead["service"])
                if lead["service"] in SERVICES else 0
            )
        )

        subject, email_message = generate_email(
            business, service, website
        )

        whatsapp_message = generate_whatsapp(
            business, service, website
        )

        st.divider()
        st.subheader("Email Draft")

        st.text_input("Subject", value=subject)
        st.text_area(
            "Email message",
            value=email_message,
            height=300
        )

        mail = email_url(email, subject, email_message)

        if mail:
            st.link_button("Open Email Draft", mail)

        st.divider()
        st.subheader("WhatsApp Draft")

        st.text_area(
            "WhatsApp message",
            value=whatsapp_message,
            height=280
        )

        wa = whatsapp_url(phone, whatsapp_message)

        if wa:
            st.link_button("Open WhatsApp Chat", wa)

        st.caption(
            "Drafts only. Contact businesses where outreach is lawful; "
            "respect consent requirements and opt-out requests."
        )

        if st.button("Save Service and Contact Details"):
            con = db()
            con.execute("""
                UPDATE leads
                SET service=?, website=?, email=?, phone=?
                WHERE id=?
            """, (
                service,
                website,
                email,
                phone,
                int(lead["id"])
            ))
            con.commit()
            con.close()

            st.success("Lead details saved.")


# =====================================================
# ADD LEAD
# =====================================================

elif page == "Add Lead":
    st.header("➕ Add a Business")

    with st.form("add_form"):
        name = st.text_input("Business name")
        website = st.text_input("Website")
        phone = st.text_input("Phone")
        email = st.text_input("Email")
        address = st.text_input("Address")

        service = st.selectbox(
            "Harvantra service",
            list(SERVICES.keys())
        )

        notes = st.text_area("Notes")

        submit = st.form_submit_button("Save Business")

    if submit:
        if not name.strip():
            st.error("Business name required.")
        else:
            save_lead({
                "business_name": name,
                "website": website,
                "phone": phone,
                "email": email,
                "address": address,
                "service": service,
                "source": "Manual",
                "status": "New",
                "notes": notes
            })

            st.success("Business saved to CRM.")


# =====================================================
# IMPORT / EXPORT
# =====================================================

elif page == "Import / Export":
    st.header("📁 Import / Export Leads")

    st.write(
        "CSV must include business_name. Optional columns: "
        "website, phone, email, address, service, notes."
    )

    file = st.file_uploader("Upload CSV", type=["csv"])

    if file and st.button("Import CSV"):
        try:
            number = import_csv(file)
            st.success(f"{number} leads imported.")
        except Exception as error:
            st.error(str(error))

    st.divider()

    leads = all_leads()

    if not leads.empty:
        st.download_button(
            "Download CRM CSV",
            leads.to_csv(index=False).encode("utf-8"),
            file_name="harvantra_leads.csv",
            mime="text/csv"
        )


# =====================================================
# ABOUT & SETTINGS
# =====================================================

elif page == "About & Settings":
    st.header("⚙️ Harvantra AI Settings")

    st.write("**Company:** Harvantra Technologies")
    st.write(f"**Website:** {COMPANY}")
    st.write(f"**GitHub:** {GITHUB}")
    st.write(f"**Founder LinkedIn:** {LINKEDIN}")

    st.divider()

    st.subheader("Free API Information")

    st.write("Geocoding: OpenStreetMap Nominatim")
    st.write("Business data: OpenStreetMap Overpass API")
    st.write("API key: Not required")

    st.markdown(
        "Business data © [OpenStreetMap contributors]"
        "(https://www.openstreetmap.org/copyright), "
        "available under the [ODbL licence]"
        "(https://opendatacommons.org/licenses/odbl/)."
    )

    st.divider()

    st.subheader("Important")

    st.write("""
    - OSM business data is incomplete and may be outdated.
    - Verify every business, website and contact detail.
    - Do not repeatedly query public servers or run bulk scans.
    - Respect applicable marketing laws and opt-out requests.
    - This version creates drafts; it does not automatically send messages.
    - SQLite on temporary cloud storage is not a production backup.
    """)
