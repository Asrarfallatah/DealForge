# backend/db/models.py

from sqlalchemy import (
    Column,
    Integer,
    Text,
    String,
    Date,
    DateTime,
    Numeric,
    ForeignKey,
    CheckConstraint,
    UniqueConstraint,
    Index,
    JSON,
    func,
)

from sqlalchemy import (
    Column,
    Integer,
    Text,
    DateTime,
    Float,
    func,
)
from sqlalchemy.orm import relationship

from db.database import Base


# =========================
# Allowed values
# =========================

LEAD_STATUSES = [
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

DEAL_STAGES = [
    "Prospecting",
    "Discovery",
    "Qualified",
    "Proposal",
    "Negotiation",
    "Closed Won",
    "Closed Lost",
]

TASK_STATUSES = [
    "Pending",
    "In Progress",
    "Completed",
    "Cancelled",
]

APPROVAL_STATUSES = [
    "Pending",
    "Approved",
    "Rejected",
    "Cancelled",
    "Execution Failed",
]


# =========================
# Campaigns
# =========================

class Campaign(Base):
    __tablename__ = "campaigns"

    campaign_id = Column(Integer, primary_key=True, index=True)
    name = Column(Text, nullable=False)
    channel = Column(Text, nullable=False)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    status = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    leads = relationship("Lead", back_populates="campaign")


# =========================
# Companies
# =========================

class Company(Base):
    __tablename__ = "companies"

    company_id = Column(Integer, primary_key=True, index=True)
    company_name = Column(Text, nullable=False, unique=True)
    industry = Column(Text, nullable=True)
    size = Column(Text, nullable=True)
    location = Column(Text, nullable=True)
    website = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    source = Column(String, nullable=True)
    description = Column(Text, nullable=True)

    contacts = relationship("Contact", back_populates="company")
    leads = relationship("Lead", back_populates="company")
    deals = relationship("Deal", back_populates="company")


# =========================
# Contacts
# =========================

class Contact(Base):
    __tablename__ = "contacts"

    contact_id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey("companies.company_id"), nullable=False)
    full_name = Column(Text, nullable=False)
    email = Column(Text, nullable=True)
    phone = Column(Text, nullable=True)
    job_title = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    company = relationship("Company", back_populates="contacts")
    leads = relationship("Lead", back_populates="contact")
    activities = relationship("Activity", back_populates="contact")


# =========================
# Leads
# =========================

class Lead(Base):
    __tablename__ = "leads"

    lead_id = Column(Integer, primary_key=True, index=True)
    contact_id = Column(Integer, ForeignKey("contacts.contact_id"), nullable=True)
    company_id = Column(Integer, ForeignKey("companies.company_id"), nullable=False)
    campaign_id = Column(Integer, ForeignKey("campaigns.campaign_id"), nullable=True)

    lead_source = Column(Text, nullable=True)
    status = Column(Text, nullable=True)
    interest = Column(Text, nullable=True)
    priority = Column(Text, nullable=True)
    owner_name = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_summary = Column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('New', 'Contacted', 'Responded', 'Qualified', "
            "'Proposal Sent', 'Negotiation', 'Won', 'Lost', 'Stalled')",
            name="check_lead_status",
        ),
    )

    company = relationship("Company", back_populates="leads")
    contact = relationship("Contact", back_populates="leads")
    campaign = relationship("Campaign", back_populates="leads")

    deal = relationship("Deal", back_populates="lead", uselist=False)
    activities = relationship("Activity", back_populates="lead")
    tasks = relationship("Task", back_populates="lead")
    stage_history = relationship("StageHistory", back_populates="lead")


# =========================
# Deals
# =========================

class Deal(Base):
    __tablename__ = "deals"

    deal_id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.lead_id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.company_id"), nullable=False)

    deal_name = Column(Text, nullable=True)
    deal_value = Column(Numeric(12, 2), nullable=True)
    deal_stage = Column(Text, nullable=True)
    probability = Column(Integer, nullable=True)
    expected_close_date = Column(Date, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "deal_stage IN ('Prospecting', 'Discovery', 'Qualified', "
            "'Proposal', 'Negotiation', 'Closed Won', 'Closed Lost')",
            name="check_deal_stage",
        ),
    )

    lead = relationship("Lead", back_populates="deal")
    company = relationship("Company", back_populates="deals")
    activities = relationship("Activity", back_populates="deal")


# =========================
# Tasks
# =========================

class Task(Base):
    __tablename__ = "tasks"

    task_id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.lead_id"), nullable=False)

    task_title = Column(Text, nullable=False)
    due_date = Column(Date, nullable=True)
    status = Column(Text, nullable=True)
    priority = Column(Text, nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('Pending', 'In Progress', 'Completed', 'Cancelled')",
            name="check_task_status",
        ),
    )

    lead = relationship("Lead", back_populates="tasks")


# =========================
# Activities
# =========================

class Activity(Base):
    __tablename__ = "activities"

    activity_id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.lead_id"), nullable=False)
    contact_id = Column(Integer, ForeignKey("contacts.contact_id"), nullable=True)
    deal_id = Column(Integer, ForeignKey("deals.deal_id"), nullable=True)

    activity_type = Column(Text, nullable=True)
    activity_notes = Column(Text, nullable=False)
    activity_date = Column(DateTime(timezone=True), server_default=func.now())
    created_by = Column(Text, nullable=True)

    lead = relationship("Lead", back_populates="activities")
    contact = relationship("Contact", back_populates="activities")
    deal = relationship("Deal", back_populates="activities")


# =========================
# Stage History
# =========================

class StageHistory(Base):
    __tablename__ = "stage_history"

    history_id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.lead_id"), nullable=False)

    old_status = Column(Text, nullable=True)
    new_status = Column(Text, nullable=False)
    changed_at = Column(DateTime(timezone=True), server_default=func.now())
    changed_by = Column(Text, nullable=True)

    lead = relationship("Lead", back_populates="stage_history")


# =========================
# Agent Pending Updates
# =========================

class AgentPendingUpdate(Base):
    __tablename__ = "agent_pending_updates"

    pending_id = Column(Integer, primary_key=True, index=True)

    user_input = Column(Text, nullable=False)
    detected_intent = Column(Text, nullable=True)

    # في الداتابيس عندك text، لذلك نخزن JSON كـ string لاحقًا
    extracted_data = Column(Text, nullable=True)
    proposed_update = Column(Text, nullable=True)

    approval_status = Column(Text, nullable=True)
    approved_by = Column(Text, nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "approval_status IN ('Pending', 'Approved', 'Rejected', "
            "'Cancelled', 'Execution Failed')",
            name="check_approval_status",
        ),
    )


# =========================
# LongTermMemory
# =========================

class LongTermMemory(Base):
    __tablename__ = "long_term_memory"

    memory_id = Column(Integer, primary_key=True, index=True)

    # Session / source
    session_id = Column(Text, nullable=True, index=True)

    # Memory classification
    memory_type = Column(Text, nullable=False, default="crm_interaction", index=True)

    # Main memory text that will be embedded into FAISS
    memory_text = Column(Text, nullable=False)

    # Structured CRM metadata
    contact_name = Column(Text, nullable=True, index=True)
    company_name = Column(Text, nullable=True, index=True)
    lead_id = Column(Integer, nullable=True, index=True)
    intent = Column(Text, nullable=True, index=True)

    # Extra metadata as JSON
    memory_metadata = Column(JSON, nullable=True)

    # Optional importance score
    importance_score = Column(Float, default=1.0)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )