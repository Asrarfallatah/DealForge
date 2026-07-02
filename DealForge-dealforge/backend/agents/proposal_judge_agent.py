import json
import os
import re

from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI

load_dotenv()

JUDGE_SYSTEM_PROMPT = """
You are the LLM-as-a-Judge for DealForge CRM.

You evaluate a proposed CRM update BEFORE it reaches human approval.

You receive:
1. User message
2. Extraction result
3. CRM lookup context
4. Reasoning result
5. Proposed update

Your job:
- Check whether the proposed_update matches the user's request.
- Check whether the selected lead/contact/company is consistent with lookup results.
- Detect hallucinated fields such as priority, due_date, status, budget, or IDs.
- Check CRM logic consistency.
- Decide whether it is safe to continue to rule-based validation.

Scoring:
8-10 = pass
5-7 = pass_with_warning
0-4 = needs_revision

Return JSON only:

{
  "score": 8,
  "verdict": "pass",
  "pass_to_validator": true,
  "issues": [],
  "warning": "",
  "suggested_action": "continue"
}
"""


def get_llm():
    return ChatOpenAI(model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"), temperature=0)


def _parse_json(text: str) -> dict:
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def judge_proposed_update(
    user_message: str,
    extraction: dict,
    lookup_context: dict,
    reasoning: dict,
) -> dict:
    proposed_update = reasoning.get("proposed_update", {}) or {}

    if not proposed_update:
        return {
            "score": 0,
            "verdict": "needs_revision",
            "pass_to_validator": False,
            "issues": ["No proposed_update was provided."],
            "warning": "",
            "suggested_action": "ask_clarification",
        }

    prompt = f"""
User message:
{user_message}

Extraction:
{json.dumps(extraction, ensure_ascii=False, indent=2, default=str)}

CRM lookup context:
{json.dumps(lookup_context, ensure_ascii=False, indent=2, default=str)}

Reasoning result:
{json.dumps(reasoning, ensure_ascii=False, indent=2, default=str)}

Proposed update:
{json.dumps(proposed_update, ensure_ascii=False, indent=2, default=str)}
"""

    try:
        response = get_llm().invoke(
            [
                SystemMessage(content=JUDGE_SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ]
        )

        result = _parse_json(response.content)

        score = int(result.get("score", 0))

        if score >= 8:
            verdict = "pass"
            pass_to_validator = True
        elif score >= 5:
            verdict = "pass_with_warning"
            pass_to_validator = True
        else:
            verdict = "needs_revision"
            pass_to_validator = False

        result["score"] = score
        result["verdict"] = verdict
        result["pass_to_validator"] = pass_to_validator

        return result

    except Exception as e:
        return {
            "score": 5,
            "verdict": "pass_with_warning",
            "pass_to_validator": True,
            "issues": [f"Judge failed to parse response: {str(e)}"],
            "warning": "Judge failed, so the system continued with rule-based validation.",
            "suggested_action": "continue_with_warning",
        }
