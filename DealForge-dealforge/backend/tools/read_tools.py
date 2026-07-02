# backend/tools/read_tools.py

from sqlalchemy import or_, func
from sqlalchemy.orm import Session
from langsmith import traceable

from db.models import (
    Company,
    Contact,
    Campaign,
    Lead,
    Deal,
    Activity,
    Task,
    StageHistory,
)

# ============================================================
# READ HELPERS
# ============================================================


@traceable(name="lead_to_dict", run_type="tool")
def lead_to_dict(lead: Lead) -> dict:
    return {
        "lead_id": lead.lead_id,
        "status": lead.status,
        "interest": lead.interest,
        "priority": lead.priority,
        "owner_name": lead.owner_name,
        "lead_source": lead.lead_source,
        "last_summary": lead.last_summary,
        "created_at": str(lead.created_at) if lead.created_at else None,
        "company": {
            "company_id": lead.company.company_id if lead.company else None,
            "company_name": lead.company.company_name if lead.company else None,
            "industry": lead.company.industry if lead.company else None,
            "size": lead.company.size if lead.company else None,
            "location": lead.company.location if lead.company else None,
            "website": lead.company.website if lead.company else None,
        },
        "contact": {
            "contact_id": lead.contact.contact_id if lead.contact else None,
            "full_name": lead.contact.full_name if lead.contact else None,
            "email": lead.contact.email if lead.contact else None,
            "phone": lead.contact.phone if lead.contact else None,
            "job_title": lead.contact.job_title if lead.contact else None,
        },
        "campaign": (
            {
                "campaign_id": lead.campaign.campaign_id if lead.campaign else None,
                "name": lead.campaign.name if lead.campaign else None,
                "channel": lead.campaign.channel if lead.campaign else None,
            }
            if lead.campaign
            else None
        ),
    }


# ============================================================
# READ TOOLS - LEADS
# ============================================================
@traceable(name="search_leads", run_tpye="tool")
def search_leads(
    db: Session,
    company_name: str | None = None,
    contact_name: str | None = None,
    lead_id: int | None = None,
    keyword: str | None = None,
    limit: int = 10,
) -> dict:
    query = (
        db.query(Lead)
        .join(Company, Lead.company_id == Company.company_id)
        .outerjoin(Contact, Lead.contact_id == Contact.contact_id)
        .outerjoin(Campaign, Lead.campaign_id == Campaign.campaign_id)
    )

    if lead_id:
        query = query.filter(Lead.lead_id == lead_id)

    if company_name:
        query = query.filter(Company.company_name.ilike(f"%{company_name.strip()}%"))

    if contact_name:
        query = query.filter(Contact.full_name.ilike(f"%{contact_name.strip()}%"))

    if keyword:
        value = f"%{keyword.strip()}%"
        query = query.filter(
            or_(
                Company.company_name.ilike(value),
                Contact.full_name.ilike(value),
                Lead.status.ilike(value),
                Lead.interest.ilike(value),
                Lead.lead_source.ilike(value),
            )
        )

    leads = query.limit(limit).all()

    return {
        "success": True,
        "count": len(leads),
        "leads": [lead_to_dict(lead) for lead in leads],
    }


@traceable(name="search_lead", run_type="tool")
def search_lead(
    db: Session,
    name_or_company: str | None = None,
    keyword: str | None = None,
    company_name: str | None = None,
    contact_name: str | None = None,
):
    result = search_leads(
        db=db,
        company_name=company_name,
        contact_name=contact_name,
        keyword=keyword or name_or_company,
    )
    return result["leads"]


@traceable(name="get_all_leads", run_type="tool")
def get_all_leads(db: Session, limit: int = 100) -> dict:
    leads = db.query(Lead).limit(limit).all()

    return {
        "success": True,
        "count": len(leads),
        "leads": [lead_to_dict(lead) for lead in leads],
    }


