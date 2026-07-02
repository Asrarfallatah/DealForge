# backend/agents/graph.py

import json
import re
from typing import TypedDict, Optional, Any

from sqlalchemy.orm import Session
from langgraph.graph import StateGraph, END

from agents.reporting_agent import handle_reporting_request
from agents.proposal_judge_agent import judge_proposed_update

try:
    from langgraph.checkpoint.memory import InMemorySaver
except ImportError:
    from langgraph.checkpoint.memory import MemorySaver as InMemorySaver

from agents.proposal_validator import validate_proposed_update


from agents.conversation_agent import extract_user_message
from agents.lookup_service import lookup_records
from agents.reasoning_agent import reason_over_results
from agents.response_builder import build_final_response

from tools.approval_tools import create_pending_node
from tools.reporting_tools import (
    generate_pipeline_report,
    generate_sales_dashboard_data,
)
from tools.enrichment_tools import scrape_company_website
from tools.read_tools import get_lead_history, get_contact_details, get_company_details
from tools.vector_memory_tools import (
    build_memory_context,
    save_turn_as_memory,
)


class AgentState(TypedDict, total=False):
    # New user message for the current turn.
    user_message: str

    # Original message before adding memory context.
    raw_user_message: str

    # Original CRM request from the beginning of the clarification flow.
    original_user_message: str

    # Short-term memory stored by LangGraph checkpointer.
    pending_context: Optional[dict]
    used_short_term_memory: bool

    # Long-term semantic memory retrieved from FAISS.
    long_term_memory_context: str

    extraction: dict
    lookup_context: dict
    reasoning: dict

    pending_result: dict
    read_result: dict
    report_result: dict
    enrichment_result: dict

    final_response: dict
    error: Optional[str]

    validation_result: dict
    repair_result: dict
    repair_attempted: bool

    judge_result: dict


# ============================================================
# SHORT-TERM MEMORY HELPERS
# ============================================================


def _json_safe(value):
    """
    Make data safe to store inside LangGraph short-term state.
    """
    try:
        json.dumps(value, ensure_ascii=False, default=str)
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except Exception:
        return str(value)


def _get_db_from_config(config) -> Session:
    """
    DB should NOT be stored in LangGraph state.
    We pass it through config for this request only.
    """
    configurable = (config or {}).get("configurable", {}) or {}
    db = configurable.get("db")

    if db is None:
        raise ValueError("Database session is missing from LangGraph config.")

    return db


def _extract_selected_choice(user_message: str, choices: list):
    """
    Understand replies like:
    1
    option 1
    choice 1
    choose 1
    select 1
    """
    if not user_message or not isinstance(choices, list) or not choices:
        return None

    text = user_message.strip().lower()

    match = re.fullmatch(r"(?:option\s*|choice\s*|#\s*)?(\d+)", text)

    if not match:
        match = re.search(
            r"\b(?:option|choice|number|choose|select)\s*(\d+)\b",
            text,
        )

    if not match:
        return None

    index = int(match.group(1)) - 1

    if 0 <= index < len(choices):
        return choices[index]

    return None


def build_contextual_user_message(
    user_message: str, pending_context: dict | None
) -> str:
    """
    If the user is answering a previous clarification/choice,
    convert the short answer into a full contextual message.

    Example:
    User: K A from Cheers requested details.
    Agent: Which lead?
    User: 1

    This function makes "1" understandable.
    """
    if not pending_context:
        return user_message

    original_user_message = pending_context.get("original_user_message") or ""
    previous_question = (
        pending_context.get("clarification_question")
        or pending_context.get("message")
        or ""
    )
    response_type = pending_context.get("response_type") or "clarification"
    choices = pending_context.get("choices") or []

    selected_choice = _extract_selected_choice(user_message, choices)

    choices_text = ""
    if choices:
        choices_text = f"""
        Previous options shown to the user:
        {json.dumps(_json_safe(choices), ensure_ascii=False, indent=2)}
        """.strip()

    selected_choice_text = ""
    if selected_choice:
        selected_choice_text = f"""
        Resolved selected choice from previous options:
        {json.dumps(_json_safe(selected_choice), ensure_ascii=False, indent=2)}
        """.strip()

    return f"""
    This is a continuation of the same CRM conversation session.
    Do NOT treat the latest user message as a new standalone request.
    
    Original CRM request:
    {original_user_message}
    
    Previous assistant follow-up type:
    {response_type}
    
    Previous assistant question/message:
    {previous_question}
    
    {choices_text}
    
    User latest answer:
    {user_message}
    
    {selected_choice_text}
    
    Continue the original CRM request using the user's latest answer.
    If the selected choice contains lead_id, contact_id, company_id, status, interest, or owner, use those values directly.
    """.strip()


# ============================================================
# NODES
# ============================================================


def memory_prepare_node(state: AgentState, config) -> AgentState:
    """
    Prepare current user message using:
    - LangGraph short-term memory for clarification/choice continuation
    - FAISS long-term semantic memory for previous CRM context
    """

    raw_user_message = state.get("user_message", "")
    pending_context = state.get("pending_context")

    effective_user_message = build_contextual_user_message(
        user_message=raw_user_message,
        pending_context=pending_context,
    )

    original_user_message = (
        pending_context.get("original_user_message")
        if pending_context
        else raw_user_message
    )

    configurable = (config or {}).get("configurable", {}) or {}
    session_key = configurable.get("thread_id") or "dealforge-default-session"

    # Retrieve relevant long-term memories from FAISS.
    # If retrieval fails, the agent continues normally.
    try:
        long_term_memory_context = build_memory_context(
            user_message=effective_user_message,
            session_id=session_key,
            k=3,
        )
    except Exception as e:
        print("Long-term memory retrieval failed:", e)
        long_term_memory_context = "No relevant long-term memories found."

    return {
        "raw_user_message": raw_user_message,
        "user_message": effective_user_message,
        "original_user_message": original_user_message,
        "used_short_term_memory": bool(pending_context),
        "long_term_memory_context": long_term_memory_context,
        # Clear old transient fields from previous graph run.
        "extraction": {},
        "lookup_context": {},
        "reasoning": {},
        "pending_result": {},
        "read_result": {},
        "report_result": {},
        "enrichment_result": {},
        "final_response": {},
        "error": None,
        "validation_result": {},
        "repair_result": {},
        "repair_attempted": False,
    }


def extract_node(state: AgentState) -> AgentState:
    """
    Node 1:
    LLM extracts intent/entities/actions from user message.
    """

    user_message = state.get("user_message", "")

    extraction = extract_user_message(user_message)

    return {
        "extraction": extraction,
    }


def lookup_node(state: AgentState, config) -> AgentState:
    """
    Node 2:
    Python DB lookup using read tools.
    """

    db = _get_db_from_config(config)
    extraction = state.get("extraction", {})

    lookup_context = lookup_records(
        db=db,
        extraction=extraction,
    )

    return {
        "lookup_context": lookup_context,
    }


def reasoning_node(state: AgentState) -> AgentState:
    """
    Node 3:
    LLM reasons over user message + extraction + DB results + long-term memory.

    Long-term memory is injected only into reasoning, not extraction,
    to avoid confusing entity extraction with old context.
    """

    user_message = state.get("user_message", "")
    memory_context = state.get("long_term_memory_context", "")

    if memory_context and "No relevant long-term memories found" not in memory_context:
        reasoning_user_message = f"""
Long-term memory context:
{memory_context}

Current user request:
{user_message}

Use the long-term memory only when it helps resolve references like:
- same person
- same company
- that lead
- previous client
- the one we discussed before

Do not override clear information from the current user request.

If memories conflict, prefer:
1. approval_decision memories over pending memories
2. executed or approved outcomes over older pending approval states
3. newer memory records over older ones

Do not say an activity or update is pending if a later memory says it was approved or executed successfully.
""".strip()
    else:
        reasoning_user_message = user_message

    reasoning = reason_over_results(
        user_message=reasoning_user_message,
        extraction=state.get("extraction", {}),
        lookup_context=state.get("lookup_context", {}),
    )

    return {
        "reasoning": reasoning,
    }


