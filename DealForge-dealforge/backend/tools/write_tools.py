# backend/tools/write_tools.py

from datetime import datetime, date
from typing import Optional
from langsmith import traceable

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

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
# CONSTANTS
# ============================================================

ALLOWED_LEAD_STATUSES = [
    "New",
    "Contacted",
    "Responded",
    "Qualified",
    "Proposal Sent",
    "Negotiation",
    "Won",
    "Lost",
    "Stalled",
]

ALLOWED_STATUS_TRANSITIONS = {
    "New": ["Contacted", "Stalled"],
    "Contacted": ["Responded", "Qualified", "Stalled"],
    "Responded": ["Qualified", "Proposal Sent", "Stalled"],
    "Qualified": ["Proposal Sent", "Negotiation", "Stalled"],
    "Proposal Sent": ["Negotiation", "Won", "Lost", "Stalled"],
    "Negotiation": ["Won", "Lost", "Stalled"],
    "Stalled": ["Contacted", "Responded", "Qualified"],
    "Won": [],
    "Lost": [],
}

ALLOWED_DEAL_STAGES = [
    "Prospecting",
    "Discovery",
    "Qualified",
    "Proposal",
    "Negotiation",
    "Closed Won",
    "Closed Lost",
]

ALLOWED_TASK_STATUSES = [
    "Pending",
    "In Progress",
    "Completed",
    "Cancelled",
]


# ============================================================
# HELPERS
# ============================================================


def parse_due_date(value):
    if value in [None, ""]:
        return None

    if isinstance(value, date):
        return value

    if isinstance(value, str):
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return None

    return None


def safe_float(value):
    if value in [None, ""]:
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_int(value):
    """
    Convert value to int safely.
    """
    if value is None or value == "":
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_requested_status(
    old_status: Optional[str],
    requested_status: Optional[str],
) -> Optional[str]:
    if not requested_status:
        return requested_status

    status = str(requested_status).strip()

    aliases = {
        "Interested": "Contacted",
        "Replied": "Contacted",
        "Reply": "Contacted",
        "Response": "Contacted",
        "Good Fit": "Qualified",
        "Qualified Lead": "Qualified",
        "Proposal": "Proposal Sent",
        "Proposal Requested": "Proposal Sent",
        "Requested Proposal": "Proposal Sent",
        "Closed Won": "Won",
        "Closed Lost": "Lost",
        "Not Interested": "Lost",
    }

    status = aliases.get(status, status)

    if old_status == "New" and status == "Responded":
        return "Contacted"

    return status


def validate_lead_status_transition(
    current_status: str | None,
    new_status: str,
) -> dict:
    new_status = normalize_requested_status(current_status, new_status)

    if new_status not in ALLOWED_LEAD_STATUSES:
        return {
            "success": False,
            "message": f"Invalid lead status: {new_status}.",
            "allowed_statuses": ALLOWED_LEAD_STATUSES,
        }

    if not current_status:
        return {
            "success": True,
            "message": "No current status found. Transition allowed.",
            "normalized_status": new_status,
        }

    if current_status == new_status:
        return {
            "success": True,
            "message": "Lead already has this status.",
            "normalized_status": new_status,
            "skipped": True,
        }

    allowed_next = ALLOWED_STATUS_TRANSITIONS.get(current_status, [])

    if new_status not in allowed_next:
        return {
            "success": False,
            "message": f"Invalid status transition: {current_status} → {new_status}.",
            "current_status": current_status,
            "new_status": new_status,
            "allowed_next_statuses": allowed_next,
        }

    return {
        "success": True,
        "message": f"Transition from {current_status} to {new_status} is allowed.",
        "normalized_status": new_status,
    }