@traceable(name="get_lead_by_id", run_type="tool")
def get_lead_by_id(db: Session, lead_id: int) -> dict:
    lead = db.query(Lead).filter(Lead.lead_id == lead_id).first()

    if not lead:
        return {
            "success": False,
            "message": f"No lead found with ID {lead_id}.",
            "lead": None,
        }

    return {
        "success": True,
        "lead": lead_to_dict(lead),
    }


@traceable(name="get_lead_details", run_type="tool")
def get_lead_details(db: Session, lead_id: int) -> dict:
    return get_lead_by_id(db=db, lead_id=lead_id)


@traceable(name="get_lead_history", run_type="tool")
def get_lead_history(db: Session, lead_id: int) -> dict:
    lead = db.query(Lead).filter(Lead.lead_id == lead_id).first()

    if not lead:
        return {
            "success": False,
            "message": f"No lead found with ID {lead_id}.",
        }

    deals = db.query(Deal).filter(Deal.lead_id == lead_id).all()

    activities = (
        db.query(Activity)
        .filter(Activity.lead_id == lead_id)
        .order_by(Activity.activity_date.desc())
        .all()
    )

    tasks = (
        db.query(Task)
        .filter(Task.lead_id == lead_id)
        .order_by(Task.due_date.asc().nullslast())
        .all()
    )

    stage_history = (
        db.query(StageHistory)
        .filter(StageHistory.lead_id == lead_id)
        .order_by(StageHistory.changed_at.desc())
        .all()
    )

    return {
        "success": True,
        "lead": lead_to_dict(lead),
        "deals": [
            {
                "deal_id": deal.deal_id,
                "deal_name": deal.deal_name,
                "deal_value": float(deal.deal_value) if deal.deal_value else None,
                "deal_stage": deal.deal_stage,
                "probability": deal.probability,
                "expected_close_date": (
                    str(deal.expected_close_date) if deal.expected_close_date else None
                ),
            }
            for deal in deals
        ],
        "activities": [
            {
                "activity_id": activity.activity_id,
                "activity_type": activity.activity_type,
                "activity_notes": activity.activity_notes,
                "activity_date": (
                    str(activity.activity_date) if activity.activity_date else None
                ),
                "created_by": activity.created_by,
            }
            for activity in activities
        ],
        "tasks": [
            {
                "task_id": task.task_id,
                "task_title": task.task_title,
                "due_date": str(task.due_date) if task.due_date else None,
                "status": task.status,
                "priority": task.priority,
                "completed_at": str(task.completed_at) if task.completed_at else None,
            }
            for task in tasks
        ],
        "stage_history": [
            {
                "history_id": history.history_id,
                "old_status": history.old_status,
                "new_status": history.new_status,
                "changed_at": str(history.changed_at) if history.changed_at else None,
                "changed_by": history.changed_by,
            }
            for history in stage_history
        ],
    }


@traceable(name="lead_summary", run_type="tool")
def lead_summary(db: Session, lead_id: int) -> dict:
    details = get_lead_by_id(db=db, lead_id=lead_id)

    if not details.get("success"):
        return details

    lead = details["lead"]
    company = lead.get("company") or {}
    contact = lead.get("contact") or {}

    summary = (
        f"Lead {lead.get('lead_id')} for {company.get('company_name') or 'Unknown company'} "
        f"is currently {lead.get('status')}. "
        f"Priority: {lead.get('priority') or 'not set'}. "
        f"Interest: {lead.get('interest') or 'not specified'}. "
        f"Main contact: {contact.get('full_name') or 'not specified'}."
    )

    return {
        "success": True,
        "lead_id": lead_id,
        "summary": summary,
        "details": details,
    }


@traceable(name="suggest_next_action", run_type="tool")
def suggest_next_action(db: Session, lead_id: int) -> dict:
    lead = db.query(Lead).filter(Lead.lead_id == lead_id).first()

    if not lead:
        return {
            "success": False,
            "message": "Lead not found.",
        }

    suggestions = {
        "New": "Contact the lead and confirm interest.",
        "Contacted": "Follow up and ask about needs, budget, and timeline.",
        "Responded": "Qualify the lead and identify budget and timeline.",
        "Qualified": "Prepare and send a proposal.",
        "Proposal Sent": "Follow up on the proposal and handle objections.",
        "Negotiation": "Schedule a negotiation call and confirm decision criteria.",
        "Won": "Create onboarding or handoff task.",
        "Lost": "Document loss reason and keep for future re-engagement.",
        "Stalled": "Send a re-engagement message or mark as inactive.",
    }

    return {
        "success": True,
        "lead_id": lead_id,
        "current_status": lead.status,
        "suggested_next_action": suggestions.get(
            lead.status,
            "Review lead details and decide next action.",
        ),
    }