def judge_proposal_node(state: AgentState) -> AgentState:
    """
    LLM-as-a-Judge checks proposed_update before rule-based validation.
    If the judge rejects it, we stop and ask for clarification.
    We do NOT auto-repair unsafe CRM updates.
    """

    reasoning = state.get("reasoning", {}) or {}

    judge_result = judge_proposed_update(
        user_message=state.get("user_message", ""),
        extraction=state.get("extraction", {}) or {},
        lookup_context=state.get("lookup_context", {}) or {},
        reasoning=reasoning,
    )

    notes = (
        str(reasoning.get("reasoning_notes", ""))
        + f" LLM Judge verdict: {judge_result.get('verdict')} "
        + f"(score={judge_result.get('score')})."
    )

    # If judge says do not continue, stop before validation/pending approval.
    if not judge_result.get("pass_to_validator"):
        issues = judge_result.get("issues") or []

        assistant_message = (
            judge_result.get("warning")
            or "I cannot safely prepare this CRM update yet. Could you clarify the correct CRM update?"
        )

        updated_reasoning = {
            **reasoning,
            "judge_result": judge_result,
            "decision": "ask_clarification",
            "assistant_message": assistant_message,
            "needs_approval": False,
            "missing_fields": issues,
            "reasoning_notes": notes,
        }

        return {
            "judge_result": judge_result,
            "reasoning": updated_reasoning,
        }

    updated_reasoning = {
        **reasoning,
        "judge_result": judge_result,
        "reasoning_notes": notes,
    }

    return {
        "judge_result": judge_result,
        "reasoning": updated_reasoning,
    }


def validate_proposal_node(state: AgentState) -> AgentState:
    """
    Validate proposed_update before creating pending approval.
    If validation fails, ask clarification directly.
    No repair agent is used.
    """

    reasoning = state.get("reasoning", {}) or {}
    proposed_update = reasoning.get("proposed_update", {}) or {}

    validation_result = validate_proposed_update(proposed_update)

    if not validation_result.get("success"):
        error_messages = [
            error.get("message")
            for error in validation_result.get("errors", [])
            if isinstance(error, dict)
        ]

        updated_reasoning = {
            **reasoning,
            "decision": "ask_clarification",
            "assistant_message": "I need more information before I can prepare this CRM update for approval. Could you clarify the missing or invalid information?",
            "needs_approval": False,
            "missing_fields": error_messages,
        }

        return {
            "validation_result": validation_result,
            "reasoning": updated_reasoning,
        }

    return {
        "validation_result": validation_result,
    }


def create_pending_node(state: AgentState, config) -> AgentState:
    """
    Create pending update for approval.
    No CRM write is executed here.
    """

    db = _get_db_from_config(config)
    reasoning = state.get("reasoning", {}) or {}

    proposed_update = reasoning.get("proposed_update", {}) or {}

    if not proposed_update:
        return {
            "pending_result": {
                "success": False,
                "message": "No proposed_update was provided by the reasoning agent.",
            }
        }

    pending_result = create_pending_update(
        db=db,
        user_input=state.get("original_user_message")
        or state.get("raw_user_message")
        or state.get("user_message", ""),
        detected_intent=reasoning.get("detected_intent", "crm_update"),
        extracted_data=reasoning.get("extracted_data", state.get("extraction", {})),
        proposed_update=proposed_update,
    )

    return {
        "pending_result": pending_result,
    }