# ============================================================
# WRITE TOOLS - CREATE
# ============================================================
@traceable(name="create_company", run_type="tool")
def create_company(
    db: Session,
    company_name: str,
    industry: str | None = None,
    size: str | None = None,
    location: str | None = None,
    website: str | None = None,
    source: str | None = None,
    description: str | None = None,
) -> dict:
    if not company_name:
        return {
            "success": False,
            "message": "company_name is required.",
        }

    company_name = company_name.strip()

    existing_company = (
        db.query(Company).filter(Company.company_name.ilike(company_name)).first()
    )

    if existing_company:
        return {
            "success": False,
            "message": "Company already exists.",
            "company_id": existing_company.company_id,
        }

    company = Company(
        company_name=company_name,
        industry=industry,
        size=size,
        location=location,
        website=website,
        source=source,
        description=description,
    )

    try:
        db.add(company)
        db.commit()
        db.refresh(company)
    except IntegrityError:
        db.rollback()
        return {
            "success": False,
            "message": "Company already exists or violates database constraint.",
        }

    return {
        "success": True,
        "message": "Company created successfully.",
        "company_id": company.company_id,
    }


@traceable(name="create_contact", run_type="tool")
def create_contact(
    db: Session,
    company_id: int,
    full_name: str,
    email: str | None = None,
    phone: str | None = None,
    job_title: str | None = None,
) -> dict:
    company = db.query(Company).filter(Company.company_id == company_id).first()

    if not company:
        return {
            "success": False,
            "message": "Company not found.",
        }

    if not full_name:
        return {
            "success": False,
            "message": "full_name is required.",
        }

    full_name = full_name.strip()

    existing_contact = (
        db.query(Contact)
        .filter(
            Contact.company_id == company_id,
            Contact.full_name.ilike(full_name),
        )
        .first()
    )

    if existing_contact:
        return {
            "success": False,
            "message": "Contact already exists for this company.",
            "contact_id": existing_contact.contact_id,
        }

    contact = Contact(
        company_id=company_id,
        full_name=full_name,
        email=email,
        phone=phone,
        job_title=job_title,
    )

    db.add(contact)
    db.commit()
    db.refresh(contact)

    return {
        "success": True,
        "message": "Contact created successfully.",
        "contact_id": contact.contact_id,
    }


@traceable(name="create_lead", run_type="tool")
def create_lead(
    db: Session,
    company_id: int,
    contact_id: int | None = None,
    campaign_id: int | None = None,
    lead_source: str | None = None,
    status: str = "New",
    interest: str | None = None,
    priority: str | None = None,
    owner_name: str | None = None,
    last_summary: str | None = None,
) -> dict:
    company = db.query(Company).filter(Company.company_id == company_id).first()

    if not company:
        return {
            "success": False,
            "message": "Company not found.",
        }

    status = normalize_requested_status("New", status)

    if status not in ALLOWED_LEAD_STATUSES:
        return {
            "success": False,
            "message": f"Invalid lead status: {status}.",
            "allowed_statuses": ALLOWED_LEAD_STATUSES,
        }

    if contact_id:
        contact = db.query(Contact).filter(Contact.contact_id == contact_id).first()

        if not contact:
            return {
                "success": False,
                "message": "Contact not found.",
            }

        if contact.company_id != company_id:
            return {
                "success": False,
                "message": "Contact does not belong to this company.",
            }

    if campaign_id:
        campaign = (
            db.query(Campaign).filter(Campaign.campaign_id == campaign_id).first()
        )

        if not campaign:
            return {
                "success": False,
                "message": "Campaign not found.",
            }

    lead = Lead(
        company_id=company_id,
        contact_id=contact_id,
        campaign_id=campaign_id,
        lead_source=lead_source,
        status=status,
        interest=interest,
        priority=priority,
        owner_name=owner_name,
        last_summary=last_summary,
    )

    db.add(lead)
    db.commit()
    db.refresh(lead)

    return {
        "success": True,
        "message": "Lead created successfully.",
        "lead_id": lead.lead_id,
    }


