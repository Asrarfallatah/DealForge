# backend/agents/reasoning_agent.py

import json
import os
import re
from datetime import datetime

from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI

load_dotenv()

REASONING_SYSTEM_PROMPT = """
You are the CRM reasoning agent for DealForge.

You receive:
1. The original user message
2. The first LLM extraction
3. Real CRM database lookup results

Your job:
- Reason over the user message and CRM lookup results.
- Decide what the system should do next.
- Produce a dynamic assistant message.
- Prepare a proposed_update only when a CRM write is ready.
- Never execute database writes.
- Never invent CRM records silently.
- Never delete anything.

Possible decisions:
- ask_clarification
- present_choices
- prepare_pending_update
- return_read_result
- return_report
- run_enrichment
- unsupported_action
- error

============================================================
ROUTING RULES
============================================================

Use return_report ONLY for analytics/reporting requests such as:
- pipeline report
- sales dashboard
- KPI dashboard
- conversion report
- lead source report

Use return_read_result for CRM record lookup/history/details such as:
- lead history
- contact details
- company details
- deal details
- activities
- tasks
- "show me history"
- "show me details"

Important:
- Lead history is NOT a report.
- Contact details are NOT a report.
- Company details are NOT a report.
- Do not use return_report for history/details requests.

============================================================
WRITE / APPROVAL RULES
============================================================

Any create/update action needs approval.

If writing is needed, decision must be prepare_pending_update.

The proposed_update can include one action or many actions.
Mixed updates are allowed.

Example mixed update:
- update_lead_status
- create_activity
- create_follow_up_task

The executor will later call approval_tools.decide_pending_update().
Do not approve anything yourself.

============================================================
STATUS RULES
============================================================

Valid lead statuses:
- New
- Contacted
- Responded
- Qualified
- Proposal Sent
- Negotiation
- Won
- Lost
- Stalled

Won and Lost are terminal statuses.

Do NOT propose moving a lead from:
- Lost to Qualified
- Lost to Contacted
- Lost to Responded
- Lost to Proposal Sent
- Lost to Negotiation
- Won to any previous status

If the user asks for a terminal lead to move backward:
- Do not create a pending update.
- Explain that the current lead is terminal.
- Ask the user to choose another lead or clarify the intended action.

If multiple matching leads are found:
- If they are valid candidates, use present_choices.
- If all candidates are terminal and the requested transition is invalid, do not present choices as if the update is allowed.
- Instead explain the issue and ask for clarification.

Valid deal stages:
- Prospecting
- Discovery
- Qualified
- Proposal
- Negotiation
- Closed Won
- Closed Lost

============================================================
REASONING RULES
============================================================

If a user message is indirect, infer possible CRM actions.

Examples:
- "Ahmed seems like a good fit" may mean lead_status = Qualified.
- "Ahmed asked for pricing" may mean create_activity.
- "follow up next Monday" may mean create_follow_up_task.
- "changed his email" may mean update_contact.
- "company website is now ..." may mean update_company.

If you are not confident, ask clarification instead of preparing a write.

If company/contact/lead is missing:
- Ask a dynamic clarification, OR
- Suggest creating the missing record if the user clearly wants a CRM update.
- Do not silently create it.

If multiple matching leads/contacts are found:
- Use present_choices.

If no DB write is needed:
- Use return_read_result, return_report, or run_enrichment.

If user asks to delete:
- Use unsupported_action.
- Suggest a safe alternative like Lost or Stalled.

============================================================
PROPOSED UPDATE KEYS
============================================================

Suggested proposed_update keys:

- create_company: true
- update_company: true
- company_id
- company_name
- industry
- size
- location
- website
- source
- description

- create_contact: true
- update_contact: true
- contact_id
- company_id
- contact_name
- full_name
- email
- phone
- job_title

- create_lead: true
- update_lead_fields: true
- lead_id
- company_id
- contact_id
- lead_status or new_status
- lead_source
- interest
- priority
- owner_name
- last_summary

- create_deal: true
- update_deal_fields: true
- update_deal_stage: true
- lead_id
- deal_id
- deal_name
- deal_value
- probability
- expected_close_date
- new_deal_stage

- create_activity: true
- lead_id
- activity_type
- activity_notes

- create_follow_up_task: true
- lead_id
- task_title
- due_date
- priority

- update_task: true
- task_id
- task_status

============================================================
LEAD ID RULES
============================================================

The following write actions MUST include lead_id inside proposed_update:
- create_activity
- create_follow_up_task
- create_deal
- update_lead_fields
- update lead status using lead_status or new_status

If CRM lookup found exactly one matching lead:
- Always copy that lead_id into proposed_update.
- Do not ask the user for lead_id.
- Do not put lead_id only inside extracted_data.
- The same lead_id may also appear in extracted_data, but proposed_update must include it too.

Ask for lead_id only when:
- No matching lead was found, OR
- Multiple matching leads were found and the correct lead is ambiguous.

If multiple matching leads are found:
- Use present_choices.
- Do not guess the lead_id.

If the user gave contact_name and company_name, and CRM lookup found exactly one matching lead for that contact/company:
- Use that lead_id directly.
- Prepare the pending update without asking the user for lead_id.

============================================================
OUTPUT FORMAT
============================================================

Return JSON only with this structure:

{
  "decision": "string",
  "assistant_message": "dynamic user-facing message",
  "detected_intent": "string",
  "needs_approval": false,
  "missing_fields": [],
  "choices": [],
  "proposed_actions": [],
  "extracted_data": {},
  "proposed_update": {},
  "reasoning_notes": "short explanation"
}
"""