def read_node(state: AgentState, config) -> AgentState:
    """
    Node 4B:
    Run read tools when the request is read-only.
    """

    db = _get_db_from_config(config)
    extraction = state.get("extraction", {}) or {}
    reasoning = state.get("reasoning", {}) or {}
    lookup_context = state.get("lookup_context", {}) or {}

    entities = extraction.get("entities", {}) or {}
    extracted_data = reasoning.get("extracted_data", {}) or {}
    proposed_update = reasoning.get("proposed_update", {}) or {}

    user_message = state.get("user_message", "").lower()
    detected_intent = reasoning.get("detected_intent", "").lower()

    lead_id = (
        extracted_data.get("lead_id")
        or proposed_update.get("lead_id")
        or entities.get("lead_id")
    )

    contact_id = (
        extracted_data.get("contact_id")
        or proposed_update.get("contact_id")
        or entities.get("contact_id")
    )

    company_id = (
        extracted_data.get("company_id")
        or proposed_update.get("company_id")
        or entities.get("company_id")
    )

    # ------------------------------------------------------------
    # Fallback IDs from lookup results
    # ------------------------------------------------------------

    lead_lookup = lookup_context.get("lead_lookup", {}) or {}
    leads = lead_lookup.get("leads", []) or []

    contact_lookup = lookup_context.get("contact_lookup", {}) or {}
    contacts = contact_lookup.get("contacts", []) or []

    company_lookup = lookup_context.get("company_lookup", {}) or {}
    companies = company_lookup.get("companies", []) or []

    if not lead_id and len(leads) == 1:
        lead_id = leads[0].get("lead_id")

    if not contact_id and len(contacts) == 1:
        contact_id = contacts[0].get("contact_id")

    if not company_id and len(companies) == 1:
        company_id = companies[0].get("company_id")

    # ------------------------------------------------------------
    # Determine read type
    # ------------------------------------------------------------

    wants_history = (
        "history" in user_message
        or "lead_history" in detected_intent
        or "get_lead_history" in detected_intent
    )

    wants_contact_details = (
        "contact details" in user_message
        or "contact_detail" in detected_intent
        or "get_contact_details" in detected_intent
    )

    wants_company_details = (
        "company details" in user_message
        or "company_detail" in detected_intent
        or "get_company_details" in detected_intent
    )

    # ------------------------------------------------------------
    # Lead history
    # ------------------------------------------------------------

    if wants_history:
        if lead_id:
            read_result = get_lead_history(
                db=db,
                lead_id=lead_id,
            )

            return {
                "read_result": read_result,
            }

        return {
            "read_result": {
                "success": True,
                "message": "Lead history requires selecting a specific lead.",
                "lookup_context": lookup_context,
            }
        }

    # ------------------------------------------------------------
    # Contact details
    # ------------------------------------------------------------

    if wants_contact_details:
        if contact_id:
            return {
                "read_result": get_contact_details(
                    db=db,
                    contact_id=contact_id,
                )
            }

        return {
            "read_result": {
                "success": True,
                "message": "Contact details require selecting a specific contact.",
                "lookup_context": lookup_context,
            }
        }

    # ------------------------------------------------------------
    # Company details
    # ------------------------------------------------------------

    if wants_company_details:
        if company_id:
            return {
                "read_result": get_company_details(
                    db=db,
                    company_id=company_id,
                )
            }

        return {
            "read_result": {
                "success": True,
                "message": "Company details require selecting a specific company.",
                "lookup_context": lookup_context,
            }
        }

    # ------------------------------------------------------------
    # Default read result
    # ------------------------------------------------------------

    return {
        "read_result": {
            "success": True,
            "message": "CRM lookup completed.",
            "lookup_context": lookup_context,
        }
    }


def report_node(state: AgentState, config) -> AgentState:
    """
    Run advanced reporting analytics agent.
    """

    db = _get_db_from_config(config)

    extraction = state.get("extraction", {}) or {}
    reasoning = state.get("reasoning", {}) or {}
    user_message = state.get("user_message", "")

    extracted_data = {}

    if isinstance(extraction, dict):
        extracted_data.update(extraction)

    if isinstance(reasoning.get("extracted_data"), dict):
        extracted_data.update(reasoning.get("extracted_data"))

    if isinstance(reasoning.get("proposed_update"), dict):
        extracted_data.update(reasoning.get("proposed_update"))

    detected_intent = reasoning.get("detected_intent")
    if detected_intent:
        extracted_data["intent"] = detected_intent

    # Detect report type from message if the agent did not provide it clearly
    lower_message = user_message.lower()

    if "dashboard" in lower_message or "kpi" in lower_message:
        extracted_data["report_type"] = "dashboard"
    elif "conversion" in lower_message:
        extracted_data["report_type"] = "conversion"
    elif "source" in lower_message:
        extracted_data["report_type"] = "lead_sources"
    elif "deal pipeline" in lower_message:
        extracted_data["report_type"] = "deal_pipeline"
    elif "pipeline" in lower_message:
        extracted_data["report_type"] = "pipeline"

    report_result = handle_reporting_request(
        db=db,
        extracted_data=extracted_data,
        user_message=user_message,
    )

    return {
        "report_result": report_result,
    }