@traceable(name="create_deal", run_type="tool")
def create_deal(
    db: Session,
    lead_id: int,
    company_id: int,
    deal_name: str | None = None,
    deal_value=None,
    deal_stage: str = "Discovery",
    probability: int | None = None,
    expected_close_date=None,
) -> dict:
    lead = db.query(Lead).filter(Lead.lead_id == lead_id).first()

    if not lead:
        return {
            "success": False,
            "message": "Lead not found.",
        }

    company = db.query(Company).filter(Company.company_id == company_id).first()

    if not company:
        return {
            "success": False,
            "message": "Company not found.",
        }

    if lead.company_id != company_id:
        return {
            "success": False,
            "message": "Lead does not belong to this company.",
        }

    if deal_stage not in ALLOWED_DEAL_STAGES:
        return {
            "success": False,
            "message": f"Invalid deal stage: {deal_stage}.",
            "allowed_stages": ALLOWED_DEAL_STAGES,
        }

    deal = Deal(
        lead_id=lead_id,
        company_id=company_id,
        deal_name=deal_name,
        deal_value=safe_float(deal_value),
        deal_stage=deal_stage,
        probability=probability,
        expected_close_date=parse_due_date(expected_close_date),
    )

    db.add(deal)
    db.commit()
    db.refresh(deal)

    return {
        "success": True,
        "message": "Deal created successfully.",
        "deal_id": deal.deal_id,
    }


# ============================================================
# WRITE TOOLS - UPDATE
# ============================================================
@traceable(name="update_lead_status", run_type="tool")
def update_lead_status(
    db: Session,
    lead_id: int,
    new_status: str,
    changed_by: str = "System",
) -> dict:
    lead = db.query(Lead).filter(Lead.lead_id == lead_id).first()

    if not lead:
        return {
            "success": False,
            "message": "Lead not found.",
        }

    old_status = lead.status

    validation = validate_lead_status_transition(
        current_status=old_status,
        new_status=new_status,
    )

    if not validation["success"]:
        return {
            "success": False,
            "message": validation["message"],
            "lead_id": lead_id,
            "old_status": old_status,
            "new_status": new_status,
            "allowed_next_statuses": validation.get("allowed_next_statuses"),
        }

    normalized_status = validation.get("normalized_status", new_status)

    if validation.get("skipped"):
        return {
            "success": True,
            "message": f"Lead is already in {normalized_status} status.",
            "lead_id": lead_id,
            "old_status": old_status,
            "new_status": normalized_status,
            "skipped": True,
        }

    lead.status = normalized_status

    history = StageHistory(
        lead_id=lead_id,
        old_status=old_status,
        new_status=normalized_status,
        changed_by=changed_by,
    )

    db.add(history)
    db.commit()
    db.refresh(lead)

    return {
        "success": True,
        "message": "Lead status updated successfully.",
        "lead_id": lead_id,
        "old_status": old_status,
        "new_status": normalized_status,
    }


@traceable(name="update_deal_stage", run_type="tool")
def update_deal_stage(
    db: Session,
    deal_id: int,
    stage: str,
) -> dict:
    deal = db.query(Deal).filter(Deal.deal_id == deal_id).first()

    if not deal:
        return {
            "success": False,
            "message": "Deal not found.",
        }

    if stage not in ALLOWED_DEAL_STAGES:
        return {
            "success": False,
            "message": f"Invalid deal stage: {stage}.",
            "allowed_stages": ALLOWED_DEAL_STAGES,
        }

    deal.deal_stage = stage
    db.commit()
    db.refresh(deal)

    return {
        "success": True,
        "message": "Deal stage updated successfully.",
        "deal_id": deal.deal_id,
        "new_stage": deal.deal_stage,
    }


@traceable(name="update_task", run_type="tool")
def update_task(
    db: Session,
    task_id: int,
    status: str,
) -> dict:
    if status not in ALLOWED_TASK_STATUSES:
        return {
            "success": False,
            "message": f"Invalid task status: {status}.",
            "allowed_statuses": ALLOWED_TASK_STATUSES,
        }

    task = db.query(Task).filter(Task.task_id == task_id).first()

    if not task:
        return {
            "success": False,
            "message": "Task not found.",
        }

    task.status = status

    if status == "Completed":
        task.completed_at = datetime.now()

    db.commit()
    db.refresh(task)

    return {
        "success": True,
        "message": "Task updated successfully.",
        "task_id": task.task_id,
        "status": task.status,
        "completed_at": str(task.completed_at) if task.completed_at else None,
    }


