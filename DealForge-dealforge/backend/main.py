# backend/main.py

import json
from pathlib import Path
from typing import Optional, Any

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from db.database import SessionLocal, engine, Base
from db import models

from agents.graph import run_agent_message
from tools.vector_memory_tools import save_long_term_memory

# ============================================================
# FASTAPI APP
# ============================================================

app = FastAPI(
    title="DealForge API",
    description="Agentic CRM backend with human approval workflow",
    version="1.0.0",
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# FRONTEND STATIC FILES
# ============================================================

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

if FRONTEND_DIR.exists():
    app.mount(
        "/app",
        StaticFiles(directory=str(FRONTEND_DIR), html=True),
        name="frontend",
    )


@app.get("/")
def root():
    if FRONTEND_DIR.exists():
        return RedirectResponse(url="/app/")
    return {"message": "DealForge API is running. Open /docs for Swagger."}


# ============================================================
# DATABASE
# ============================================================


@app.on_event("startup")
def on_startup():
    print("Creating tables if they do not exist...")
    Base.metadata.create_all(bind=engine)
    print("Application startup complete.")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================
# MODELS
# ============================================================

Company = models.Company
Contact = models.Contact
Lead = models.Lead
Deal = models.Deal
Task = models.Task

AgentPendingUpdate = getattr(
    models,
    "AgentPendingUpdate",
    getattr(models, "AgentPendingUpdates", None),
)


# ============================================================
# REQUEST SCHEMAS
# ============================================================


class AgentChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str


class AgentDecisionRequest(BaseModel):
    pending_id: int
    decision: str
    decided_by: Optional[str] = "frontend_user"
    edited_data: Optional[dict] = None
    session_id: Optional[str] = None


class SaveReportRequest(BaseModel):
    generated_at: Optional[str] = None
    report_type: Optional[str] = None
    report: Optional[dict] = None
    dashboard: Optional[dict] = None
    approvals: Optional[list] = None


# ============================================================
# HELPERS
# ============================================================


def to_value(value: Any):
    if value is None:
        return None

    if hasattr(value, "isoformat"):
        return value.isoformat()

    return value


def safe_json_load(value):
    if value is None:
        return None

    if isinstance(value, (dict, list)):
        return value

    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value

    return value


def get_attr(obj, name, default=None):
    return getattr(obj, name, default)


def company_to_dict(company):
    return {
        "company_id": get_attr(company, "company_id"),
        "company_name": get_attr(company, "company_name"),
        "industry": get_attr(company, "industry"),
        "size": get_attr(company, "size"),
        "location": get_attr(company, "location"),
        "website": get_attr(company, "website"),
        "source": get_attr(company, "source"),
        "description": get_attr(company, "description"),
        "created_at": to_value(get_attr(company, "created_at")),
    }


def contact_to_dict(contact):
    return {
        "contact_id": get_attr(contact, "contact_id"),
        "company_id": get_attr(contact, "company_id"),
        "full_name": get_attr(contact, "full_name"),
        "email": get_attr(contact, "email"),
        "phone": get_attr(contact, "phone"),
        "job_title": get_attr(contact, "job_title"),
        "created_at": to_value(get_attr(contact, "created_at")),
    }


def lead_to_dict(lead, company_map=None, contact_map=None):
    company = company_map.get(lead.company_id) if company_map else None
    contact = contact_map.get(lead.contact_id) if contact_map else None

    return {
        "lead_id": get_attr(lead, "lead_id"),
        "company_id": get_attr(lead, "company_id"),
        "contact_id": get_attr(lead, "contact_id"),
        "company_name": get_attr(company, "company_name") if company else None,
        "contact_name": get_attr(contact, "full_name") if contact else None,
        "status": get_attr(lead, "status"),
        "lead_source": get_attr(lead, "lead_source"),
        "interest": get_attr(lead, "interest"),
        "priority": get_attr(lead, "priority"),
        "owner_name": get_attr(lead, "owner_name"),
        "last_summary": get_attr(lead, "last_summary"),
        "created_at": to_value(get_attr(lead, "created_at")),
    }


def deal_to_dict(deal):
    return {
        "deal_id": get_attr(deal, "deal_id"),
        "lead_id": get_attr(deal, "lead_id"),
        "deal_name": get_attr(deal, "deal_name"),
        "deal_value": get_attr(deal, "deal_value"),
        "deal_stage": get_attr(deal, "deal_stage"),
        "probability": get_attr(deal, "probability"),
        "expected_close_date": to_value(get_attr(deal, "expected_close_date")),
        "created_at": to_value(get_attr(deal, "created_at")),
    }


def task_to_dict(task):
    return {
        "task_id": get_attr(task, "task_id"),
        "lead_id": get_attr(task, "lead_id"),
        "deal_id": get_attr(task, "deal_id"),
        "task_title": get_attr(task, "task_title"),
        "due_date": to_value(get_attr(task, "due_date")),
        "status": get_attr(task, "status", get_attr(task, "task_status")),
        "priority": get_attr(task, "priority"),
        "completed_at": to_value(get_attr(task, "completed_at")),
        "created_at": to_value(get_attr(task, "created_at")),
    }


def pending_to_dict(pending):
    return {
        "pending_id": get_attr(pending, "pending_id"),
        "user_input": get_attr(pending, "user_input"),
        "detected_intent": get_attr(pending, "detected_intent"),
        "extracted_data": safe_json_load(get_attr(pending, "extracted_data")),
        "proposed_update": safe_json_load(get_attr(pending, "proposed_update")),
        "approval_status": get_attr(pending, "approval_status"),
        "approved_by": get_attr(pending, "approved_by"),
        "approved_at": to_value(get_attr(pending, "approved_at")),
        "created_at": to_value(get_attr(pending, "created_at")),
    }


def json_safe(value):
    try:
        json.dumps(value, ensure_ascii=False, default=str)
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except Exception:
        return str(value)


def save_approval_decision_to_memory(
    db: Session,
    request: AgentDecisionRequest,
    decision_result: dict,
):
    """
    Save approval/edit/cancel decision as long-term memory.
    This stores the final outcome of a pending CRM update in DB + FAISS.
    """

    try:
        if AgentPendingUpdate is None:
            return

        pending = (
            db.query(AgentPendingUpdate)
            .filter(AgentPendingUpdate.pending_id == request.pending_id)
            .first()
        )

        pending_data = pending_to_dict(pending) if pending else {}

        extracted_data = pending_data.get("extracted_data") or {}
        proposed_update = pending_data.get("proposed_update") or {}

        execution_result = (
            decision_result.get("execution_result")
            if isinstance(decision_result, dict)
            else {}
        ) or {}

        decision = (request.decision or "").lower().strip()
        approval_status = (
            decision_result.get("approval_status")
            if isinstance(decision_result, dict)
            else None
        )

        lead_id = (
            execution_result.get("lead_id")
            or decision_result.get("lead_id")
            or extracted_data.get("lead_id")
            or proposed_update.get("lead_id")
        )

        contact_name = extracted_data.get("contact_name") or proposed_update.get(
            "contact_name"
        )

        company_name = extracted_data.get("company_name") or proposed_update.get(
            "company_name"
        )

        intent = (
            pending_data.get("detected_intent")
            or extracted_data.get("intent")
            or proposed_update.get("intent")
        )

        user_input = pending_data.get("user_input") or ""

        if decision == "approve":
            if decision_result.get("success"):
                outcome_text = "The user approved the pending CRM update and it was executed successfully."
            else:
                outcome_text = (
                    "The user approved the pending CRM update, but execution failed."
                )
        elif decision == "edit":
            outcome_text = "The user edited the pending CRM update. The update is still waiting for approval."
        elif decision in ["cancel", "reject"]:
            outcome_text = "The user cancelled the pending CRM update. No CRM database changes were applied."
        else:
            outcome_text = f"The user made a pending update decision: {decision}."

        memory_text = f"""
Pending CRM update decision for pending_id {request.pending_id}.
Original user request: {user_input}
Decision: {decision}
Approval status: {approval_status}
Outcome: {outcome_text}
Contact: {contact_name}
Company: {company_name}
Lead ID: {lead_id}
Intent: {intent}
""".strip()

        memory_metadata = {
            "event_type": "approval_decision",
            "pending_id": request.pending_id,
            "decision": decision,
            "approval_status": approval_status,
            "pending_data": pending_data,
            "decision_result": json_safe(decision_result),
        }

        save_long_term_memory(
            db=db,
            session_id=request.session_id,
            memory_type="approval_decision",
            memory_text=memory_text,
            contact_name=contact_name,
            company_name=company_name,
            lead_id=lead_id,
            intent=intent,
            memory_metadata=memory_metadata,
            importance_score=3.0,
        )

    except Exception as error:
        print("Approval long-term memory save failed:", error)


def count_by_field(items, field_name: str):
    result = {}

    for item in items:
        key = get_attr(item, field_name) or "Unknown"
        result[key] = result.get(key, 0) + 1

    return result


# ============================================================
# HEALTH
# ============================================================


@app.get("/test-db")
def test_db(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))

        return {
            "success": True,
            "message": "Database connected successfully.",
            "tables": {
                "companies": db.query(Company).count(),
                "contacts": db.query(Contact).count(),
                "leads": db.query(Lead).count(),
                "deals": db.query(Deal).count(),
                "tasks": db.query(Task).count(),
            },
        }

    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