def enrichment_node(state: AgentState) -> AgentState:
    """
    Node 4D:
    Run external enrichment tool.
    This does not write to CRM.
    """

    extraction = state.get("extraction", {}) or {}
    reasoning = state.get("reasoning", {}) or {}

    entities = extraction.get("entities", {}) or {}

    company_name = (
        reasoning.get("extracted_data", {}).get("company_name")
        or reasoning.get("proposed_update", {}).get("company_name")
        or entities.get("company_name")
    )

    if not company_name:
        return {
            "enrichment_result": {
                "success": False,
                "message": "company_name is required for enrichment.",
            }
        }

    enrichment_result = scrape_company_website(
        company_name=company_name,
        max_pages=5,
    )

    return {
        "enrichment_result": enrichment_result,
    }


def final_node(state: AgentState) -> AgentState:
    """
    Final node:
    Build UI/API response.
    """

    final_response = build_final_response(state)

    return {
        "final_response": final_response,
    }


def memory_update_node(state: AgentState, config) -> AgentState:
    """
    Save or clear short-term memory at the end of the graph run.

    Also saves every completed agent turn into hybrid long-term memory:
    - PostgreSQL table: long_term_memory
    - FAISS vector store: semantic search index
    """

    final_response = dict(state.get("final_response", {}) or {})

    response_type = final_response.get("type")
    requires_user_input = bool(final_response.get("requires_user_input"))
    needs_approval = bool(final_response.get("needs_approval"))

    should_store_pending_context = (
        response_type in {"clarification", "ask_clarification", "choices"}
        and requires_user_input
        and not needs_approval
    )

    pending_context = None

    if should_store_pending_context:
        reasoning = state.get("reasoning", {}) or {}

        pending_context = {
            "response_type": response_type,
            "original_user_message": (
                state.get("original_user_message")
                or state.get("raw_user_message")
                or state.get("user_message", "")
            ),
            "effective_user_message": state.get("user_message", ""),
            "message": final_response.get("message"),
            "clarification_question": (
                final_response.get("clarification_question")
                or final_response.get("message")
            ),
            "choices": _json_safe(
                final_response.get("choices") or reasoning.get("choices") or []
            ),
            "missing_fields": _json_safe(
                final_response.get("missing_fields")
                or reasoning.get("missing_fields")
                or []
            ),
            "extraction": _json_safe(state.get("extraction", {}) or {}),
            "lookup_context": _json_safe(state.get("lookup_context", {}) or {}),
            "reasoning": _json_safe(reasoning),
        }

    final_response["used_short_term_memory"] = bool(state.get("used_short_term_memory"))

    # Save this completed turn into long-term memory DB + FAISS.
    # This is append-only: each useful turn becomes a new memory row and vector.
    try:
        db = _get_db_from_config(config)
        configurable = (config or {}).get("configurable", {}) or {}
        session_key = configurable.get("thread_id") or "dealforge-default-session"

        result_data = {
            "final_response": _json_safe(final_response),
            "reasoning": _json_safe(state.get("reasoning", {}) or {}),
            "lookup_context": _json_safe(state.get("lookup_context", {}) or {}),
            "pending_result": _json_safe(state.get("pending_result", {}) or {}),
            "read_result": _json_safe(state.get("read_result", {}) or {}),
            "report_result": _json_safe(state.get("report_result", {}) or {}),
            "enrichment_result": _json_safe(state.get("enrichment_result", {}) or {}),
        }

        extracted_data = _json_safe(state.get("extraction", {}) or {})

        save_turn_as_memory(
            db=db,
            session_id=session_key,
            user_message=state.get("raw_user_message") or state.get("user_message", ""),
            agent_response=final_response.get("message", ""),
            extracted_data=extracted_data,
            result_data=result_data,
        )

    except Exception as e:
        # Memory should never break the main CRM workflow.
        print("Long-term memory save failed:", e)

    return {
        "pending_context": pending_context,
        "final_response": final_response,
    }


# ============================================================
# ROUTING
# ============================================================


