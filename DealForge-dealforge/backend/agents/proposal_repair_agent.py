# backend/agents/proposal_repair_agent.py

import json
import os
import re
from datetime import datetime

from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI


load_dotenv()


PROPOSAL_REPAIR_SYSTEM_PROMPT = """
You are the Proposal Repair Agent for DealForge CRM.

You receive:
1. Original user message
2. Existing extraction
3. Database lookup context
4. Existing reasoning result
5. Validation errors
6. Current incomplete proposed_update

Your job:
- Repair only missing required fields in proposed_update.
- Use only information that can be inferred from the original user message, extraction, or lookup context.
- Do not invent emails, phone numbers, websites, deal values, budgets, people, company details, or due dates.
- Do not add unrelated CRM actions.
- Do not remove existing valid fields.
- Do not execute tools.
- Do not approve anything.
- Do not update the database.

Important:
- If a required field can be reasonably inferred from the user's message, fill it.
- If a required field cannot be inferred, return can_repair false and ask for clarification.
- Keep repaired text concise and business-friendly.

General repair rules:
- For create_activity:
  - activity_notes should summarize the event/action mentioned by the user.
  - activity_type should be a short category if missing, such as "Note", "Call", "Email", "Meeting", "Demo Request", "Pricing Request", or "Customer Request".
- For create_follow_up_task:
  - task_title should be a short clear title based on the user's requested follow-up.
  - due_date should only be included if the user gave a date or a clearly inferable relative date.
- For create_company:
  - company_name can be filled only if the user mentioned the company name.
- For create_contact:
  - contact_name/full_name can be filled only if the user mentioned the person name.
- For update fields:
  - fill only fields clearly stated by the user.

Return JSON only in this structure:

{
  "can_repair": true,
  "assistant_message": "short message if needed",
  "proposed_update": {},
  "repair_notes": "short explanation"
}

If you cannot repair:
- assistant_message must be a direct clarification question to the user.
- It must not be an internal status message.
- It must ask exactly what information is missing.
- The question must end with a question mark.

{
  "can_repair": false,
  "assistant_message": "dynamic clarification question to the user",
  "proposed_update": {},
  "repair_notes": "why it cannot be repaired"
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


def compact_for_prompt(value, max_chars: int = 10000) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str, indent=2)

    if len(text) > max_chars:
        return text[:max_chars] + "\n...TRUNCATED..."

    return text


def normalize_repair_result(result: dict, original_proposed_update: dict) -> dict:
    if not isinstance(result, dict):
        return {
            "can_repair": False,
            "assistant_message": "I need more information before I can prepare this CRM update.",
            "proposed_update": original_proposed_update,
            "repair_notes": "Invalid repair result.",
        }

    result.setdefault("can_repair", False)
    result.setdefault("assistant_message", "")
    result.setdefault("proposed_update", original_proposed_update)
    result.setdefault("repair_notes", "")

    if not isinstance(result["proposed_update"], dict):
        result["proposed_update"] = original_proposed_update

    return result


def repair_proposed_update(
    user_message: str,
    extraction: dict,
    lookup_context: dict,
    reasoning: dict,
    validation_result: dict,
) -> dict:
    """
    Use LLM to repair an incomplete proposed_update only when possible.
    """

    current_proposed_update = reasoning.get("proposed_update", {}) or {}

    today = datetime.now().date().isoformat()

    prompt = f"""
Today's date is: {today}

Original user message:
{user_message}

Initial extraction:
{compact_for_prompt(extraction, max_chars=5000)}

CRM lookup context:
{compact_for_prompt(lookup_context, max_chars=8000)}

Current reasoning result:
{compact_for_prompt(reasoning, max_chars=6000)}

Validation result:
{compact_for_prompt(validation_result, max_chars=4000)}

Current incomplete proposed_update:
{compact_for_prompt(current_proposed_update, max_chars=4000)}

Repair the proposed_update if the missing fields can be inferred.
Return JSON only.
"""

    try:
        llm = get_llm()

        response = llm.invoke([
            SystemMessage(content=PROPOSAL_REPAIR_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])

        parsed = extract_json_object(response.content)

        return normalize_repair_result(
            result=parsed,
            original_proposed_update=current_proposed_update,
        )

    except Exception as error:
        return {
            "can_repair": False,
            "assistant_message": "I need more information before I can prepare this CRM update.",
            "proposed_update": current_proposed_update,
            "repair_notes": str(error),
        }