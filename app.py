
import streamlit as st
import requests
import pandas as pd
import sqlite3
import re
import time
from datetime import datetime
from urllib.parse import quote

# =========================================================
# HARVANTRA AI V3.0 - CONFIGURATION
# =========================================================

st.set_page_config(
    page_title="Harvantra AI",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

APP_NAME = "Harvantra AI"
DB_PATH = "harvantra_crm.db"

COMPANY_WEBSITE = "https://harvantratechnologies.github.io/"
GITHUB_PORTFOLIO = "https://github.com/harvantratechnologies"
FOUNDER_LINKEDIN = "https://www.linkedin.com/in/haris-hassan-65b0523a8/"

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

OVERPASS_SERVERS = [
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.nchc.org.tw/api/interpreter"
]

HEADERS = {
    "User-Agent": (
        "HarvantraAI/3.0 "
        "(https://harvantratechnologies.github.io/)"
    )
}

# =========================================================
# OFFICIAL 30 HARVANTRA SERVICES
# =========================================================

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
        "We can support incident investigation, evidence preservation and digital forensics readiness.",

    "Threat Hunting & Detection Engineering":
        "We can improve threat detection through security log analysis, threat hunting and detection rule development.",

    "Endpoint Detection & Response (EDR)":
        "We can review endpoint security coverage, suspicious activity visibility and incident containment readiness.",

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
        "We can review your security architecture, identify major risks and develop a practical security improvement roadmap.",

    "Security Compliance & GRC":
        "We can support security control reviews, risk documentation and governance and compliance improvement activities.",

    "Security Awareness & Phishing Simulation":
        "We can improve employee security awareness through training and authorized phishing simulation exercises.",

    "Threat Intelligence & Dark-Web Monitoring":
        "We can improve threat awareness through relevant threat intelligence and monitoring of exposed organizational information.",

    "Ransomware Protection & Backup Security":
        "We can review backup security, ransomware readiness and recovery procedures to improve business resilience.",

    "Cloud Migration & Infrastructure Management":
        "We can support secure cloud migration planning and infrastructure management.",

    "Server Management & Hardening":
        "We can review server configurations, unnecessary services and access controls to recommend security hardening.",

    "Network Design, VPN & Secure Remote Access":
        "We can help plan secure network connectivity, VPN configuration and remote access controls.",

    "DevSecOps & CI/CD Security":
        "We can help integrate security checks into development workflows and CI/CD pipelines.",

    "Docker & Container Security":
        "We can review container configurations, image security and runtime permissions.",

    "Website Security & Maintenance":
        "We can review website security, identify common weaknesses and recommend maintenance and hardening improvements.",

    "Database Security & Management":
        "We can review database access, permissions, configuration and backup security practices.",

    "Backup & Disaster Recovery":
        "We can assess backup practices and disaster recovery readiness to improve operational resilience.",

    "IT Infrastructure Monitoring":
        "We can improve infrastructure visibility through monitoring of system health, availability and operational issues.",

    "Managed IT Support & Helpdesk":
        "We can provide managed IT support and helpdesk assistance for routine technical and infrastructure requirements."
}

STATUSES = [
    "New",
    "Qualified",
    "Contacted",
    "Replied",
    "Meeting",
    "Proposal",
    "Client",
    "Not Interested",
    "Do Not Contact"
]

# =========================================================
# DATABASE
# =========================================================

def get_db():
    return sqlite3.connect(
        DB_PATH,
        check_same_thread=False
    )


def initialize_database():
    con = get_db()

    con.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_name TEXT NOT NULL,
            website TEXT,
            phone TEXT,
            email TEXT,
            address TEXT,
            service TEXT,
            source TEXT,
            status TEXT DEFAULT 'New',
            notes TEXT,
            consent_basis TEXT DEFAULT '',
            created_at TEXT,
            updated_at TEXT
        )
    """)

    columns = {
        row[1]
        for row in con.execute(
            "PRAGMA table_info(leads)"
        ).fetchall()
    }

    if "consent_basis" not in columns:
        con.execute(
            "ALTER TABLE leads ADD COLUMN consent_basis TEXT DEFAULT ''"
        )

    if "updated_at" not in columns:
        con.execute(
            "ALTER TABLE leads ADD COLUMN updated_at TEXT"
        )

    con.commit()
    con.close()


def get_leads():
    con = get_db()

    df = pd.read_sql_query(
        "SELECT * FROM leads ORDER BY id DESC",
        con
    )

    con.close()
    return df


def add_lead(data):
    now = datetime.now().isoformat(timespec="seconds")

    con = get_db()

    con.execute("""
        INSERT INTO leads (
            business_name, website, phone, email,
            address, service, source, status, notes,
            consent_basis, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        data.get("business_name", ""),
        data.get("website", ""),
        data.get("phone", ""),
        data.get("email", ""),
        data.get("address", ""),
        data.get("service", list(SERVICES.keys())[0]),
        data.get("source", ""),
        data.get("status", "New"),
        data.get("notes", ""),
        data.get("consent_basis", ""),
        now,
        now
    ))

    con.commit()
    con.close()