def route_after_reasoning(state: AgentState) -> str:
    """
    Route based on reasoning decision.
    Adds deterministic safety rules so read/history does not become report.
    """

    reasoning = state.get("reasoning", {}) or {}
    extraction = state.get("extraction", {}) or {}

    decision = reasoning.get("decision")
    request_type = extraction.get("request_type")

    user_message = state.get("user_message", "").lower()

    possible_actions = extraction.get("possible_actions", []) or []
    action_types = [
        action.get("action_type", "")
        for action in possible_actions
        if isinstance(action, dict)
    ]

    # ------------------------------------------------------------
    # Report override
    # ------------------------------------------------------------

    report_keywords = [
        "pipeline report",
        "sales dashboard",
        "dashboard",
        "kpi",
        "conversion report",
        "lead source report",
    ]

    if request_type == "report" or any(
        keyword in user_message for keyword in report_keywords
    ):
        return "report"

    # ------------------------------------------------------------
    # Read override
    # ------------------------------------------------------------

    read_keywords = [
        "history",
        "lead history",
        "contact details",
        "company details",
        "deal details",
        "show me the history",
    ]

    read_actions = [
        "get_lead_history",
        "get_contact_details",
        "get_company_details",
    ]

    if (
        request_type == "read"
        or any(keyword in user_message for keyword in read_keywords)
        or any(action in read_actions for action in action_types)
    ):
        return "read"

    # ------------------------------------------------------------
    # Normal LLM decision routing
    # ------------------------------------------------------------

    if decision == "prepare_pending_update":
        return "judge_proposal"

    if decision == "return_read_result":
        return "read"

    if decision == "return_report":
        return "report"

    if decision == "run_enrichment":
        return "enrichment"

    return "final"


def route_after_judge(state: AgentState) -> str:
    judge_result = state.get("judge_result", {}) or {}

    if judge_result.get("pass_to_validator"):
        return "validate_proposal"

    return "final"


def route_after_validation(state: AgentState) -> str:
    """
    Route after proposal validation.
    """

    validation_result = state.get("validation_result", {}) or {}

    if validation_result.get("success"):
        return "create_pending"

    return "final"


# ============================================================
# GRAPH BUILDER
# ============================================================


def build_agent_graph():
    workflow = StateGraph(AgentState)

    workflow.add_node("memory_prepare", memory_prepare_node)

    workflow.add_node("extract", extract_node)
    workflow.add_node("lookup", lookup_node)
    workflow.add_node("reason", reasoning_node)

    workflow.add_node("judge_proposal", judge_proposal_node)

    workflow.add_node("validate_proposal", validate_proposal_node)

    workflow.add_node("create_pending", create_pending_node)
    workflow.add_node("read", read_node)
    workflow.add_node("report", report_node)
    workflow.add_node("enrichment", enrichment_node)

    workflow.add_node("final", final_node)
    workflow.add_node("memory_update", memory_update_node)

    workflow.set_entry_point("memory_prepare")

    workflow.add_edge("memory_prepare", "extract")
    workflow.add_edge("extract", "lookup")
    workflow.add_edge("lookup", "reason")

    workflow.add_conditional_edges(
        "reason",
        route_after_reasoning,
        {
            "judge_proposal": "judge_proposal",
            "validate_proposal": "validate_proposal",
            "read": "read",
            "report": "report",
            "enrichment": "enrichment",
            "final": "final",
        },
    )

    workflow.add_conditional_edges(
        "judge_proposal",
        route_after_judge,
        {
            "validate_proposal": "validate_proposal",
            "final": "final",
        },
    )

    workflow.add_conditional_edges(
        "validate_proposal",
        route_after_validation,
        {
            "create_pending": "create_pending",
            "final": "final",
        },
    )

    workflow.add_edge("create_pending", "final")
    workflow.add_edge("read", "final")
    workflow.add_edge("report", "final")
    workflow.add_edge("enrichment", "final")

    workflow.add_edge("final", "memory_update")
    workflow.add_edge("memory_update", END)

    checkpointer = InMemorySaver()

    return workflow.compile(checkpointer=checkpointer)


agent_graph = build_agent_graph()


def run_agent_message(
    db: Session,
    user_message: str,
    session_id: str | None = None,
) -> dict:
    """
    Main function to run the CRM agent graph.

    Short-term memory:
    - Managed by LangGraph checkpointer.
    - Uses session_id as thread_id.
    - Does not store memory in database.
    - Memory is lost when backend restarts.
    """

    session_key = (session_id or "dealforge-default-session").strip()

    initial_state = {
        "user_message": user_message,
    }

    config = {
        "configurable": {
            "thread_id": session_key,
            "db": db,
        }
    }

    result = agent_graph.invoke(
        initial_state,
        config=config,
    )

    final_response = result.get("final_response", result)

    final_response["session_id"] = session_key

    return final_response
