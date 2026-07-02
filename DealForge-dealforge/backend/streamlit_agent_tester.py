# streamlit_agent_tester.py

import json
import time
import uuid
from datetime import datetime
from typing import Any

import pandas as pd
import requests
import streamlit as st

# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="DealForge Chat Tester",
    page_icon="💬",
    layout="wide",
)

DEFAULT_API_BASE = "http://127.0.0.1:8000"


# ============================================================
# SESSION STATE
# ============================================================

if "api_base" not in st.session_state:
    st.session_state.api_base = DEFAULT_API_BASE

if "session_id" not in st.session_state:
    st.session_state.session_id = f"streamlit-{uuid.uuid4().hex[:8]}"

if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": (
                "DealForge is ready. Send a natural CRM message. "
                "If a database update is needed, I will ask for approval first."
            ),
            "result": None,
            "time": datetime.now().isoformat(),
        }
    ]

if "pending_clarification" not in st.session_state:
    st.session_state.pending_clarification = None

if "decided_pending_ids" not in st.session_state:
    st.session_state.decided_pending_ids = set()

if "last_user_request" not in st.session_state:
    st.session_state.last_user_request = None


# ============================================================
# API HELPERS
# ============================================================


def api_url(path: str) -> str:
    return st.session_state.api_base.rstrip("/") + path


def api_get(path: str):
    response = requests.get(api_url(path), timeout=30)
    response.raise_for_status()
    return response.json()


