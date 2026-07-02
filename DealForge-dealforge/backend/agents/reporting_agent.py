# backend/agents/reporting_agent.py

import os
import json
import re
from typing import Any, Dict, Optional, List

from langchain_openai import ChatOpenAI

from tools.reporting_tools import (
    generate_pipeline_report,
    generate_sales_dashboard_data,
    conversion_report,
    top_lead_sources,
    get_deals_pipeline,
)
from tools.read_tools import (
    get_lead_history,
    lead_summary,
    search_contact,
    get_contact_details,
    search_company,
    get_company_details,
    search_leads,
)


# =========================
# LLM CONFIG
# =========================

llm = ChatOpenAI(
    model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    temperature=0,
    api_key=os.getenv("OPENAI_API_KEY"),
)


# =========================
# COMPATIBILITY HELPERS
# =========================

def flatten_extracted_data(extracted_data: Optional[dict]) -> Dict[str, Any]:
    """
    Converts nested agent output into one flat dictionary.
    This keeps the ReportingAgent independent from old crm_executor_agent.py.
    """
    if not isinstance(extracted_data, dict):
        return {}

    flat: Dict[str, Any] = {}

    def merge_dict(data: dict):
        for key, value in data.items():
            if value is not None and value != "":
                flat[key] = value

    # Keep top-level values first.
    merge_dict({k: v for k, v in extracted_data.items() if not isinstance(v, dict)})

    # Merge common nested structures used by the agents.
    for nested_key in [
        "entities",
        "extracted_data",
        "proposed_update",
        "data",
        "arguments",
        "tool_arguments",
    ]:
        nested = extracted_data.get(nested_key)
        if isinstance(nested, dict):
            merge_dict(nested)

    return flat