# ============================================================
# READ TOOLS - COMPANIES
# ============================================================
@traceable(name="search_company", run_type="tool")
def search_company(db: Session, keyword: str) -> dict:
    if not keyword:
        return {
            "success": True,
            "count": 0,
            "companies": [],
        }

    companies = (
        db.query(Company)
        .filter(Company.company_name.ilike(f"%{keyword.strip()}%"))
        .all()
    )

    return {
        "success": True,
        "count": len(companies),
        "companies": [
            {
                "company_id": company.company_id,
                "company_name": company.company_name,
                "industry": company.industry,
                "size": company.size,
                "location": company.location,
                "website": company.website,
                "source": company.source,
                "description": company.description,
            }
            for company in companies
        ],
    }


@traceable(name="get_all_companies", run_type="tool")
def get_all_companies(db: Session, limit: int = 100) -> dict:
    companies = db.query(Company).limit(limit).all()

    return {
        "success": True,
        "count": len(companies),
        "companies": [
            {
                "company_id": company.company_id,
                "company_name": company.company_name,
                "industry": company.industry,
                "size": company.size,
                "location": company.location,
                "website": company.website,
                "contacts_count": len(company.contacts),
                "leads_count": len(company.leads),
                "deals_count": len(company.deals),
            }
            for company in companies
        ],
    }


@traceable(name="get_company_details", run_type="tool")
def get_company_details(db: Session, company_id: int) -> dict:
    company = db.query(Company).filter(Company.company_id == company_id).first()

    if not company:
        return {
            "success": False,
            "message": "Company not found.",
        }

    return {
        "success": True,
        "company": {
            "company_id": company.company_id,
            "company_name": company.company_name,
            "industry": company.industry,
            "size": company.size,
            "location": company.location,
            "website": company.website,
            "source": company.source,
            "description": company.description,
            "created_at": str(company.created_at) if company.created_at else None,
        },
        "contacts": [
            {
                "contact_id": contact.contact_id,
                "full_name": contact.full_name,
                "email": contact.email,
                "phone": contact.phone,
                "job_title": contact.job_title,
            }
            for contact in company.contacts
        ],
        "leads": [
            {
                "lead_id": lead.lead_id,
                "status": lead.status,
                "priority": lead.priority,
                "interest": lead.interest,
                "lead_source": lead.lead_source,
            }
            for lead in company.leads
        ],
        "deals": [
            {
                "deal_id": deal.deal_id,
                "deal_name": deal.deal_name,
                "deal_value": float(deal.deal_value) if deal.deal_value else None,
                "deal_stage": deal.deal_stage,
                "probability": deal.probability,
            }
            for deal in company.deals
        ],
    }


# ============================================================
# READ TOOLS - CONTACTS
# ============================================================
@traceable(name="search_contact", run_type="tool")
def search_contact(
    db: Session,
    name: str | None = None,
    keyword: str | None = None,
    company_name: str | None = None,
) -> dict:
    search_term = name or keyword

    query = db.query(Contact).join(Company, Contact.company_id == Company.company_id)

    if search_term:
        value = f"%{search_term.strip()}%"
        query = query.filter(
            or_(
                Contact.full_name.ilike(value),
                Contact.email.ilike(value),
                Contact.phone.ilike(value),
            )
        )

    if company_name:
        query = query.filter(Company.company_name.ilike(f"%{company_name.strip()}%"))

    contacts = query.all()

    return {
        "success": True,
        "count": len(contacts),
        "contacts": [
            {
                "contact_id": contact.contact_id,
                "company_id": contact.company_id,
                "company_name": (
                    contact.company.company_name if contact.company else None
                ),
                "full_name": contact.full_name,
                "email": contact.email,
                "phone": contact.phone,
                "job_title": contact.job_title,
                "created_at": str(contact.created_at) if contact.created_at else None,
            }
            for contact in contacts
        ],
    }