def update_lead(lead_id, **fields):
    allowed = {
        "business_name", "website", "phone", "email",
        "address", "service", "source", "status",
        "notes", "consent_basis"
    }

    updates = {
        key: value
        for key, value in fields.items()
        if key in allowed
    }

    if not updates:
        return

    updates["updated_at"] = datetime.now().isoformat(
        timespec="seconds"
    )

    clause = ", ".join(
        f"{key}=?" for key in updates
    )

    con = get_db()

    con.execute(
        f"UPDATE leads SET {clause} WHERE id=?",
        list(updates.values()) + [int(lead_id)]
    )

    con.commit()
    con.close()


def delete_lead(lead_id):
    con = get_db()

    con.execute(
        "DELETE FROM leads WHERE id=?",
        (int(lead_id),)
    )

    con.commit()
    con.close()


def save_discovered_leads(records):
    existing = get_leads()

    existing_keys = set()

    if not existing.empty:
        for _, row in existing.iterrows():
            existing_keys.add((
                str(row["business_name"]).strip().lower(),
                str(row["website"]).strip().lower()
            ))

    saved = 0
    duplicates = 0

    for record in records:
        key = (
            record["business_name"].strip().lower(),
            record["website"].strip().lower()
        )

        if key in existing_keys:
            duplicates += 1
            continue

        add_lead(record)
        existing_keys.add(key)
        saved += 1

    return saved, duplicates


# =========================================================
# LOCATION SEARCH - NOMINATIM
# =========================================================

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
        timeout=(10, 30)
    )

    response.raise_for_status()

    results = response.json()

    if not results:
        raise ValueError(
            "Location not found. City and country check karein."
        )

    return {
        "lat": float(results[0]["lat"]),
        "lon": float(results[0]["lon"]),
        "display_name": results[0]["display_name"]
    }


# =========================================================
# OVERPASS MULTI-SERVER API FALLBACK
# =========================================================

def query_overpass(query):

    errors = []

    for server in OVERPASS_SERVERS:

        try:
            response = requests.post(
                server,
                data={"data": query},
                headers=HEADERS,
                timeout=(15, 90)
            )

            response.raise_for_status()

            result = response.json()

            if "elements" not in result:
                raise ValueError(
                    "Invalid response from Overpass server."
                )

            return result

        except (
            requests.exceptions.RequestException,
            ValueError
        ) as error:

            errors.append(
                f"{server}: {str(error)}"
            )

            continue

    raise RuntimeError(
        "All Overpass servers failed. "
        "Please wait and try again later.\n\n"
        + "\n".join(errors)
    )


# =========================================================
# BUSINESS DISCOVERY
# =========================================================