# ============================================================
# AGENT ENDPOINTS
# ============================================================


@app.post("/agent/chat")
def agent_chat(request: AgentChatRequest, db: Session = Depends(get_db)):
    if not request.message or not request.message.strip():
        raise HTTPException(status_code=400, detail="message is required.")

    try:
        result = run_agent_message(
            db=db,
            user_message=request.message,
            session_id=request.session_id,
        )

        return result

    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


@app.post("/agent/decision")
def agent_decision(request: AgentDecisionRequest, db: Session = Depends(get_db)):
    try:
        result = run_agent_message(
            db=db,
            user_message=f"APPROVAL_DECISION: {request.pending_id} | {request.decision}",
            session_id=request.session_id,
        )

        return result

    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


# ============================================================
# CRM DATA ENDPOINTS
# ============================================================


@app.get("/companies")
def get_companies(db: Session = Depends(get_db)):
    companies = db.query(Company).order_by(Company.company_id.desc()).all()
    return [company_to_dict(company) for company in companies]


@app.get("/contacts")
def get_contacts(db: Session = Depends(get_db)):
    contacts = db.query(Contact).order_by(Contact.contact_id.desc()).all()
    return [contact_to_dict(contact) for contact in contacts]


@app.get("/leads")
def get_leads(db: Session = Depends(get_db)):
    leads = db.query(Lead).order_by(Lead.lead_id.desc()).all()
    companies = db.query(Company).all()
    contacts = db.query(Contact).all()

    company_map = {company.company_id: company for company in companies}
    contact_map = {contact.contact_id: contact for contact in contacts}

    return [
        lead_to_dict(
            lead=lead,
            company_map=company_map,
            contact_map=contact_map,
        )
        for lead in leads
    ]


