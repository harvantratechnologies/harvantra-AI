from sqlalchemy.orm import Session
from app.models import ServiceCatalog

HARVANTRA_30_SERVICES = [
    (1, "Managed SOC & 24/7 Monitoring", "SOC & Threat Operations", "Continuous security monitoring, alert triage, and incident escalation.", "Organizations needing round-the-clock threat visibility without building an internal SOC."),
    (2, "SIEM Deployment & Management", "SOC & Threat Operations", "Log collection, correlation rules, dashboards, and SIEM tuning.", "Businesses with servers, cloud workloads, or compliance needs requiring centralized log analysis."),
    (3, "Vulnerability Assessment & Management", "Offensive & Vulnerability Management", "Systematic discovery, prioritization, and remediation tracking of system vulnerabilities.", "Companies seeking regular visibility into software and infrastructure weaknesses."),
    (4, "Penetration Testing (VAPT)", "Offensive & Vulnerability Management", "Simulated authorized attacks to evaluate real-world exploitable risk.", "Organizations preparing for audits, client security reviews, or major releases."),
    (5, "Incident Response & Digital Forensics", "Incident & Forensic Response", "Rapid containment, root-cause investigation, evidence preservation, and recovery.", "Businesses experiencing suspected intrusions, data leaks, or suspicious system activity."),
    (6, "Threat Hunting & Detection Engineering", "SOC & Threat Operations", "Proactive hypothesis-driven threat searches and custom detection rules.", "Teams looking to catch stealthy adversaries before alerts trigger."),
    (7, "Endpoint Detection & Response", "Endpoint & Network Security", "Behavioral monitoring and automated containment on laptops, desktops, and servers.", "Organizations with remote or hybrid staff using endpoints across networks."),
    (8, "Network Security Assessment & Hardening", "Endpoint & Network Security", "Segmentation review, firewall/router auditing, and protocol hardening.", "Businesses with office networks, branch offices, or on-premise infrastructure."),
    (9, "Firewall Security & Management", "Endpoint & Network Security", "Rule cleanup, policy enforcement, IPS/IDS tuning, and ongoing firewall administration.", "Companies managing perimeter or internal firewalls with growing rule complexity."),
    (10, "AWS & Azure Cloud Security", "Cloud & Identity Security", "Securing cloud accounts, storage, compute, networking, and IAM configurations.", "Businesses running workloads or hosting applications on AWS or Microsoft Azure."),
    (11, "Cloud Security Posture Management", "Cloud & Identity Security", "Continuous configuration auditing and misconfiguration remediation across cloud assets.", "Teams scaling cloud infrastructure and preventing exposed buckets or open ports."),
    (12, "Identity & Access Management", "Cloud & Identity Security", "Role-based access control, least privilege, MFA enforcement, and access reviews.", "Organizations managing employee accounts across cloud apps, email, and internal systems."),
    (13, "Zero Trust Security", "Cloud & Identity Security", "Continuous verification, micro-segmentation, and least-privilege access architecture.", "Modernized or distributed organizations reducing implicit trust inside networks."),
    (14, "Web & API Security Testing", "Application Security", "Security testing of web portals, customer dashboards, and backend APIs.", "Companies operating customer-facing websites, portals, or third-party APIs."),
    (15, "Mobile Application Security Testing", "Application Security", "Static and dynamic security review of Android and iOS applications.", "Businesses offering mobile apps that handle user data, logins, or payments."),
    (16, "Security Architecture & Risk Assessment", "Governance, Risk & Compliance", "Evaluating system architecture, data flows, and business risk exposure.", "Growing enterprises planning new systems, expansions, or vendor onboarding."),
    (17, "Security Compliance & GRC", "Governance, Risk & Compliance", "Policy alignment, control mapping, risk registers, and audit readiness support.", "Businesses needing structured governance, risk management, or regulatory alignment."),
    (18, "Security Awareness & Phishing Simulation", "Governance, Risk & Compliance", "Staff training programs and controlled phishing simulations to reduce human risk.", "Organizations with teams handling emails, financial workflows, or sensitive data."),
    (19, "Threat Intelligence & Dark-Web Monitoring", "Threat Intelligence & Resilience", "Tracking external threat indicators, leaked credentials, and brand/domain mentions.", "Businesses concerned about credential exposure, impersonation, or targeted threats."),
    (20, "Ransomware Protection & Backup Security", "Threat Intelligence & Resilience", "Anti-ransomware controls, immutable backups, and recovery readiness checks.", "Organizations that cannot afford operational downtime or encrypted business data."),
    (21, "Cloud Migration & Infrastructure Management", "Infrastructure & Cloud Operations", "Structured migration of workloads and ongoing cloud infrastructure administration.", "Businesses moving from local servers or legacy setups to cloud environments."),
    (22, "Server Management & Hardening", "Infrastructure & Cloud Operations", "Linux/Windows server patching, configuration hardening, performance care, and uptime support.", "Companies running dedicated, VPS, or on-premise servers."),
    (23, "Network Design, VPN & Secure Remote Access", "Endpoint & Network Security", "Reliable LAN/WAN design, site-to-site/client VPNs, and encrypted remote access.", "Businesses supporting remote workers, branches, or external contractors."),
    (24, "DevSecOps & CI/CD Security", "Application Security", "Integrating code checks, secret scanning, and pipeline security into software delivery.", "Software teams building and deploying applications continuously."),
    (25, "Docker & Container Security", "Application Security", "Hardening container images, registries, and runtime environments.", "Teams deploying microservices or apps using Docker or containers."),
    (26, "Website Security & Maintenance", "Web & Database Operations", "Malware cleanup, HTTPS/TLS health, CMS/plugin patching, and ongoing website upkeep.", "Businesses relying on websites for visibility, leads, or online operations."),
    (27, "Database Security & Management", "Web & Database Operations", "Database administration, access controls, backup verification, tuning, and hardening.", "Organizations storing critical business or customer records in databases."),
    (28, "Backup & Disaster Recovery", "Threat Intelligence & Resilience", "Automated backup scheduling, restore testing, and business continuity planning.", "Companies needing reliable recovery plans after hardware failure or accidental deletion."),
    (29, "IT Infrastructure Monitoring", "Infrastructure & Cloud Operations", "Proactive uptime, CPU/memory/disk, and service health monitoring.", "Businesses wanting early alerts before IT slowdowns impact operations."),
    (30, "Managed IT Support & Helpdesk", "Infrastructure & Cloud Operations", "Tiered technical troubleshooting, user support, and day-to-day IT assistance.", "Small and growing businesses needing dependable ongoing IT support."),
]


def seed_services(db: Session) -> None:
    for number, name, category, summary, ideal_profile in HARVANTRA_30_SERVICES:
        existing = db.query(ServiceCatalog).filter(ServiceCatalog.number == number).first()
        if not existing:
            db.add(
                ServiceCatalog(
                    number=number,
                    name=name,
                    category=category,
                    summary=summary,
                    ideal_client_profile=ideal_profile,
                    is_active=True,
                )
            )
    db.commit()
