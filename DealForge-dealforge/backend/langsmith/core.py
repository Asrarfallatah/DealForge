import os
from langsmith import traceable

# ======================
# CONFIG (LangSmith)
# ======================
os.environ["LANGSMITH_TRACING"] = "true"
os.environ["LANGSMITH_PROJECT"] = "DealForge"


# ======================
# MOCK TOOLS
# ======================
def crm_tool(text):
    return {"module": "crm", "action": "processed", "data": text}


def reporting_tool(text):
    return {
        "module": "reporting",
        "kpis": {
            "total_leads": 500,
            "conversion_rate": 0.32,
            "active_deals": 120,
        },
    }


# ======================
# ROUTER
# ======================
def router(text: str):
    text_lower = text.lower()

    reporting_keywords = [
        "report",
        "dashboard",
        "analytics",
        "kpi",
        "revenue",
        "conversion",
        "performance",
        "sales report",
    ]

    crm_keywords = [
        "lead",
        "customer",
        "client",
        "deal",
        "add",
        "create",
        "register",
        "update",
        "modify",
        "change",
        "move",
        "mark",
        "delete",
    ]

    if any(word in text_lower for word in reporting_keywords):
        return "reporting"

    elif any(word in text_lower for word in crm_keywords):
        return "crm"

    else:
        return "unknown"


# ======================
# PIPELINE
# ======================
@traceable
def process_user_input(text: str):

    route = router(text)

    if route == "crm":
        result = crm_tool(text)

    elif route == "reporting":
        result = reporting_tool(text)

    else:
        result = {"error": "Unknown request"}

    return {"output": {"route": route, "response": result}}
