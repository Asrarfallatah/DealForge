# backend/tools/reporting_tools.py

from io import BytesIO
from typing import Dict, Any
from langsmith import traceable

from sqlalchemy import func
from sqlalchemy.orm import Session

from db.models import Company, Contact, Lead, Deal, Task

# ============================================================
# DASHBOARD / REPORTING
# ============================================================


@traceable(name="normalize_status", run_type="tool")
def normalize_status(value):
    """
    Normalize status values for case-insensitive counting.
    """
    return value.strip().lower() if value else value


# ============================================================
# LEAD PIPELINE
# ============================================================


@traceable(name="get_lead_pipeline", run_type="tool")
def get_lead_pipeline(db: Session) -> Dict[str, Any]:
    """
    Old-compatible lead pipeline output.

    Expected output:
    {
        "success": True,
        "pipeline": {...},
        "total_leads": 500
    }
    """
    rows = (
        db.query(func.lower(Lead.status), func.count(Lead.lead_id))
        .group_by(func.lower(Lead.status))
        .all()
    )

    raw = {status: count for status, count in rows}

    normalized = {
        "New": raw.get("new", 0),
        "Contacted": raw.get("contacted", 0),
        "Responded": raw.get("responded", 0),
        "Qualified": raw.get("qualified", 0),
        "Proposal Sent": raw.get("proposal sent", 0),
        "Stalled": raw.get("stalled", 0),
        "Won": raw.get("won", 0),
        "Lost": raw.get("lost", 0),
    }

    return {
        "success": True,
        "pipeline": normalized,
        "total_leads": sum(normalized.values()),
    }


# ============================================================
# DEAL PIPELINE
# ============================================================


@traceable(name="get_deal_pipeline", run_type="tool")
def get_deal_pipeline(db: Session) -> Dict[str, int]:
    """
    Old-compatible deal pipeline output.

    Expected output:
    {
        "Prospecting": 0,
        "Discovery": 0,
        ...
    }
    """
    rows = (
        db.query(Deal.deal_stage, func.count(Deal.deal_id))
        .group_by(Deal.deal_stage)
        .all()
    )

    raw = {stage: count for stage, count in rows}

    return {
        "Prospecting": raw.get("Prospecting", 0),
        "Discovery": raw.get("Discovery", 0),
        "Qualified": raw.get("Qualified", 0),
        "Proposal": raw.get("Proposal", 0),
        "Negotiation": raw.get("Negotiation", 0),
        "Closed Won": raw.get("Closed Won", 0),
        "Closed Lost": raw.get("Closed Lost", 0),
    }


# ============================================================
# COMBINED PIPELINE
# ============================================================


@traceable(name="get_pipeline", run_type="tool")
def get_pipeline(db: Session) -> Dict[str, Any]:
    """
    Old-compatible combined pipeline output.
    """
    return {
        "success": True,
        "lead_pipeline": get_lead_pipeline(db)["pipeline"],
        "deal_pipeline": get_deal_pipeline(db),
    }


# ============================================================
# CURRENT PROJECT COMPATIBILITY NAMES
# ============================================================


@traceable(name="generate_pipeline_report", run_type="tool")
def generate_pipeline_report(db: Session) -> Dict[str, Any]:
    """
    Current project function name.
    Keeps compatibility with graph/report nodes that expect pipeline_by_status.
    """
    lead_pipeline = get_lead_pipeline(db)

    return {
        "success": True,
        "total_leads": lead_pipeline["total_leads"],
        "pipeline_by_status": lead_pipeline["pipeline"],
    }


@traceable(name="get_deals_pipeline", run_type="tool")
def get_deals_pipeline(db: Session) -> Dict[str, Any]:
    """
    Current project function name.
    Keeps compatibility with graph/report nodes that expect pipeline_by_deal_stage.
    """
    return {
        "success": True,
        "pipeline_by_deal_stage": get_deal_pipeline(db),
    }


# ============================================================
# SIMPLE REPORTS
# ============================================================


@traceable(name="pipeline_report", run_type="tool")
def pipeline_report(db: Session) -> Dict[str, Any]:
    """
    Old-compatible simple pipeline report.

    Expected output:
    {
        "pipeline": {"new": 10, "qualified": 20, ...}
    }
    """
    rows = (
        db.query(func.lower(Lead.status), func.count(Lead.lead_id))
        .group_by(func.lower(Lead.status))
        .all()
    )

    return {"pipeline": {status or "unknown": count for status, count in rows}}


@traceable(name="top_lead_sources", run_type="tool")
def top_lead_sources(db: Session) -> Dict[str, int]:
    """
    Old-compatible lead sources output.

    Expected output:
    {
        "Website": 10,
        "Cold Calling": 20,
        "Unknown": 3
    }
    """
    rows = (
        db.query(Lead.lead_source, func.count(Lead.lead_id))
        .group_by(Lead.lead_source)
        .all()
    )

    return {source or "Unknown": count for source, count in rows}


@traceable(name="lead_sources_report", run_type="tool")
def lead_sources_report(db: Session) -> Dict[str, int]:
    """
    Compatibility wrapper for lead sources.
    """
    return top_lead_sources(db)


@traceable(name="conversion_report ", run_type="tool")
def conversion_report(db: Session) -> Dict[str, Any]:
    """
    Old-compatible conversion report output.
    """
    total_leads = db.query(func.count(Lead.lead_id)).scalar() or 0

    won_leads = (
        db.query(func.count(Lead.lead_id)).filter(Lead.status.ilike("won")).scalar()
        or 0
    )

    lost_leads = (
        db.query(func.count(Lead.lead_id)).filter(Lead.status.ilike("lost")).scalar()
        or 0
    )

    qualified_leads = (
        db.query(func.count(Lead.lead_id))
        .filter(Lead.status.ilike("qualified"))
        .scalar()
        or 0
    )

    conversion_rate = round((won_leads / total_leads) * 100, 2) if total_leads else 0

    return {
        "total_leads": total_leads,
        "qualified_leads": qualified_leads,
        "won_leads": won_leads,
        "lost_leads": lost_leads,
        "conversion_rate_percent": conversion_rate,
    }