# ============================================================
# WRITE TOOLS - ACTIVITIES / TASKS
# ============================================================
@traceable(name="create_activity", run_type="tool")
def create_activity(
    db: Session,
    lead_id: int,
    activity_type: str,
    activity_notes: str,
    created_by: str = "System",
    contact_id: int | None = None,
    deal_id: int | None = None,
) -> dict:
    lead = db.query(Lead).filter(Lead.lead_id == lead_id).first()

    if not lead:
        return {
            "success": False,
            "message": "Lead not found.",
        }

    if not activity_notes:
        return {
            "success": False,
            "message": "activity_notes is required.",
        }

    if contact_id is None:
        contact_id = lead.contact_id

    if deal_id is None:
        deal = db.query(Deal).filter(Deal.lead_id == lead_id).first()
        deal_id = deal.deal_id if deal else None

    activity = Activity(
        lead_id=lead_id,
        contact_id=contact_id,
        deal_id=deal_id,
        activity_type=activity_type or "Note",
        activity_notes=activity_notes,
        created_by=created_by,
    )

    db.add(activity)
    db.commit()
    db.refresh(activity)

    return {
        "success": True,
        "message": "Activity created successfully.",
        "activity_id": activity.activity_id,
        "lead_id": lead_id,
        "activity_type": activity.activity_type,
        "activity_notes": activity.activity_notes,
    }


@traceable(name="log_activity", run_type="tool")
def log_activity(
    db: Session,
    lead_id: int,
    activity_type: str,
    activity_notes: str,
    created_by: str = "System",
    contact_id: int | None = None,
    deal_id: int | None = None,
) -> dict:
    return create_activity(
        db=db,
        lead_id=lead_id,
        activity_type=activity_type,
        activity_notes=activity_notes,
        created_by=created_by,
        contact_id=contact_id,
        deal_id=deal_id,
    )


@traceable(name="create_follow_up_task", run_type="tool")
def create_follow_up_task(
    db: Session,
    lead_id: int,
    task_title: str,
    due_date=None,
    priority: str | None = None,
) -> dict:
    lead = db.query(Lead).filter(Lead.lead_id == lead_id).first()

    if not lead:
        return {
            "success": False,
            "message": "Lead not found.",
        }

    if not task_title:
        return {
            "success": False,
            "message": "task_title is required.",
        }

    task = Task(
        lead_id=lead_id,
        task_title=task_title,
        due_date=parse_due_date(due_date),
        status="Pending",
        priority=priority,
    )

    db.add(task)
    db.commit()
    db.refresh(task)

    return {
        "success": True,
        "message": "Follow-up task created successfully.",
        "task_id": task.task_id,
        "lead_id": lead_id,
        "task_title": task.task_title,
        "due_date": str(task.due_date) if task.due_date else None,
        "status": task.status,
        "priority": task.priority,
    }


@traceable(name="create_task", run_type="tool")
def create_task(
    db: Session,
    lead_id: int,
    title: str,
) -> dict:
    return create_follow_up_task(
        db=db,
        lead_id=lead_id,
        task_title=title,
        due_date=None,
        priority=None,
    )


# ============================================================
# UPDATE TOOLS
# ============================================================
@traceable(name="update_company", run_type="tool")
def update_company(
    db: Session,
    company_id: int,
    company_name: str = None,
    industry: str = None,
    size: str = None,
    location: str = None,
    website: str = None,
    source: str = None,
    description: str = None,
) -> dict:
    """
    Update company fields.
    Does not delete anything.
    """

    company = db.query(Company).filter(Company.company_id == company_id).first()

    if not company:
        return {
            "success": False,
            "message": "Company not found.",
            "company_id": company_id,
        }

    old_values = {
        "company_name": company.company_name,
        "industry": company.industry,
        "size": company.size,
        "location": company.location,
        "website": company.website,
        "source": company.source,
        "description": company.description,
    }

    if company_name is not None and company_name != company.company_name:
        existing_company = (
            db.query(Company)
            .filter(Company.company_name == company_name)
            .filter(Company.company_id != company_id)
            .first()
        )

        if existing_company:
            return {
                "success": False,
                "message": "Another company with this name already exists.",
                "company_id": company_id,
                "duplicate_company_id": existing_company.company_id,
            }

        company.company_name = company_name

    if industry is not None:
        company.industry = industry

    if size is not None:
        company.size = size

    if location is not None:
        company.location = location

    if website is not None:
        company.website = website

    if source is not None:
        company.source = source

    if description is not None:
        company.description = description

    db.commit()
    db.refresh(company)

    updated_values = {
        "company_name": company.company_name,
        "industry": company.industry,
        "size": company.size,
        "location": company.location,
        "website": company.website,
        "source": company.source,
        "description": company.description,
    }

    return {
        "success": True,
        "message": "Company updated successfully.",
        "company_id": company.company_id,
        "old_values": old_values,
        "updated_values": updated_values,
    }