@app.get("/deals")
def get_deals(db: Session = Depends(get_db)):
    deals = db.query(Deal).order_by(Deal.deal_id.desc()).all()
    return [deal_to_dict(deal) for deal in deals]


@app.get("/tasks")
def get_tasks(db: Session = Depends(get_db)):
    tasks = db.query(Task).order_by(Task.task_id.desc()).all()
    return [task_to_dict(task) for task in tasks]


@app.put("/tasks/{task_id}")
def update_task_status(
    task_id: int,
    status: str = Query(...),
    db: Session = Depends(get_db),
):
    task = db.query(Task).filter(Task.task_id == task_id).first()

    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    if hasattr(task, "status"):
        task.status = status
    elif hasattr(task, "task_status"):
        task.task_status = status
    else:
        raise HTTPException(status_code=500, detail="Task status field not found.")

    db.commit()
    db.refresh(task)

    return {
        "success": True,
        "message": "Task status updated successfully.",
        "task": task_to_dict(task),
    }


# ============================================================
# DASHBOARD ENDPOINTS
# ============================================================


@app.get("/dashboard/overview")
def dashboard_overview(db: Session = Depends(get_db)):
    companies_count = db.query(Company).count()
    contacts_count = db.query(Contact).count()
    leads = db.query(Lead).all()
    deals = db.query(Deal).all()
    tasks = db.query(Task).all()

    pipeline = count_by_field(leads, "status")
    task_stats = count_by_field(tasks, "status")

    total_deals = len(deals)

    won_deals = [
        deal
        for deal in deals
        if str(get_attr(deal, "deal_stage") or "").lower() == "won"
    ]

    total_revenue = sum(float(get_attr(deal, "deal_value") or 0) for deal in won_deals)

    pending_tasks = [
        task
        for task in tasks
        if str(get_attr(task, "status", get_attr(task, "task_status")) or "").lower()
        == "pending"
    ]

    return {
        "total_companies": companies_count,
        "total_contacts": contacts_count,
        "total_leads": len(leads),
        "total_deals": total_deals,
        "won_deals": len(won_deals),
        "total_revenue": total_revenue,
        "pending_tasks": len(pending_tasks),
        "pipeline": pipeline,
        "task_stats": task_stats,
    }


@app.get("/dashboard/pipeline")
def dashboard_pipeline(db: Session = Depends(get_db)):
    leads = db.query(Lead).all()
    return count_by_field(leads, "status")


@app.get("/dashboard/tasks")
def dashboard_tasks(db: Session = Depends(get_db)):
    tasks = db.query(Task).all()

    result = {}

    for task in tasks:
        status = get_attr(task, "status", get_attr(task, "task_status")) or "Unknown"
        result[status] = result.get(status, 0) + 1

    return result


@app.get("/deals/pipeline")
def deals_pipeline(db: Session = Depends(get_db)):
    deals = db.query(Deal).all()
    return count_by_field(deals, "deal_stage")


@app.get("/kanban")
def kanban(db: Session = Depends(get_db)):
    leads = get_leads(db)

    board = {}

    for lead in leads:
        status = lead.get("status") or "Unknown"
        board.setdefault(status, []).append(lead)

    return board


# ============================================================
# APPROVALS
# ============================================================


@app.get("/approvals")
def get_approvals(db: Session = Depends(get_db)):
    if AgentPendingUpdate is None:
        return []

    pending_items = (
        db.query(AgentPendingUpdate)
        .order_by(AgentPendingUpdate.pending_id.desc())
        .all()
    )

    return [pending_to_dict(item) for item in pending_items]


# ============================================================
# REPORT SNAPSHOT SAVE
# ============================================================


@app.post("/reports/save-local")
def save_local_report(request: SaveReportRequest):
    reports_dir = Path(__file__).resolve().parent / "local_reports"
    reports_dir.mkdir(exist_ok=True)

    filename = f"dealforge_report_{len(list(reports_dir.glob('*.json'))) + 1}.json"
    file_path = reports_dir / filename

    payload = request.model_dump()

    with open(file_path, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2, default=str)

    return {
        "success": True,
        "message": "Report saved successfully.",
        "file": str(file_path),
    }