@traceable(name="deal_pipeline_report", run_type="tool")
def deal_pipeline_report(db: Session) -> Dict[str, Any]:
    """
    Compatibility wrapper for deal pipeline.
    """
    return get_deals_pipeline(db)


# ============================================================
# DASHBOARD
# ============================================================


@traceable(name="generate_dashboard", run_type="tool")
def generate_dashboard(db: Session) -> Dict[str, Any]:
    """
    Old-compatible dashboard output for Advanced ReportingAgent.

    Expected output:
    {
        "success": True,
        "report_type": "dashboard",
        "data": {
            "kpis": {...},
            "pipelines": {...},
            "conversion": {...},
            "lead_sources": {...}
        }
    }
    """
    # =====================
    # KPIs
    # =====================
    total_leads = db.query(func.count(Lead.lead_id)).scalar() or 0
    total_companies = db.query(func.count(Company.company_id)).scalar() or 0
    total_contacts = db.query(func.count(Contact.contact_id)).scalar() or 0
    total_deals = db.query(func.count(Deal.deal_id)).scalar() or 0

    won_deals = (
        db.query(func.count(Deal.deal_id))
        .filter(Deal.deal_stage == "Closed Won")
        .scalar()
        or 0
    )

    lost_deals = (
        db.query(func.count(Deal.deal_id))
        .filter(Deal.deal_stage == "Closed Lost")
        .scalar()
        or 0
    )

    total_revenue = (
        db.query(func.sum(Deal.deal_value))
        .filter(Deal.deal_stage == "Closed Won")
        .scalar()
        or 0
    )

    pending_tasks = (
        db.query(func.count(Task.task_id)).filter(Task.status != "Completed").scalar()
        or 0
    )

    # =====================
    # Pipelines
    # =====================
    lead_pipeline = get_lead_pipeline(db)["pipeline"]
    deal_pipeline = get_deal_pipeline(db)

    # =====================
    # Conversion / Win Rate
    # =====================
    conversion_rate = round((won_deals / total_deals) * 100, 2) if total_deals else 0

    win_rate = (
        round((won_deals / (won_deals + lost_deals)) * 100, 2)
        if (won_deals + lost_deals)
        else 0
    )

    # =====================
    # Lead Sources
    # =====================
    lead_sources = top_lead_sources(db)

    # =====================
    # Final Structure
    # =====================
    return {
        "success": True,
        "report_type": "dashboard",
        "data": {
            "kpis": {
                "total_leads": total_leads,
                "total_companies": total_companies,
                "total_contacts": total_contacts,
                "total_deals": total_deals,
                "won_deals": won_deals,
                "lost_deals": lost_deals,
                "open_deals": total_deals - (won_deals + lost_deals),
                "total_revenue": float(total_revenue),
                "pending_tasks": pending_tasks,
            },
            "pipelines": {
                "lead_pipeline": lead_pipeline,
                "deal_pipeline": deal_pipeline,
            },
            "conversion": {
                "deal_conversion_rate": conversion_rate,
                "win_rate": win_rate,
            },
            "lead_sources": lead_sources,
        },
    }


@traceable(name="generate_sales_dashboard_data", run_type="tool")
def generate_sales_dashboard_data(db: Session) -> Dict[str, Any]:
    """
    Current project function name.
    Returns the old-compatible dashboard structure.
    """
    return generate_dashboard(db)


# ============================================================
# OPTIONAL PDF REPORT
# ============================================================


@traceable(name="generate_pdf_report", run_type="tool")
def generate_pdf_report(db: Session) -> Dict[str, Any]:
    """
    Optional PDF report.
    If reportlab is not installed, returns a clean error instead of crashing.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
    except ImportError:
        return {
            "success": False,
            "message": "reportlab is not installed. Run: pip install reportlab",
        }

    dashboard = generate_dashboard(db)
    data = dashboard.get("data", {})
    kpis = data.get("kpis", {})
    lead_pipeline = data.get("pipelines", {}).get("lead_pipeline", {})
    lead_sources = data.get("lead_sources", {})

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()

    content = []

    content.append(Paragraph("CRM SALES REPORT", styles["Title"]))
    content.append(Spacer(1, 12))

    content.append(
        Paragraph(f"Total Leads: {kpis.get('total_leads', 0)}", styles["Normal"])
    )
    content.append(
        Paragraph(f"Won Deals: {kpis.get('won_deals', 0)}", styles["Normal"])
    )
    content.append(
        Paragraph(f"Lost Deals: {kpis.get('lost_deals', 0)}", styles["Normal"])
    )
    content.append(
        Paragraph(f"Open Deals: {kpis.get('open_deals', 0)}", styles["Normal"])
    )
    content.append(
        Paragraph(f"Revenue: {kpis.get('total_revenue', 0)}", styles["Normal"])
    )
    content.append(Spacer(1, 12))

    content.append(Paragraph("Lead Pipeline", styles["Heading2"]))
    for status, count in lead_pipeline.items():
        content.append(Paragraph(f"{status}: {count}", styles["Normal"]))
    content.append(Spacer(1, 12))

    content.append(Paragraph("Lead Sources", styles["Heading2"]))
    for source, count in lead_sources.items():
        content.append(Paragraph(f"{source}: {count}", styles["Normal"]))

    doc.build(content)

    buffer.seek(0)

    return {
        "success": True,
        "file": buffer.getvalue(),
    }