def api_post(path: str, payload: dict, timeout: int = 120):
    response = requests.post(api_url(path), json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


def call_agent(user_text: str):
    """
    If the previous agent response was a clarification, combine the user's answer
    with the original request so we can test multi-turn behavior even if backend
    session memory is still simple.
    """

    backend_message = user_text

    if st.session_state.pending_clarification:
        context = st.session_state.pending_clarification

        backend_message = f"""
Original user request:
{context.get("original_request")}

Clarification question:
{context.get("question")}

User clarification answer:
{user_text}

Continue the CRM request using the clarification answer.
""".strip()

    start = time.perf_counter()

    result = api_post(
        "/agent/chat",
        {
            "session_id": st.session_state.session_id,
            "message": backend_message,
        },
    )

    elapsed = round(time.perf_counter() - start, 2)

    return result, elapsed, backend_message


def send_decision(pending_id: int, decision: str, edited_data: dict | None = None):
    payload = {
        "pending_id": pending_id,
        "decision": decision,
        "decided_by": "streamlit_tester",
        "session_id": st.session_state.session_id,
    }

    if edited_data is not None:
        payload["edited_data"] = edited_data

    return api_post("/agent/decision", payload)


# ============================================================
# DISPLAY HELPERS
# ============================================================


def pretty_key(key: str) -> str:
    return str(key).replace("_", " ").title()


def get_response_type(result: dict | None) -> str:
    if not result:
        return "message"

    return (
        result.get("type")
        or result.get("decision")
        or result.get("route_to")
        or "message"
    )


def get_agent_message(result: dict | None) -> str:
    if not result:
        return ""

    return (
        result.get("clarification_question")
        or result.get("message")
        or result.get("assistant_message")
        or "Done."
    )


def is_approval_required(result: dict | None) -> bool:
    if not result:
        return False

    return bool(
        result.get("pending_id")
        and (
            result.get("type") == "approval_required"
            or result.get("needs_approval")
            or result.get("requires_approval")
        )
    )


def is_clarification(result: dict | None) -> bool:
    if not result:
        return False

    response_type = get_response_type(result)

    return response_type in ["clarification", "ask_clarification"]


def safe_json(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)


def convert_edited_value(original_value: Any, edited_value: Any):
    if isinstance(original_value, bool):
        return bool(edited_value)

    if isinstance(original_value, int) and not isinstance(original_value, bool):
        try:
            return int(edited_value)
        except Exception:
            return edited_value

    if isinstance(original_value, float):
        try:
            return float(edited_value)
        except Exception:
            return edited_value

    return edited_value


def append_message(role: str, content: str, result: dict | None = None):
    st.session_state.messages.append(
        {
            "role": role,
            "content": content,
            "result": result,
            "time": datetime.now().isoformat(),
        }
    )


def handle_agent_result(
    user_text: str, result: dict, elapsed: float, backend_message: str
):
    response_type = get_response_type(result)
    content = get_agent_message(result)

    if is_clarification(result):
        question = get_agent_message(result)

        st.session_state.pending_clarification = {
            "original_request": st.session_state.last_user_request or user_text,
            "question": question,
        }

        append_message(
            "assistant",
            f"{question}\n\n_Time: {elapsed} seconds_",
            result,
        )
        return

    st.session_state.pending_clarification = None

    append_message(
        "assistant",
        f"{content}\n\n_Time: {elapsed} seconds_",
        result,
    )


# ============================================================
# APPROVAL CARD
# ============================================================


def render_proposed_actions(result: dict):
    proposed_actions = result.get("proposed_actions") or []

    if proposed_actions:
        st.write("**Proposed actions**")
        st.dataframe(
            pd.DataFrame(proposed_actions),
            use_container_width=True,
            hide_index=True,
        )


def render_proposed_update(result: dict):
    proposed_update = result.get("proposed_update") or {}

    if proposed_update:
        st.write("**Proposed update**")
        st.json(proposed_update)


def render_edit_form(result: dict, message_index: int):
    pending_id = result.get("pending_id")
    proposed_update = result.get("proposed_update") or {}

    if not proposed_update:
        st.info("No proposed_update available to edit.")
        return

    with st.expander("✏️ Edit before approval", expanded=False):
        st.caption("Edit the fields below, then submit the edited update.")

        with st.form(f"edit_form_{pending_id}_{message_index}"):
            edited_data = {}

            for key, value in proposed_update.items():
                label = pretty_key(key)
                widget_key = f"edit_{pending_id}_{message_index}_{key}"

                if isinstance(value, bool):
                    edited_data[key] = st.checkbox(
                        label,
                        value=value,
                        key=widget_key,
                    )

                elif isinstance(value, (dict, list)):
                    raw_text = st.text_area(
                        label,
                        value=safe_json(value),
                        key=widget_key,
                        height=120,
                    )

                    try:
                        edited_data[key] = json.loads(raw_text)
                    except Exception:
                        edited_data[key] = raw_text

                elif key in ["activity_notes", "last_summary", "description"]:
                    edited_value = st.text_area(
                        label,
                        value="" if value is None else str(value),
                        key=widget_key,
                        height=90,
                    )
                    edited_data[key] = convert_edited_value(value, edited_value)

                else:
                    edited_value = st.text_input(
                        label,
                        value="" if value is None else str(value),
                        key=widget_key,
                    )
                    edited_data[key] = convert_edited_value(value, edited_value)

            submit_edit = st.form_submit_button(
                "Submit Edited Update",
                type="primary",
                use_container_width=True,
            )

        if submit_edit:
            try:
                decision_result = send_decision(
                    pending_id=pending_id,
                    decision="edit",
                    edited_data=edited_data,
                )

                st.session_state.decided_pending_ids.add(pending_id)

                append_message(
                    "assistant",
                    decision_result.get(
                        "message",
                        "Edited update submitted successfully.",
                    ),
                    decision_result,
                )

                st.rerun()

            except Exception as error:
                st.error(f"Edit failed: {error}")


def render_approval_controls(result: dict, message_index: int):
    pending_id = result.get("pending_id")

    if not pending_id:
        return

    if pending_id in st.session_state.decided_pending_ids:
        st.success(f"Decision already submitted for pending #{pending_id}.")
        return

    st.write("**Approval decision**")

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button(
            "Approve",
            type="primary",
            key=f"approve_{pending_id}_{message_index}",
            use_container_width=True,
        ):
            try:
                decision_result = send_decision(
                    pending_id=pending_id,
                    decision="approve",
                )

                st.session_state.decided_pending_ids.add(pending_id)

                append_message(
                    "assistant",
                    decision_result.get(
                        "message",
                        "Approved and executed successfully.",
                    ),
                    decision_result,
                )

                st.rerun()

            except Exception as error:
                st.error(f"Approval failed: {error}")

    with col2:
        if st.button(
            "Edit",
            key=f"edit_open_{pending_id}_{message_index}",
            use_container_width=True,
        ):
            st.session_state[f"show_edit_{pending_id}_{message_index}"] = True

    with col3:
        if st.button(
            "Reject",
            key=f"reject_{pending_id}_{message_index}",
            use_container_width=True,
        ):
            try:
                decision_result = send_decision(
                    pending_id=pending_id,
                    decision="cancel",
                )

                st.session_state.decided_pending_ids.add(pending_id)

                append_message(
                    "assistant",
                    decision_result.get(
                        "message",
                        "Rejected. No database update was executed.",
                    ),
                    decision_result,
                )

                st.rerun()

            except Exception as error:
                st.error(f"Reject failed: {error}")

    if st.session_state.get(f"show_edit_{pending_id}_{message_index}"):
        render_edit_form(result, message_index)


def render_result_details(result: dict | None, message_index: int):
    if not result:
        return

    response_type = get_response_type(result)

    if is_approval_required(result):
        st.info(
            "This CRM update requires human approval before writing to the database."
        )

        render_proposed_actions(result)
        render_proposed_update(result)
        render_approval_controls(result, message_index)

    elif is_clarification(result):
        st.warning("The agent needs your answer. Reply in the chat input below.")

    elif response_type in ["report", "read_result"]:
        with st.expander("View raw result"):
            st.json(result)

    else:
        if result.get("proposed_update"):
            render_proposed_update(result)

        with st.expander("View raw response"):
            st.json(result)


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.header("Backend")

    st.session_state.api_base = st.text_input(
        "FastAPI Base URL",
        value=st.session_state.api_base,
    )

    if st.button("Health Check", use_container_width=True):
        try:
            health = api_get("/test-db")
            st.success("Backend connected.")
            st.json(health)

        except Exception as error:
            st.error(f"Backend unavailable: {error}")

    st.divider()

    st.header("Quick Scenarios")

    scenario_1 = (
        "I spoke with N C from Zotware today. They asked for a product demo "
        "and pricing details for the Customer Follow-up service. "
        "Please log this activity and create a follow-up task for next Monday."
    )

    scenario_2 = "Give me a pipeline report."

    scenario_3 = "Show me the history for N C from Zotware."

    if st.button("Activity + Task", use_container_width=True):
        st.session_state.scenario_to_send = scenario_1
        st.rerun()

    if st.button("Pipeline Report", use_container_width=True):
        st.session_state.scenario_to_send = scenario_2
        st.rerun()

    if st.button("Lead History", use_container_width=True):
        st.session_state.scenario_to_send = scenario_3
        st.rerun()

    st.divider()

    if st.button("Clear Chat", use_container_width=True):
        st.session_state.messages = [
            {
                "role": "assistant",
                "content": "Chat cleared. Send a new CRM message.",
                "result": None,
                "time": datetime.now().isoformat(),
            }
        ]
        st.session_state.pending_clarification = None
        st.session_state.decided_pending_ids = set()
        st.session_state.last_user_request = None
        st.session_state.session_id = f"streamlit-{uuid.uuid4().hex[:8]}"
        st.rerun()


# ============================================================
# MAIN CHAT UI
# ============================================================

st.title("DealForge Chat Tester")
st.caption("Chat with the agent, review approvals, edit proposals, approve, or reject.")

for index, message in enumerate(st.session_state.messages):
    role = message.get("role", "assistant")
    content = message.get("content", "")
    result = message.get("result")

    with st.chat_message(role):
        st.write(content)
        render_result_details(result, index)


# ============================================================
# SCENARIO AUTO SEND
# ============================================================

if "scenario_to_send" in st.session_state:
    scenario_text = st.session_state.pop("scenario_to_send")

    append_message("user", scenario_text)
    st.session_state.last_user_request = scenario_text

    with st.spinner("Running agent..."):
        try:
            result, elapsed, backend_message = call_agent(scenario_text)
            handle_agent_result(
                user_text=scenario_text,
                result=result,
                elapsed=elapsed,
                backend_message=backend_message,
            )

        except Exception as error:
            append_message(
                "assistant",
                f"Backend request failed: {error}",
                None,
            )

    st.rerun()


# ============================================================
# CHAT INPUT
# ============================================================

placeholder = "Type your CRM message here..."

if st.session_state.pending_clarification:
    placeholder = "Reply with the missing information..."

user_input = st.chat_input(placeholder)

if user_input:
    append_message("user", user_input)

    if not st.session_state.pending_clarification:
        st.session_state.last_user_request = user_input

    with st.spinner("DealForge is thinking..."):
        try:
            result, elapsed, backend_message = call_agent(user_input)

            handle_agent_result(
                user_text=user_input,
                result=result,
                elapsed=elapsed,
                backend_message=backend_message,
            )

        except Exception as error:
            append_message(
                "assistant",
                f"Backend request failed: {error}",
                None,
            )

    st.rerun()
