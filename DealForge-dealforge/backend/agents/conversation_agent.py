# backend/agents/conversation_agent.py

import json
import os
import re
from datetime import datetime

from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI


load_dotenv()


EXTRACTION_SYSTEM_PROMPT = """
You are the CRM message extraction agent for DealForge.

Your job is ONLY to understand the user's message and extract structured information.
Do not execute tools.
Do not update the database.
Do not ask the user questions here.
Do not make final decisions.

You must return JSON only.

The CRM has these main tables:
- companies
- contacts
- leads
- deals
- activities
- tasks
- stage_history

Possible request_type values:
- crm_update
- read
- report
- enrichment
- unsupported

Possible action_type values:
- create_company
- update_company
- create_contact
- update_contact
- create_lead
- update_lead_fields
- update_lead_status
- create_deal
- update_deal_fields
- update_deal_stage
- create_activity
- create_follow_up_task
- update_task
- get_lead_history
- get_contact_details
- get_company_details
- pipeline_report
- sales_dashboard
- enrich_company
- unsupported

Important rules:
- A single user message can contain multiple actions.
- If the user says something indirect, infer possible CRM meaning.
  Example: "Ahmed seems like a good fit" may imply update_lead_status = Qualified.
- If uncertain, keep confidence lower and explain uncertainty in reasoning_notes.
- Do not invent emails, phones, company website, budget, priority, or due date.
- If a relative date is clear, convert it to YYYY-MM-DD using today's date.
- If a relative date is unclear, keep due_date as null and keep due_date_text.
- Use English JSON keys.
- Preserve the original user meaning.

Return JSON with this exact structure:

{
  "request_type": "crm_update | read | report | enrichment | unsupported",
  "language": "en | ar | mixed",
  "entities": {
    "company_name": null,
    "contact_name": null,
    "lead_id": null,
    "company_id": null,
    "contact_id": null,
    "deal_id": null,
    "task_id": null
  },
  "possible_actions": [
    {
      "action_type": "string",
      "target_table": "string",
      "confidence": 0.0,
      "data": {},
      "reason": "string"
    }
  ],
  "needs_db_lookup": true,
  "reasoning_notes": "short explanation"
}
"""


def get_llm():
    """
    Create the LLM client.
    """
    model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    return ChatOpenAI(
        model=model_name,
        temperature=0,
    )


def extract_json_object(text: str) -> dict:
    """
    Extract JSON object from LLM response.
    Handles ```json blocks too.
    """
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


def build_fallback_extraction(user_message: str) -> dict:
    """
    Fallback if LLM parsing fails.
    """
    return {
        "request_type": "unsupported",
        "language": "mixed",
        "entities": {
            "company_name": None,
            "contact_name": None,
            "lead_id": None,
            "company_id": None,
            "contact_id": None,
            "deal_id": None,
            "task_id": None,
        },
        "possible_actions": [
            {
                "action_type": "unsupported",
                "target_table": "none",
                "confidence": 0.0,
                "data": {},
                "reason": "Could not parse the user message.",
            }
        ],
        "needs_db_lookup": False,
        "reasoning_notes": "LLM extraction failed.",
        "raw_user_message": user_message,
    }


def normalize_extraction(result: dict, user_message: str) -> dict:
    """
    Ensure required keys exist.
    """
    if not isinstance(result, dict):
        return build_fallback_extraction(user_message)

    result.setdefault("request_type", "unsupported")
    result.setdefault("language", "mixed")
    result.setdefault("entities", {})
    result.setdefault("possible_actions", [])
    result.setdefault("needs_db_lookup", True)
    result.setdefault("reasoning_notes", "")

    entities = result["entities"]

    default_entities = {
        "company_name": None,
        "contact_name": None,
        "lead_id": None,
        "company_id": None,
        "contact_id": None,
        "deal_id": None,
        "task_id": None,
    }

    for key, value in default_entities.items():
        entities.setdefault(key, value)

    if not isinstance(result["possible_actions"], list):
        result["possible_actions"] = []

    result["raw_user_message"] = user_message

    return result


def extract_user_message(user_message: str) -> dict:
    """
    Use LLM to extract intent, entities, and possible actions from user message.
    """

    if not user_message or not user_message.strip():
        return build_fallback_extraction(user_message)

    today = datetime.now().date().isoformat()

    human_prompt = f"""
Today's date is: {today}

User message:
{user_message}

Extract the CRM meaning as JSON only.
"""

    try:
        llm = get_llm()

        response = llm.invoke([
            SystemMessage(content=EXTRACTION_SYSTEM_PROMPT),
            HumanMessage(content=human_prompt),
        ])

        parsed = extract_json_object(response.content)

        return normalize_extraction(parsed, user_message)

    except Exception as error:
        fallback = build_fallback_extraction(user_message)
        fallback["error"] = str(error)
        return fallback