@traceable(name="update_contact", run_type="tool")
def update_contact(
    db: Session,
    contact_id: int,
    company_id: int = None,
    full_name: str = None,
    email: str = None,
    phone: str = None,
    job_title: str = None,
) -> dict:
    """
    Update contact fields.
    Does not delete anything.
    """

    contact = db.query(Contact).filter(Contact.contact_id == contact_id).first()

    if not contact:
        return {
            "success": False,
            "message": "Contact not found.",
            "contact_id": contact_id,
        }

    old_values = {
        "company_id": contact.company_id,
        "full_name": contact.full_name,
        "email": contact.email,
        "phone": contact.phone,
        "job_title": contact.job_title,
    }

    target_company_id = company_id if company_id is not None else contact.company_id

    company = db.query(Company).filter(Company.company_id == target_company_id).first()

    if not company:
        return {
            "success": False,
            "message": "Company not found for this contact update.",
            "company_id": target_company_id,
        }

    new_name = full_name if full_name is not None else contact.full_name

    duplicate_contact = (
        db.query(Contact)
        .filter(Contact.company_id == target_company_id)
        .filter(Contact.full_name == new_name)
        .filter(Contact.contact_id != contact_id)
        .first()
    )

    if duplicate_contact:
        return {
            "success": False,
            "message": "Another contact with this name already exists in the same company.",
            "contact_id": contact_id,
            "duplicate_contact_id": duplicate_contact.contact_id,
        }

    if company_id is not None:
        contact.company_id = company_id

    if full_name is not None:
        contact.full_name = full_name

    if email is not None:
        contact.email = email

    if phone is not None:
        contact.phone = phone

    if job_title is not None:
        contact.job_title = job_title

    db.commit()
    db.refresh(contact)

    updated_values = {
        "company_id": contact.company_id,
        "full_name": contact.full_name,
        "email": contact.email,
        "phone": contact.phone,
        "job_title": contact.job_title,
    }

    return {
        "success": True,
        "message": "Contact updated successfully.",
        "contact_id": contact.contact_id,
        "old_values": old_values,
        "updated_values": updated_values,
    }