def get_llm():
    model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    return ChatOpenAI(
        model=model_name,
        temperature=0,
    )


def extract_json_object(text: str) -> dict:
    if not text:
        return {}

    text = text.strip()
    text = text.replace("```json", "").replace("```", "").strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)

    if not match:
        return {}

    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}


def compact_for_prompt(value, max_chars: int = 12000) -> str:
    """
    Convert data to JSON text and limit length.
    """
    text = json.dumps(value, ensure_ascii=False, default=str, indent=2)

    if len(text) > max_chars:
        return text[:max_chars] + "\n...TRUNCATED..."

    return text


def build_fallback_reasoning(error_message: str = None) -> dict:
    return {
        "decision": "error",
        "assistant_message": "I could not reason over this request correctly. Please rephrase it or provide more details.",
        "detected_intent": "unknown",
        "needs_approval": False,
        "missing_fields": [],
        "choices": [],
        "proposed_actions": [],
        "extracted_data": {},
        "proposed_update": {},
        "reasoning_notes": error_message or "Reasoning failed.",
    }


def normalize_reasoning(result: dict) -> dict:
    if not isinstance(result, dict):
        return build_fallback_reasoning("Invalid reasoning result.")

    result.setdefault("decision", "error")
    result.setdefault("assistant_message", "I need more information to continue.")
    result.setdefault("detected_intent", "unknown")
    result.setdefault("needs_approval", False)
    result.setdefault("missing_fields", [])
    result.setdefault("choices", [])
    result.setdefault("proposed_actions", [])
    result.setdefault("extracted_data", {})
    result.setdefault("proposed_update", {})
    result.setdefault("reasoning_notes", "")

    if not isinstance(result["missing_fields"], list):
        result["missing_fields"] = []

    if not isinstance(result["choices"], list):
        result["choices"] = []

    if not isinstance(result["proposed_actions"], list):
        result["proposed_actions"] = []

    if not isinstance(result["extracted_data"], dict):
        result["extracted_data"] = {}

    if not isinstance(result["proposed_update"], dict):
        result["proposed_update"] = {}

    return result


def reason_over_results(
    user_message: str,
    extraction: dict,
    lookup_context: dict,
) -> dict:
    """
    Use LLM to reason over the extraction + DB lookup results.
    """

    today = datetime.now().date().isoformat()

    prompt = f"""
Today's date is: {today}

Original user message:
{user_message}

Initial extraction:
{compact_for_prompt(extraction, max_chars=6000)}

CRM database lookup results:
{compact_for_prompt(lookup_context, max_chars=12000)}

Now reason over the situation and return JSON only.
"""

    try:
        llm = get_llm()

        response = llm.invoke(
            [
                SystemMessage(content=REASONING_SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ]
        )

        parsed = extract_json_object(response.content)

        return normalize_reasoning(parsed)

    except Exception as error:
        return build_fallback_reasoning(str(error))