def discover_businesses(location, radius_km, limit):

    place = geocode_location(location)

    lat = place["lat"]
    lon = place["lon"]

    radius = int(radius_km * 1000)

    query = f"""
    [out:json][timeout:60];
    (
      nwr(around:{radius},{lat},{lon})[name][website];
      nwr(around:{radius},{lat},{lon})[name]["contact:website"];
    );
    out center tags;
    """

    elements = query_overpass(query).get(
        "elements", []
    )

    records = []
    seen = set()

    categories = [
        "shop",
        "office",
        "amenity",
        "craft",
        "tourism",
        "healthcare",
        "industrial",
        "leisure",
        "club"
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

        if not any(category in tags for category in categories):
            continue

        if website.startswith("www."):
            website = "https://" + website

        elif not website.startswith(("http://", "https://")):
            website = "https://" + website

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

        address_parts = [
            tags.get("addr:housenumber", ""),
            tags.get("addr:street", ""),
            tags.get("addr:city", ""),
            tags.get("addr:state", ""),
            tags.get("addr:country", "")
        ]

        address = ", ".join(
            part for part in address_parts if part
        )

        if not address:
            address = place["display_name"]

        category = next(
            (c for c in categories if c in tags),
            "business"
        )

        records.append({
            "business_name": name,
            "website": website,
            "phone": phone,
            "email": email,
            "address": address,
            "service": list(SERVICES.keys())[0],
            "source": "OpenStreetMap",
            "status": "New",
            "notes": (
                f"OSM category: {category}. "
                "Verify information before contacting."
            ),
            "consent_basis": ""
        })

        if len(records) >= limit:
            break

    return records


# =========================================================
# OUTREACH GENERATOR
# =========================================================

def generate_email(business_name, service, website=""):

    pitch = SERVICES[service]

    subject = (
        f"IT & Cybersecurity Support for {business_name}"
    )

    message = f"""Hello {business_name} Team,

I hope you are doing well.

I am reaching out from Harvantra Technologies, a Pakistan-based IT and cybersecurity services company.

We provide {service}.

How this may help your organization:

{pitch}

We would welcome an opportunity to understand your requirements and discuss whether our services could be relevant.

Company Website:
{COMPANY_WEBSITE}

GitHub Portfolio:
{GITHUB_PORTFOLIO}

Founder LinkedIn:
{FOUNDER_LINKEDIN}

"""

    if website:
        message += f"Your Business Website:\n{website}\n\n"

    message += """If this is relevant to your team, please let us know a suitable time for a brief discussion.

If you do not wish to receive further messages, please let us know.

Regards,
Harvantra Technologies
"""

    return subject, message


def generate_whatsapp(business_name, service, website=""):

    pitch = SERVICES[service]

    message = f"""Hello {business_name} Team,

I am reaching out from Harvantra Technologies.

We provide {service}.

{pitch}

Company Website:
{COMPANY_WEBSITE}

GitHub Portfolio:
{GITHUB_PORTFOLIO}

Founder LinkedIn:
{FOUNDER_LINKEDIN}

"""

    if website:
        message += f"Your Business Website:\n{website}\n\n"

    message += """Would your team be open to a brief discussion?

If you do not wish to receive further messages, please let us know.
"""

    return message


def create_whatsapp_link(phone, message):

    number = re.sub(r"[^0-9]", "", str(phone))

    if not number:
        return ""

    return (
        "https://wa.me/"
        + number
        + "?text="
        + quote(message)
    )


def create_email_link(email, subject, message):

    if not email or "@" not in email:
        return ""

    return (
        f"mailto:{email}"
        f"?subject={quote(subject)}"
        f"&body={quote(message)}"
    )


# =========================================================
# CSV IMPORT
# =========================================================

def import_csv(uploaded_file):

    df = pd.read_csv(uploaded_file)

    df.columns = [
        str(column).strip().lower()
        for column in df.columns
    ]

    if "business_name" not in df.columns:
        raise ValueError(
            "CSV mein business_name column required hai."
        )

    imported = 0

    for _, row in df.iterrows():

        name = str(row.get("business_name", "")).strip()

        if not name or name.lower() == "nan":
            continue

        service = str(row.get("service", "")).strip()

        if service not in SERVICES:
            service = list(SERVICES.keys())[0]

        def clean(value):
            if pd.isna(value):
                return ""
            return str(value).strip()

        add_lead({
            "business_name": name,
            "website": clean(row.get("website", "")),
            "phone": clean(row.get("phone", "")),
            "email": clean(row.get("email", "")),
            "address": clean(row.get("address", "")),
            "service": service,
            "source": "CSV Import",
            "status": "New",
            "notes": clean(row.get("notes", "")),
            "consent_basis": clean(row.get("consent_basis", ""))
        })

        imported += 1

    return imported


# =========================================================
# INITIALIZE
# =========================================================

initialize_database()

# =========================================================
# SIDEBAR
# =========================================================

st.sidebar.title("🛡️ Harvantra AI")
st.sidebar.caption("Client Acquisition Platform")

page = st.sidebar.radio(
    "Main Menu",
    [
        "Dashboard",
        "Business Discovery",
        "All Leads CRM",
        "30 Service Categories",
        "Outreach Studio",
        "Add Lead",
        "Import / Export",
        "Company & Settings"
    ]
)

st.sidebar.divider()

st.sidebar.caption("Harvantra Technologies")

st.sidebar.markdown(
    f"[Company Website]({COMPANY_WEBSITE})"
)

st.sidebar.markdown(
    f"[GitHub Portfolio]({GITHUB_PORTFOLIO})"
)

st.sidebar.markdown(
    f"[Founder LinkedIn]({FOUNDER_LINKEDIN})"
)

# =========================================================
# DASHBOARD
# =========================================================

if page == "Dashboard":

    st.title("📊 Harvantra AI Dashboard")

    leads = get_leads()
    total = len(leads)

    def get_count(status):
        if total == 0:
            return 0
        return int((leads["status"] == status).sum())

    col1, col2, col3, col4, col5 = st.columns(5)

    col1.metric("Total Leads", total)
    col2.metric("New", get_count("New"))
    col3.metric("Contacted", get_count("Contacted"))
    col4.metric("Replied", get_count("Replied"))
    col5.metric("Clients", get_count("Client"))

    st.divider()

    st.subheader("Recent Business Leads")

    if leads.empty:
        st.info("No leads found. Start Business Discovery.")

    else:
        st.dataframe(
            leads.head(15),
            use_container_width=True,
            hide_index=True
        )

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("Lead Status Analytics")
            st.bar_chart(leads["status"].value_counts())

        with col2:
            st.subheader("Service Distribution")
            st.bar_chart(leads["service"].value_counts())

    st.divider()

    st.metric("Available Harvantra Services", len(SERVICES))


# =========================================================
# BUSINESS DISCOVERY
# =========================================================

elif page == "Business Discovery":

    st.title("🌍 Business Discovery")

    st.info(
        "Searches public OpenStreetMap data. "
        "Only businesses with website information recorded in OSM "
        "can be discovered. Results are not exhaustive."
    )

    with st.form("business_search_form"):

        location = st.text_input(
            "Location",
            placeholder="Islamabad, Pakistan"
        )

        radius = st.slider(
            "Search radius (km)",
            1, 5, 3
        )

        result_limit = st.slider(
            "Maximum results",
            5, 50, 15
        )

        service = st.selectbox(
            "Assign Harvantra service",
            list(SERVICES.keys())
        )

        submitted = st.form_submit_button(
            "🔎 Search Businesses"
        )

    if submitted:

        if not location.strip():
            st.error("Please enter a location.")

        else:

            try:

                with st.spinner(
                    "Searching available OpenStreetMap servers..."
                ):

                    found = discover_businesses(
                        location,
                        radius,
                        result_limit
                    )

                for record in found:
                    record["service"] = service

                st.session_state["discovered_leads"] = found

                st.success(
                    f"{len(found)} businesses discovered."
                )

                if not found:
                    st.warning(
                        "No matching businesses found. "
                        "OSM data may be incomplete. "
                        "Try another location or radius."
                    )

            except requests.exceptions.RequestException as error:

                st.error(f"Network/API error: {error}")

            except Exception as error:

                st.error(f"Search error: {error}")

    found = st.session_state.get(
        "discovered_leads", []
    )

    if found:

        st.subheader("Review Discovered Businesses")

        st.dataframe(
            pd.DataFrame(found),
            use_container_width=True,
            hide_index=True
        )

        st.caption(
            "Verify business information before saving or contacting."
        )

        if st.button("💾 Save Reviewed Leads"):

            saved, duplicates = save_discovered_leads(found)

            st.success(
                f"{saved} new leads saved. "
                f"{duplicates} duplicates skipped."
            )


# =========================================================
# ALL LEADS CRM
# =========================================================

elif page == "All Leads CRM":

    st.title("📋 All Leads CRM")

    leads = get_leads()

    if leads.empty:

        st.info("CRM is currently empty.")

    else:

        search = st.text_input(
            "Search business name or website"
        )

        status_filter = st.selectbox(
            "Filter by status",
            ["All"] + STATUSES
        )

        filtered = leads.copy()

        if search:

            filtered = filtered[
                filtered["business_name"].str.contains(
                    search,
                    case=False,
                    na=False
                )
                |
                filtered["website"].str.contains(
                    search,
                    case=False,
                    na=False
                )
            ]

        if status_filter != "All":

            filtered = filtered[
                filtered["status"] == status_filter
            ]

        st.dataframe(
            filtered,
            use_container_width=True,
            hide_index=True
        )

        st.divider()
        st.subheader("Manage Lead")

        if not filtered.empty:

            selected_id = st.selectbox(
                "Select Lead ID",
                filtered["id"].tolist()
            )

            selected = filtered[
                filtered["id"] == selected_id
            ].iloc[0]

            current_status = (
                selected["status"]
                if selected["status"] in STATUSES
                else "New"
            )

            with st.form("lead_update_form"):

                status = st.selectbox(
                    "Lead status",
                    STATUSES,
                    index=STATUSES.index(current_status)
                )

                email = st.text_input(
                    "Email",
                    value=str(selected["email"] or "")
                )

                phone = st.text_input(
                    "Phone",
                    value=str(selected["phone"] or "")
                )

                notes = st.text_area(
                    "Notes",
                    value=str(selected["notes"] or "")
                )

                consent = st.text_input(
                    "Contact permission / lawful basis notes",
                    value=str(selected["consent_basis"] or "")
                )

                save = st.form_submit_button("Update Lead")

            if save:

                update_lead(
                    selected_id,
                    status=status,
                    email=email,
                    phone=phone,
                    notes=notes,
                    consent_basis=consent
                )

                st.success("Lead updated.")
                st.rerun()

            if st.button("Delete Selected Lead"):

                delete_lead(selected_id)

                st.success("Lead deleted.")
                st.rerun()


# =========================================================
# 30 SERVICE CATEGORIES
# =========================================================

elif page == "30 Service Categories":

    st.title("🗂️ 30 Service Categories")

    leads = get_leads()

    tabs = st.tabs(list(SERVICES.keys()))

    for tab, (service, pitch) in zip(tabs, SERVICES.items()):

        with tab:

            st.subheader(service)
            st.write(pitch)

            if leads.empty:

                st.info("No leads available.")

            else:

                service_leads = leads[
                    leads["service"] == service
                ]

                st.metric(
                    "Total Leads",
                    len(service_leads)
                )

                if not service_leads.empty:

                    st.dataframe(
                        service_leads[
                            [
                                "id",
                                "business_name",
                                "website",
                                "phone",
                                "email",
                                "status"
                            ]
                        ],
                        use_container_width=True,
                        hide_index=True
                    )


# =========================================================
# OUTREACH STUDIO
# =========================================================

elif page == "Outreach Studio":

    st.title("✉️ Personalized Outreach Studio")

    leads = get_leads()

    if leads.empty:

        st.warning("Add or discover business leads first.")

    else:

        options = {
            f'{row["id"]} - {row["business_name"]}': row
            for _, row in leads.iterrows()
        }

        selected_label = st.selectbox(
            "Select Business",
            list(options.keys())
        )

        lead = options[selected_label]

        business_name = st.text_input(
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
            "Relevant Harvantra Service",
            list(SERVICES.keys()),
            index=(
                list(SERVICES.keys()).index(lead["service"])
                if lead["service"] in SERVICES
                else 0
            )
        )

        subject, email_message = generate_email(
            business_name,
            service,
            website
        )

        whatsapp_message = generate_whatsapp(
            business_name,
            service,
            website
        )

        st.divider()

        st.subheader("Email Message")

        edited_subject = st.text_input(
            "Email Subject",
            value=subject
        )

        edited_email = st.text_area(
            "Personalized Email Draft",
            value=email_message,
            height=330
        )

        email_link = create_email_link(
            email,
            edited_subject,
            edited_email
        )

        if email_link:

            st.link_button(
                "Open Email Draft",
                email_link
            )

        else:

            st.caption("Add a valid business email.")

        st.divider()

        st.subheader("WhatsApp Message")

        edited_whatsapp = st.text_area(
            "Personalized WhatsApp Draft",
            value=whatsapp_message,
            height=300
        )

        whatsapp_link = create_whatsapp_link(
            phone,
            edited_whatsapp
        )

        if whatsapp_link:

            st.link_button(
                "Open WhatsApp Chat",
                whatsapp_link
            )

        else:

            st.caption(
                "Add a phone number with country code."
            )

        st.info(
            "These are drafts, not automatic messages. "
            "Use lawful contact methods, follow WhatsApp policies "
            "and respect opt-out requests."
        )

        if st.button("Save Service and Contact Details"):

            update_lead(
                lead["id"],
                service=service,
                website=website,
                email=email,
                phone=phone
            )

            st.success("Business details saved.")
            st.rerun()


# =========================================================
# ADD LEAD
# =========================================================

elif page == "Add Lead":

    st.title("➕ Add New Business")

    with st.form("manual_lead_form"):

        business_name = st.text_input("Business Name")
        website = st.text_input("Website")
        phone = st.text_input("Phone with country code")
        email = st.text_input("Email")
        address = st.text_input("Address")

        service = st.selectbox(
            "Harvantra Service",
            list(SERVICES.keys())
        )

        source = st.selectbox(
            "Source",
            [
                "Manual Research",
                "OpenStreetMap",
                "Referral",
                "LinkedIn",
                "Website",
                "CSV Import",
                "Other"
            ]
        )

        notes = st.text_area("Notes")

        consent_basis = st.text_input(
            "Contact permission / lawful basis notes"
        )

        submit = st.form_submit_button("Save Business")

    if submit:

        if not business_name.strip():

            st.error("Business name is required.")

        else:

            add_lead({
                "business_name": business_name.strip(),
                "website": website,
                "phone": phone,
                "email": email,
                "address": address,
                "service": service,
                "source": source,
                "status": "New",
                "notes": notes,
                "consent_basis": consent_basis
            })

            st.success("Business successfully saved to CRM.")


# =========================================================
# IMPORT / EXPORT
# =========================================================

elif page == "Import / Export":

    st.title("📁 Import and Export Leads")

    st.subheader("Import CSV")

    st.write("""
    Required column:
    - business_name

    Optional columns:
    - website
    - phone
    - email
    - address
    - service
    - notes
    - consent_basis
    """)

    uploaded_file = st.file_uploader(
        "Upload CSV",
        type=["csv"]
    )

    if uploaded_file:

        if st.button("Import Leads"):

            try:

                imported = import_csv(uploaded_file)

                st.success(
                    f"{imported} leads imported."
                )

            except Exception as error:

                st.error(str(error))

    st.divider()

    st.subheader("Export CRM")

    leads = get_leads()

    if not leads.empty:

        csv_data = leads.to_csv(
            index=False
        ).encode("utf-8")

        st.download_button(
            "⬇️ Download All Leads",
            data=csv_data,
            file_name="harvantra_leads.csv",
            mime="text/csv"
        )

    else:

        st.info("No leads available for export.")


# =========================================================
# COMPANY & SETTINGS
# =========================================================

elif page == "Company & Settings":

    st.title("⚙️ Company & Settings")

    st.subheader("Harvantra Technologies")

    st.write(f"Company Website: {COMPANY_WEBSITE}")
    st.write(f"GitHub Portfolio: {GITHUB_PORTFOLIO}")
    st.write(f"Founder LinkedIn: {FOUNDER_LINKEDIN}")

    st.divider()

    st.subheader("API Information")

    st.success(
        "No API key required for the included public OSM services."
    )

    st.write("Geocoding: OpenStreetMap Nominatim")
    st.write("Business discovery: Multiple Overpass API servers")

    st.markdown(
        "Data © [OpenStreetMap contributors]"
        "(https://www.openstreetmap.org/copyright), "
        "licensed under [ODbL]"
        "(https://opendatacommons.org/licenses/odbl/)."
    )

    st.divider()

    st.subheader("Important Usage Rules")

    st.write("""
    1. OpenStreetMap data may be incomplete or outdated.
    2. Verify businesses and contact information.
    3. Do not run repeated or excessive public API requests.
    4. Respect Nominatim and Overpass usage policies.
    5. Respect marketing laws and opt-out requests.
    6. Do not send unsolicited WhatsApp bulk messages.
    7. This application creates outreach drafts only.
    8. Back up the CRM database regularly.
    9. Public cloud hosting may not preserve local SQLite files.
    """)

    st.divider()

    st.subheader("System Information")

    st.write("Application Version: 3.0")
    st.write("Total Services:", len(SERVICES))
    st.write("Database: SQLite")
    st.write("Business Data: OpenStreetMap")


# =========================================================
# FOOTER
# =========================================================

st.sidebar.divider()
st.sidebar.caption("Harvantra AI | Version 3.0")
st.sidebar.caption("Powered by Harvantra Technologies")