@traceable(name="update_lead_fields", run_type="tool")
def update_lead_fields(
    db: Session,
    lead_id: int,
    company_id: int = None,
    contact_id: int = None,
    campaign_id: int = None,
    lead_source: str = None,
    interest: str = None,
    priority: str = None,
    owner_name: str = None,
    last_summary: str = None,
) -> dict:
    """
    Update lead fields except status.
    Lead status must be updated using update_lead_status()
    because it has transition validation and stage history.
    """

    lead = db.query(Lead).filter(Lead.lead_id == lead_id).first()

    if not lead:
        return {
            "success": False,
            "message": "Lead not found.",
            "lead_id": lead_id,
        }

    old_values = {
        "company_id": lead.company_id,
        "contact_id": lead.contact_id,
        "campaign_id": lead.campaign_id,
        "lead_source": lead.lead_source,
        "interest": lead.interest,
        "priority": lead.priority,
        "owner_name": lead.owner_name,
        "last_summary": lead.last_summary,
    }

    target_company_id = company_id if company_id is not None else lead.company_id
    target_contact_id = contact_id if contact_id is not None else lead.contact_id

    company = db.query(Company).filter(Company.company_id == target_company_id).first()

    if not company:
        return {
            "success": False,
            "message": "Company not found for this lead update.",
            "company_id": target_company_id,
        }

    if target_contact_id is not None:
        contact = (
            db.query(Contact).filter(Contact.contact_id == target_contact_id).first()
        )

        if not contact:
            return {
                "success": False,
                "message": "Contact not found for this lead update.",
                "contact_id": target_contact_id,
            }

        if contact.company_id != target_company_id:
            return {
                "success": False,
                "message": "Contact does not belong to the selected company.",
                "contact_id": target_contact_id,
                "contact_company_id": contact.company_id,
                "lead_company_id": target_company_id,
            }

    if campaign_id is not None:
        campaign = (
            db.query(Campaign).filter(Campaign.campaign_id == campaign_id).first()
        )

        if not campaign:
            return {
                "success": False,
                "message": "Campaign not found for this lead update.",
                "campaign_id": campaign_id,
            }

    if company_id is not None:
        lead.company_id = company_id

    if contact_id is not None:
        lead.contact_id = contact_id

    if campaign_id is not None:
        lead.campaign_id = campaign_id

    if lead_source is not None:
        lead.lead_source = lead_source

    if interest is not None:
        lead.interest = interest

    if priority is not None:
        lead.priority = priority

    if owner_name is not None:
        lead.owner_name = owner_name

    if last_summary is not None:
        lead.last_summary = last_summary

    db.commit()
    db.refresh(lead)

    updated_values = {
        "company_id": lead.company_id,
        "contact_id": lead.contact_id,
        "campaign_id": lead.campaign_id,
        "lead_source": lead.lead_source,
        "interest": lead.interest,
        "priority": lead.priority,
        "owner_name": lead.owner_name,
        "last_summary": lead.last_summary,
    }

    return {
        "success": True,
        "message": "Lead fields updated successfully.",
        "lead_id": lead.lead_id,
        "old_values": old_values,
        "updated_values": updated_values,
    }


@traceable(name="update_deal_fields", run_type="tool")
def update_deal_fields(
    db: Session,
    deal_id: int,
    deal_name: str = None,
    deal_value=None,
    probability=None,
    expected_close_date: str = None,
) -> dict:
    """
    Update deal fields except deal_stage.
    Deal stage must be updated using update_deal_stage().
    """

    deal = db.query(Deal).filter(Deal.deal_id == deal_id).first()

    if not deal:
        return {
            "success": False,
            "message": "Deal not found.",
            "deal_id": deal_id,
        }

    old_values = {
        "deal_name": deal.deal_name,
        "deal_value": float(deal.deal_value) if deal.deal_value is not None else None,
        "probability": deal.probability,
        "expected_close_date": (
            str(deal.expected_close_date) if deal.expected_close_date else None
        ),
    }

    parsed_deal_value = safe_float(deal_value)
    parsed_probability = safe_int(probability)

    if probability is not None:
        if (
            parsed_probability is None
            or parsed_probability < 0
            or parsed_probability > 100
        ):
            return {
                "success": False,
                "message": "Probability must be a number between 0 and 100.",
                "deal_id": deal_id,
                "probability": probability,
            }

    parsed_expected_close_date = None

    if expected_close_date is not None:
        parsed_expected_close_date = parse_due_date(expected_close_date)

        if parsed_expected_close_date is None:
            return {
                "success": False,
                "message": "Invalid expected_close_date format. Use YYYY-MM-DD.",
                "deal_id": deal_id,
                "expected_close_date": expected_close_date,
            }

    if deal_name is not None:
        deal.deal_name = deal_name

    if deal_value is not None:
        deal.deal_value = parsed_deal_value

    if probability is not None:
        deal.probability = parsed_probability

    if expected_close_date is not None:
        deal.expected_close_date = parsed_expected_close_date

    db.commit()
    db.refresh(deal)

    updated_values = {
        "deal_name": deal.deal_name,
        "deal_value": float(deal.deal_value) if deal.deal_value is not None else None,
        "probability": deal.probability,
        "expected_close_date": (
            str(deal.expected_close_date) if deal.expected_close_date else None
        ),
    }

    return {
        "success": True,
        "message": "Deal fields updated successfully.",
        "deal_id": deal.deal_id,
        "old_values": old_values,
        "updated_values": updated_values,
    }