@traceable(name="get_contact_details", run_type="tool")
def get_contact_details(db: Session, contact_id: int) -> dict:
    contact = db.query(Contact).filter(Contact.contact_id == contact_id).first()

    if not contact:
        return {
            "success": False,
            "message": "Contact not found.",
        }

    return {
        "success": True,
        "contact": {
            "contact_id": contact.contact_id,
            "company_id": contact.company_id,
            "company_name": contact.company.company_name if contact.company else None,
            "full_name": contact.full_name,
            "email": contact.email,
            "phone": contact.phone,
            "job_title": contact.job_title,
            "created_at": str(contact.created_at) if contact.created_at else None,
        },
    }


# ============================================================
# READ TOOLS - DEALS / ACTIVITIES / TASKS
# ============================================================
@traceable(name="get_deal_details", run_type="tool")
def get_deal_details(db: Session, deal_id: int) -> dict:
    deal = db.query(Deal).filter(Deal.deal_id == deal_id).first()

    if not deal:
        return {
            "success": False,
            "message": "Deal not found.",
        }

    return {
        "success": True,
        "deal": {
            "deal_id": deal.deal_id,
            "lead_id": deal.lead_id,
            "company_id": deal.company_id,
            "company_name": deal.company.company_name if deal.company else None,
            "deal_name": deal.deal_name,
            "deal_value": float(deal.deal_value) if deal.deal_value else None,
            "deal_stage": deal.deal_stage,
            "probability": deal.probability,
            "expected_close_date": (
                str(deal.expected_close_date) if deal.expected_close_date else None
            ),
            "created_at": str(deal.created_at) if deal.created_at else None,
            "updated_at": str(deal.updated_at) if deal.updated_at else None,
        },
    }


@traceable(name="get_deals_pipeline", run_type="tool")
def get_deals_pipeline(db: Session) -> dict:
    rows = (
        db.query(Deal.deal_stage, func.count(Deal.deal_id))
        .group_by(Deal.deal_stage)
        .all()
    )

    return {
        "success": True,
        "pipeline_by_deal_stage": {stage or "Unknown": count for stage, count in rows},
    }


@traceable(name="get_activities", run_type="tool")
def get_activities(db: Session, lead_id: int) -> dict:
    activities = (
        db.query(Activity)
        .filter(Activity.lead_id == lead_id)
        .order_by(Activity.activity_date.desc())
        .all()
    )

    return {
        "success": True,
        "count": len(activities),
        "activities": [
            {
                "activity_id": activity.activity_id,
                "lead_id": activity.lead_id,
                "contact_id": activity.contact_id,
                "deal_id": activity.deal_id,
                "activity_type": activity.activity_type,
                "activity_notes": activity.activity_notes,
                "activity_date": (
                    str(activity.activity_date) if activity.activity_date else None
                ),
                "created_by": activity.created_by,
            }
            for activity in activities
        ],
    }


@traceable(name="get_pending_tasks", run_type="tool")
def get_pending_tasks(db: Session) -> dict:
    tasks = (
        db.query(Task)
        .filter(Task.status != "Completed")
        .order_by(Task.due_date.asc().nullslast())
        .all()
    )

    return {
        "success": True,
        "count": len(tasks),
        "tasks": [
            {
                "task_id": task.task_id,
                "lead_id": task.lead_id,
                "company_name": (
                    task.lead.company.company_name
                    if task.lead and task.lead.company
                    else None
                ),
                "task_title": task.task_title,
                "due_date": str(task.due_date) if task.due_date else None,
                "status": task.status,
                "priority": task.priority,
                "completed_at": str(task.completed_at) if task.completed_at else None,
            }
            for task in tasks
        ],
    }