def _safe_json_loads(text: str) -> dict:
    """
    Parses LLM JSON safely even if the model accidentally wraps it in markdown.
    """
    if not text:
        return {}

    clean = text.strip()

    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?", "", clean, flags=re.IGNORECASE).strip()
        clean = re.sub(r"```$", "", clean).strip()

    try:
        return json.loads(clean)
    except Exception:
        match = re.search(r"\{.*\}", clean, flags=re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass

    return {
        "executive_summary": "The report was generated, but the LLM analysis could not be parsed as JSON.",
        "insights": [],
        "risks": [],
        "recommendations": [],
        "raw_llm_output": text,
    }


# =========================
# INTENTS
# =========================

CRM_READ_TOOL_MAP = {
    "get_lead_history": "get_lead_history",
    "lead_summary": "lead_summary",
    "search_contact": "search_contact",
    "get_contact_details": "get_contact_details",
    "get_company_info": "get_company_info",
    "get_company_details": "get_company_info",
    "get_pipeline": "get_pipeline",
    "generate_dashboard": "generate_dashboard",
}

REPORT_DEFINITIONS = {
    "dashboard": {"tool": "generate_dashboard"},
    "sales_dashboard": {"tool": "generate_dashboard"},
    "pipeline": {"tool": "get_pipeline"},
    "pipeline_report": {"tool": "get_pipeline"},
    "conversion": {"tool": "conversion_report"},
    "conversion_report": {"tool": "conversion_report"},
    "lead_sources": {"tool": "lead_sources_report"},
    "source_report": {"tool": "lead_sources_report"},
    "deal_pipeline": {"tool": "deal_pipeline_report"},
}

READ_INTENTS = set(CRM_READ_TOOL_MAP.keys())
REPORT_INTENTS = set(REPORT_DEFINITIONS.keys())


# =========================
# REPORTING ENGINE
# =========================

class ReportingAgent:
    """
    CRM Analytics Engine v1.1

    Layers:
    - Tool Execution Layer
    - Normalization Layer
    - Analytics Layer (KPIs + Risks)
    - LLM Intelligence Layer

    This file is additive and does not replace reporting_tools.py.
    """

    def __init__(self, db):
        self.db = db

    # =========================
    # INTERNAL HELPERS
    # =========================

    def _to_int(self, value: Any) -> Optional[int]:
        try:
            if value is None or value == "":
                return None
            return int(value)
        except Exception:
            return None

    def _pick(self, data: Dict[str, Any], *keys: str) -> Any:
        for key in keys:
            value = data.get(key)
            if value is not None and value != "":
                return value
        return None

    def _resolve_lead_id(self, flat: Dict[str, Any]) -> Optional[int]:
        lead_id = self._to_int(self._pick(flat, "lead_id", "current_lead_id"))
        if lead_id:
            return lead_id

        company_name = self._pick(flat, "company_name", "company")
        contact_name = self._pick(flat, "contact_name", "contact", "full_name", "name")
        keyword = self._pick(flat, "keyword", "query", "search_term")

        result = search_leads(
            db=self.db,
            company_name=company_name,
            contact_name=contact_name,
            keyword=keyword,
            limit=5,
        )
        leads = result.get("leads", []) if isinstance(result, dict) else []

        if len(leads) == 1:
            return leads[0].get("lead_id")

        return None

    def _resolve_contact_id(self, flat: Dict[str, Any]) -> Optional[int]:
        contact_id = self._to_int(self._pick(flat, "contact_id"))
        if contact_id:
            return contact_id

        contact_name = self._pick(flat, "contact_name", "contact", "full_name", "name", "keyword")
        company_name = self._pick(flat, "company_name", "company")

        result = search_contact(
            db=self.db,
            name=contact_name,
            company_name=company_name,
        )
        contacts = result.get("contacts", []) if isinstance(result, dict) else []

        if len(contacts) == 1:
            return contacts[0].get("contact_id")

        return None

    def _resolve_company_id(self, flat: Dict[str, Any]) -> Optional[int]:
        company_id = self._to_int(self._pick(flat, "company_id"))
        if company_id:
            return company_id

        company_name = self._pick(flat, "company_name", "company", "keyword")
        if not company_name:
            return None

        result = search_company(db=self.db, keyword=str(company_name))
        companies = result.get("companies", []) if isinstance(result, dict) else []

        if len(companies) == 1:
            return companies[0].get("company_id")

        return None

    # =========================
    # TOOL EXECUTION
    # =========================

    def _run(self, tool_name: str, arguments: Optional[dict] = None):
        """
        Tool router compatible with the current DealForge v2 structure.
        This replaces the old tool_router dependency without changing old files.
        """
        args = arguments or {}

        if tool_name == "get_pipeline":
            return generate_pipeline_report(db=self.db)

        if tool_name == "generate_dashboard":
            return generate_sales_dashboard_data(db=self.db)

        if tool_name == "conversion_report":
            return conversion_report(db=self.db)

        if tool_name == "lead_sources_report":
            return top_lead_sources(db=self.db)

        if tool_name == "deal_pipeline_report":
            return get_deals_pipeline(db=self.db)

        if tool_name == "get_lead_history":
            lead_id = self._resolve_lead_id(args)
            if not lead_id:
                return {
                    "success": False,
                    "message": "I could not identify exactly one lead for the history request.",
                    "lookup": search_leads(
                        db=self.db,
                        company_name=args.get("company_name"),
                        contact_name=args.get("contact_name"),
                        keyword=args.get("keyword"),
                        limit=5,
                    ),
                }
            return get_lead_history(db=self.db, lead_id=lead_id)

        if tool_name == "lead_summary":
            lead_id = self._resolve_lead_id(args)
            if not lead_id:
                return {
                    "success": False,
                    "message": "I could not identify exactly one lead for the summary request.",
                }
            return lead_summary(db=self.db, lead_id=lead_id)

        if tool_name == "search_contact":
            return search_contact(
                db=self.db,
                name=args.get("contact_name") or args.get("name") or args.get("keyword"),
                company_name=args.get("company_name"),
            )

        if tool_name == "get_contact_details":
            contact_id = self._resolve_contact_id(args)
            if not contact_id:
                return {
                    "success": False,
                    "message": "I could not identify exactly one contact.",
                    "lookup": search_contact(
                        db=self.db,
                        name=args.get("contact_name") or args.get("name") or args.get("keyword"),
                        company_name=args.get("company_name"),
                    ),
                }
            return get_contact_details(db=self.db, contact_id=contact_id)

        if tool_name == "get_company_info":
            company_id = self._resolve_company_id(args)
            if company_id:
                return get_company_details(db=self.db, company_id=company_id)

            company_name = args.get("company_name") or args.get("company") or args.get("keyword")
            return search_company(db=self.db, keyword=company_name or "")

        return {
            "success": False,
            "message": f"Unsupported reporting/read tool: {tool_name}",
        }

    # =========================
    # KPI ENGINE
    # =========================

    def _compute_kpis(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(data, dict):
            return {}

        nested_kpis = data.get("kpis") if isinstance(data.get("kpis"), dict) else {}
        conversion = data.get("conversion") if isinstance(data.get("conversion"), dict) else {}
        pipeline = data.get("pipeline") if isinstance(data.get("pipeline"), dict) else {}
        deal_pipeline = data.get("deal_pipeline") if isinstance(data.get("deal_pipeline"), dict) else {}

        pipeline_by_status = (
            data.get("pipeline_by_status")
            or pipeline.get("pipeline_by_status")
            or {}
        )
        pipeline_by_deal_stage = (
            data.get("pipeline_by_deal_stage")
            or deal_pipeline.get("pipeline_by_deal_stage")
            or {}
        )

        total_leads = (
            data.get("total_leads")
            or nested_kpis.get("total_leads")
            or pipeline.get("total_leads")
            or conversion.get("total_leads")
            or sum(pipeline_by_status.values())
            or 0
        )

        won_deals = (
            data.get("won_deals")
            or nested_kpis.get("won_deals")
            or conversion.get("won_leads")
            or pipeline_by_status.get("Won")
            or pipeline_by_deal_stage.get("Closed Won")
            or 0
        )

        lost_deals = (
            data.get("lost_deals")
            or conversion.get("lost_leads")
            or pipeline_by_status.get("Lost")
            or pipeline_by_deal_stage.get("Closed Lost")
            or 0
        )

        total_deals = data.get("total_deals") or nested_kpis.get("total_deals") or 0
        open_deals = data.get("open_deals")

        if open_deals is None:
            open_deals = max((total_deals or total_leads or 0) - won_deals - lost_deals, 0)

        conversion_rate = (
            data.get("conversion_rate")
            or data.get("conversion_rate_percent")
            or conversion.get("conversion_rate_percent")
        )
        if conversion_rate is None:
            conversion_rate = (won_deals / total_leads) * 100 if total_leads else 0

        win_rate = (
            (won_deals / (won_deals + lost_deals)) * 100
            if (won_deals + lost_deals) > 0
            else 0
        )

        pipeline_health = (
            "healthy"
            if conversion_rate >= 40
            else "warning" if conversion_rate >= 25 else "critical"
        )

        return {
            "total_leads": total_leads,
            "won_deals": won_deals,
            "lost_deals": lost_deals,
            "open_deals": open_deals,
            "conversion_rate": round(float(conversion_rate), 2),
            "win_rate": round(float(win_rate), 2),
            "pipeline_health": pipeline_health,
        }

    # =========================
    # RISK ENGINE
    # =========================

    def _detect_risks(self, kpis: Dict[str, Any]) -> List[Dict[str, Any]]:
        risks = []

        def add(level, issue, impact, score):
            risks.append(
                {"type": level, "issue": issue, "impact": impact, "score": score}
            )

        if kpis.get("conversion_rate", 0) < 25:
            add("CRITICAL", "Very low conversion rate", "Revenue loss risk", 0.95)

        if kpis.get("win_rate", 0) < 30:
            add("HIGH", "Weak deal closing efficiency", "Pipeline stagnation", 0.75)

        if kpis.get("open_deals", 0) > kpis.get("total_leads", 1):
            add("MEDIUM", "Pipeline imbalance", "Forecast unreliability", 0.5)

        return sorted(risks, key=lambda x: x["score"], reverse=True)

    # =========================
    # LLM LAYER
    # =========================

    def _safe_llm_invoke(self, prompt: str) -> str:
        try:
            return llm.invoke(prompt).content
        except Exception as exc:
            return f"LLM analysis unavailable: {exc}"

    def _generate_insights(self, context: dict):
        prompt = f"""
You are a CRM Analytics Engine.

Analyze the following:

RAW DATA:
{json.dumps(context["raw_data"], indent=2, default=str)}

KPIs:
{json.dumps(context["kpis"], indent=2, default=str)}

Provide:
- Key insights
- Performance interpretation
- Bottlenecks
"""
        return self._safe_llm_invoke(prompt)

    def _generate_recommendations(self, context: dict):
        prompt = f"""
You are a revenue optimization engine.

DATA:
{json.dumps(context, indent=2, default=str)}

Return 3 prioritized recommendations focusing on:
- conversion improvement
- pipeline velocity
- revenue growth
"""
        return self._safe_llm_invoke(prompt)

    def _generate_full_analysis(self, context):
        prompt = f"""
You are a senior CRM analytics engine.

Return ONLY valid JSON (no markdown, no text).

Format exactly:

{{
  "executive_summary": "string",
  "insights": [
    "string",
    "string",
    "string"
  ],
  "risks": [
    {{
      "type": "CRITICAL | HIGH | MEDIUM",
      "issue": "string",
      "impact": "string"
    }}
  ],
  "recommendations": [
    "string",
    "string",
    "string"
  ]
}}

DATA:
{json.dumps(context, indent=2, default=str)}
"""
        response = self._safe_llm_invoke(prompt)
        parsed = _safe_json_loads(response)

        if not parsed.get("risks") and context.get("risks"):
            parsed["risks"] = [
                {
                    "type": risk.get("type"),
                    "issue": risk.get("issue"),
                    "impact": risk.get("impact"),
                }
                for risk in context.get("risks", [])
            ]

        return parsed

    def _explain_risks(self, risks: List[Dict[str, Any]]):
        prompt = f"""
Explain these CRM risks in business language:

{json.dumps(risks, indent=2, default=str)}

Include:
- Business impact
- Severity
- Action plan
"""
        return self._safe_llm_invoke(prompt)

    # =========================
    # REPORT TOOL EXECUTION
    # =========================

    def _run_report_tool(self, report_type: str):
        report_type = report_type or "dashboard"
        tool_name = REPORT_DEFINITIONS.get(report_type, {}).get(
            "tool", "generate_dashboard"
        )
        return self._run(tool_name, {})

    # =========================
    # READ INTENT
    # =========================

    def handle_read_intent(self, flat: Dict[str, Any], current_lead_id=None):
        intent = flat.get("intent")

        if intent not in READ_INTENTS:
            return {"success": False, "message": "Unsupported intent"}

        if current_lead_id and not flat.get("lead_id"):
            flat["lead_id"] = current_lead_id

        tool_name = CRM_READ_TOOL_MAP[intent]
        result = self._run(tool_name, flat)

        return {
            "success": bool(result.get("success", True)) if isinstance(result, dict) else True,
            "intent": intent,
            "tool_name": tool_name,
            "tool_result": result,
        }

    # =========================
    # REPORT PIPELINE
    # =========================

    def handle_report_intent(self, flat: Dict[str, Any], user_message=""):
        report_type = (
            flat.get("report_type")
            or flat.get("intent")
            or "dashboard"
        )

        if report_type in ["get_pipeline", "pipeline_report"]:
            report_type = "pipeline"
        elif report_type == "generate_dashboard":
            report_type = "dashboard"

        result = self._run_report_tool(report_type)

        if not isinstance(result, dict) or not result.get("success"):
            return {
                "success": False,
                "message": "Report generation failed",
                "tool_result": result,
            }

        # =========================
        # NORMALIZATION LAYER
        # =========================

        raw_data = (
            result.get("report", {}).get("data")
            if isinstance(result.get("report"), dict)
            else None
        ) or result.get("report", {}) or result.get("result") or result

        # =========================
        # KPI ENGINE
        # =========================

        kpis = raw_data.get("kpis") if isinstance(raw_data.get("kpis"), dict) else {}
        computed_kpis = self._compute_kpis(raw_data)
        kpis = {**kpis, **computed_kpis}

        # =========================
        # RISK ENGINE
        # =========================

        risks = self._detect_risks(kpis)

        # =========================
        # LLM LAYER
        # =========================

        analysis = self._generate_full_analysis(
            {
                "raw_data": raw_data,
                "kpis": kpis,
                "risks": risks,
            }
        )

        return {
            "success": True,
            "message": "Analytics report generated successfully",
            "report_type": report_type,
            # Core
            "report": raw_data,
            # Analytics
            "kpis": kpis,
            "risks": risks,
            # Intelligence Layer
            "analysis": analysis,
        }

    # =========================
    # MAIN ENTRY
    # =========================

    def handle(self, extracted_data, user_message="", current_lead_id=None):
        flat = flatten_extracted_data(extracted_data)
        intent = flat.get("intent") or "dashboard"

        if intent in READ_INTENTS:
            return self.handle_read_intent(flat, current_lead_id)

        return self.handle_report_intent(flat, user_message)


# =========================
# COMPATIBILITY LAYER
# =========================

class reporter(ReportingAgent):
    def generate_report(self, intent: str, report_type: str = "dashboard"):
        return self.handle_report_intent({"intent": intent, "report_type": report_type})


def handle_reporting_request(
    db,
    extracted_data: dict,
    user_message: str = "",
    current_lead_id: Optional[int] = None,
):
    return ReportingAgent(db).handle(
        extracted_data=extracted_data,
        user_message=user_message,
        current_lead_id=current_lead_id,
    )


def generate_report(db, extracted_data: dict, user_message: str):
    return handle_reporting_request(db, extracted_data, user_message)
