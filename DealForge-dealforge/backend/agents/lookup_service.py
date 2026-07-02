# backend/agents/lookup_service.py

from sqlalchemy.orm import Session

from tools.read_tools import (
    search_leads,
    search_company,
    search_contact,
    get_lead_history,
    get_contact_details,
    get_company_details,
    get_deal_details,
    get_pending_tasks,
)


def compact_list(items, limit: int = 5):
    """
    Limit long lists so we do not send too much data to the LLM.
    """
    if not isinstance(items, list):
        return []

    return items[:limit]


def safe_call(tool_name: str, func, **kwargs) -> dict:
    """
    Call a tool safely without breaking the whole graph.
    """
    try:
        return func(**kwargs)
    except TypeError as error:
        return {
            "success": False,
            "tool": tool_name,
            "message": f"Tool argument mismatch: {str(error)}",
        }
    except Exception as error:
        return {
            "success": False,
            "tool": tool_name,
            "message": str(error),
        }


def call_search_company(db: Session, company_name: str) -> dict:
    """
    Search company by company name using read_tools.search_company().
    read_tools.search_company expects: keyword
    """
    if not company_name:
        return {
            "success": False,
            "message": "company_name is missing.",
            "companies": [],
        }

    result = safe_call(
        "search_company",
        search_company,
        db=db,
        keyword=company_name,
    )

    # search_company returns a list, so normalize it to dict
    if isinstance(result, list):
        return {
            "success": True,
            "count": len(result),
            "companies": result,
        }

    return result


def call_search_contact(
    db: Session,
    contact_name: str,
    company_name: str = None,
) -> dict:
    """
    Search contact with company context if available.
    """
    if not contact_name:
        return {"success": False, "message": "contact_name is missing.", "contacts": []}

    result = safe_call(
        "search_contact",
        search_contact,
        db=db,
        name=contact_name,
        company_name=company_name,
    )

    if result.get("success"):
        return result

    return safe_call(
        "search_contact",
        search_contact,
        db=db,
        contact_name=contact_name,
        company_name=company_name,
    )


def call_search_leads(
    db: Session,
    company_name: str = None,
    contact_name: str = None,
    keyword: str = None,
) -> dict:
    """
    Search leads by company/contact/keyword.
    """
    return safe_call(
        "search_leads",
        search_leads,
        db=db,
        company_name=company_name,
        contact_name=contact_name,
        keyword=keyword,
    )


def lookup_records(
    db: Session,
    extraction: dict,
) -> dict:
    """
    Lookup CRM records based on LLM extraction.

    This is Python only, no LLM.
    It gives the reasoning agent real CRM context.
    """

    entities = extraction.get("entities", {}) or {}

    company_name = entities.get("company_name")
    contact_name = entities.get("contact_name")
    lead_id = entities.get("lead_id")
    company_id = entities.get("company_id")
    contact_id = entities.get("contact_id")
    deal_id = entities.get("deal_id")
    task_id = entities.get("task_id")

    context = {
        "input_entities": entities,
        "company_lookup": None,
        "contact_lookup": None,
        "lead_lookup": None,
        "lead_history": None,
        "company_details": None,
        "contact_details": None,
        "deal_details": None,
        "pending_tasks": None,
        "lookup_notes": [],
    }

    # Company lookup by ID
    if company_id:
        context["company_details"] = safe_call(
            "get_company_details",
            get_company_details,
            db=db,
            company_id=company_id,
        )

    # Company lookup by name
    if company_name:
        context["company_lookup"] = call_search_company(
            db=db,
            company_name=company_name,
        )

    # Contact lookup by ID
    if contact_id:
        context["contact_details"] = safe_call(
            "get_contact_details",
            get_contact_details,
            db=db,
            contact_id=contact_id,
        )

    # Contact lookup by name
    if contact_name:
        context["contact_lookup"] = call_search_contact(
            db=db,
            contact_name=contact_name,
            company_name=company_name,
        )

    # Lead lookup by ID
    if lead_id:
        context["lead_history"] = safe_call(
            "get_lead_history",
            get_lead_history,
            db=db,
            lead_id=lead_id,
        )

    # Lead lookup by company/contact
    if company_name or contact_name:
        context["lead_lookup"] = call_search_leads(
            db=db,
            company_name=company_name,
            contact_name=contact_name,
        )

    # Deal details
    if deal_id:
        context["deal_details"] = safe_call(
            "get_deal_details",
            get_deal_details,
            db=db,
            deal_id=deal_id,
        )

    # Pending tasks, if possible
    if lead_id:
        context["pending_tasks"] = safe_call(
            "get_pending_tasks",
            get_pending_tasks,
            db=db,
            lead_id=lead_id,
        )

    # Compact large results if needed
    if isinstance(context.get("lead_lookup"), dict):
        leads = context["lead_lookup"].get("leads", [])
        context["lead_lookup"]["leads"] = compact_list(leads, limit=5)

    if isinstance(context.get("contact_lookup"), dict):
        contacts = context["contact_lookup"].get("contacts", [])
        context["contact_lookup"]["contacts"] = compact_list(contacts, limit=5)

    if isinstance(context.get("company_lookup"), dict):
        companies = context["company_lookup"].get("companies", [])
        context["company_lookup"]["companies"] = compact_list(companies, limit=5)

    return context