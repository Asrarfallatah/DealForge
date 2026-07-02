# backend/agents/response_builder.py


def looks_like_question(text: str) -> bool:
    if not text:
        return False

    text = str(text).strip()

    question_words = [
        "which",
        "what",
        "who",
        "when",
        "where",
        "how",
        "could you",
        "please provide",
        "please confirm",

    ]

    lower = text.lower()

    return text.endswith("?") or any(word in lower for word in question_words)


def build_missing_fields_question(reasoning: dict) -> str:
    missing_fields = reasoning.get("missing_fields") or []

    if isinstance(missing_fields, list) and missing_fields:
        fields_text = ", ".join(str(field) for field in missing_fields)

        if "lead_id" in fields_text or "contact" in fields_text or "company" in fields_text:
            return "Which contact, company, or lead should I use for this CRM update?"

        if "activity_notes" in fields_text:
            return "What activity should I log for this lead?"

        if "task_title" in fields_text:
            return "What should the follow-up task be about?"

        if "due_date" in fields_text:
            return "When should I schedule the follow-up task?"

    return "I need one clarification before I can prepare this CRM update. Which lead or customer should this update apply to?"

def build_clarification_response(reasoning: dict) -> dict:
    """
    Build a user-facing clarification response.
    Always return a real question, not an internal status message.
    """

    message = (
        reasoning.get("clarification_question")
        or reasoning.get("assistant_message")
        or reasoning.get("message")
        or ""
    )

    if not looks_like_question(message):
        message = build_missing_fields_question(reasoning)

    return {
        "type": "clarification",
        "message": message,
        "clarification_question": message,
        "requires_user_input": True,
        "needs_approval": False,
        "missing_fields": reasoning.get("missing_fields", []),
    }


def build_choices_response(reasoning: dict) -> dict:
    return {
        "type": "choices",
        "message": reasoning.get("assistant_message"),
        "requires_user_input": True,
        "choices": reasoning.get("choices", []),
        "needs_approval": False,
    }


def build_pending_response(reasoning: dict, pending_result: dict) -> dict:
    proposed_update = reasoning.get("proposed_update", {}) or {}

    return {
        "type": "approval_required",
        "message": reasoning.get("assistant_message", "Please review and approve the proposed CRM update."),
        "requires_user_input": True,
        "needs_approval": True,
        "pending_id": pending_result.get("pending_id"),
        "approval_status": pending_result.get("approval_status", "Pending"),
        "proposed_actions": build_proposed_actions_from_update(proposed_update),
        "proposed_update": proposed_update,
    }


def build_read_response(reasoning: dict, read_result: dict) -> dict:
    return {
        "type": "read_result",
        "message": reasoning.get("assistant_message"),
        "requires_user_input": False,
        "needs_approval": False,
        "data": read_result,
    }


def build_pipeline_report_message(report_result: dict) -> str:
    if not report_result or not report_result.get("success"):
        return "I could not generate the pipeline report."

    total_leads = report_result.get("total_leads")
    pipeline = report_result.get("pipeline_by_status", {}) or {}

    lines = ["Pipeline Report"]

    if total_leads is not None:
        lines.append(f"Total leads: {total_leads}")

    for status, count in pipeline.items():
        lines.append(f"- {status}: {count}")

    return "\n".join(lines)


def build_dashboard_message(report_result: dict) -> str:
    if not report_result or not report_result.get("success"):
        return "I could not generate the sales dashboard."

    kpis = report_result.get("kpis", {}) or {}

    lines = ["Sales Dashboard"]

    for key, value in kpis.items():
        label = key.replace("_", " ").title()
        lines.append(f"- {label}: {value}")

    return "\n".join(lines)


def build_report_response(reasoning: dict, report_result: dict) -> dict:
    """
    Build report message from advanced ReportingAgent output.
    """

    if not report_result or not report_result.get("success"):
        return {
            "type": "report",
            "message": "I could not generate the report.",
            "requires_user_input": False,
            "needs_approval": False,
            "data": report_result,
        }

    report_type = report_result.get("report_type", "report")
    kpis = report_result.get("kpis", {}) or {}
    risks = report_result.get("risks", []) or []
    analysis = report_result.get("analysis", {}) or {}
    raw_report = report_result.get("report", {}) or {}

    lines = []

    title = report_type.replace("_", " ").title()
    lines.append(f"{title} Report")

    if kpis:
        lines.append("")
        lines.append("KPIs:")
        for key, value in kpis.items():
            label = key.replace("_", " ").title()
            lines.append(f"- {label}: {value}")

    if raw_report.get("pipeline_by_status"):
        lines.append("")
        lines.append("Lead Pipeline:")
        for status, count in raw_report.get("pipeline_by_status", {}).items():
            lines.append(f"- {status}: {count}")

    if raw_report.get("lead_pipeline"):
        lines.append("")
        lines.append("Lead Pipeline:")
        for status, count in raw_report.get("lead_pipeline", {}).items():
            lines.append(f"- {status}: {count}")

    if raw_report.get("deal_pipeline"):
        lines.append("")
        lines.append("Deal Pipeline:")
        for stage, count in raw_report.get("deal_pipeline", {}).items():
            lines.append(f"- {stage}: {count}")

    executive_summary = analysis.get("executive_summary")
    if executive_summary:
        lines.append("")
        lines.append("Executive Summary:")
        lines.append(str(executive_summary))

    insights = analysis.get("insights") or []
    if insights:
        lines.append("")
        lines.append("Insights:")
        for item in insights:
            lines.append(f"- {item}")

    if risks:
        lines.append("")
        lines.append("Risks:")
        for risk in risks:
            issue = risk.get("issue", "Risk detected")
            level = risk.get("type", "MEDIUM")
            impact = risk.get("impact", "")
            lines.append(f"- {level}: {issue} — {impact}")

    recommendations = analysis.get("recommendations") or []
    if recommendations:
        lines.append("")
        lines.append("Recommendations:")
        for item in recommendations:
            lines.append(f"- {item}")

    message = "\n".join(lines)

    return {
        "type": "report",
        "message": message,
        "requires_user_input": False,
        "needs_approval": False,
        "data": report_result,
    }


def short_text(text: str, max_chars: int = 450) -> str:
    if not text:
        return ""

    text = " ".join(str(text).split())

    if len(text) <= max_chars:
        return text

    return text[:max_chars].rstrip() + "..."


def build_enrichment_message(enrichment_result: dict) -> str:
    if not enrichment_result or not enrichment_result.get("success"):
        return "I could not find useful public company information."

    company_name = enrichment_result.get("company_name") or "the company"
    website = enrichment_result.get("website")

    company_profile = enrichment_result.get("company_profile", {}) or {}
    scraped_text = company_profile.get("scraped_text", "")

    contact_info = enrichment_result.get("contact_info", {}) or {}
    emails = contact_info.get("emails", []) or []
    phones = contact_info.get("phone_numbers", []) or []
    social_links = contact_info.get("social_links", {}) or {}
    linkedin = social_links.get("linkedin", []) or []

    lines = [f"I found public information for {company_name}."]

    if website:
        lines.append(f"- Website: {website}")

    if emails:
        lines.append(f"- Email: {', '.join(emails[:3])}")

    if phones:
        lines.append(f"- Phone: {', '.join(phones[:3])}")

    if linkedin:
        lines.append(f"- LinkedIn: {linkedin[0]}")

    summary = short_text(scraped_text)

    if summary:
        lines.append(f"- Summary: {summary}")

    return "\n".join(lines)


def build_enrichment_response(reasoning: dict, enrichment_result: dict) -> dict:
    """
    Build a short user-facing enrichment message.
    Keep full raw data in data.
    """

    return {
        "type": "enrichment",
        "message": build_enrichment_message(enrichment_result),
        "requires_user_input": False,
        "needs_approval": False,
        "data": enrichment_result,
    }


def build_unsupported_response(reasoning: dict) -> dict:
    return {
        "type": "unsupported",
        "message": reasoning.get("assistant_message"),
        "requires_user_input": False,
        "needs_approval": False,
    }


def build_error_response(message: str, details=None) -> dict:
    return {
        "type": "error",
        "message": message,
        "requires_user_input": False,
        "needs_approval": False,
        "details": details,
    }


def build_final_response(state: dict) -> dict:
    """
    Build one consistent response shape for UI/API.
    This does not reason and does not use LLM.
    """

    reasoning = state.get("reasoning", {}) or {}
    decision = reasoning.get("decision")

    if state.get("error"):
        return build_error_response(
            message="Something went wrong while processing your request.",
            details=state.get("error"),
        )

    if decision == "ask_clarification":
        return build_clarification_response(reasoning)

    if decision == "present_choices":
        return build_choices_response(reasoning)

    if decision == "prepare_pending_update":
        pending_result = state.get("pending_result", {}) or {}

        if pending_result.get("success"):
            return build_pending_response(
                reasoning=reasoning,
                pending_result=pending_result,
            )

        return build_error_response(
            message="I prepared a CRM update, but could not create the pending approval record.",
            details=pending_result,
        )

    if decision == "return_read_result":
        return build_read_response(
            reasoning=reasoning,
            read_result=state.get("read_result", {}),
        )

    if decision == "return_report":
        return build_report_response(
            reasoning=reasoning,
            report_result=state.get("report_result", {}),
        )

    if decision == "run_enrichment":
        return build_enrichment_response(
            reasoning=reasoning,
            enrichment_result=state.get("enrichment_result", {}),
        )

    if decision == "unsupported_action":
        return build_unsupported_response(reasoning)

    # Safety fallback:
    # Sometimes graph routing can execute report/read even if LLM decision text is imperfect.
    if state.get("report_result"):
        return build_report_response(
            reasoning=reasoning,
            report_result=state.get("report_result", {}),
        )

    if state.get("read_result"):
        return build_read_response(
            reasoning=reasoning,
            read_result=state.get("read_result", {}),
        )

    if state.get("enrichment_result"):
        return build_enrichment_response(
            reasoning=reasoning,
            enrichment_result=state.get("enrichment_result", {}),
        )

    return {
        "type": decision or "final",
        "message": reasoning.get("assistant_message", "Done."),
        "requires_user_input": False,
        "needs_approval": reasoning.get("needs_approval", False),
        "reasoning_notes": reasoning.get("reasoning_notes"),
    }


def build_proposed_actions_from_update(proposed_update: dict) -> list:
    """
    Build UI-friendly proposed_actions from the final proposed_update.
    This keeps the displayed proposal consistent with what will be executed.
    """

    if not isinstance(proposed_update, dict):
        return []

    actions = []

    if proposed_update.get("create_activity"):
        actions.append({
            "action_type": "create_activity",
            "data": {
                "lead_id": proposed_update.get("lead_id"),
                "activity_type": proposed_update.get("activity_type"),
                "activity_notes": proposed_update.get("activity_notes"),
            },
        })

    if proposed_update.get("create_follow_up_task"):
        actions.append({
            "action_type": "create_follow_up_task",
            "data": {
                "lead_id": proposed_update.get("lead_id"),
                "task_title": proposed_update.get("task_title"),
                "due_date": proposed_update.get("due_date"),
                "priority": proposed_update.get("priority"),
            },
        })

    if proposed_update.get("update_lead_fields"):
        actions.append({
            "action_type": "update_lead_fields",
            "data": {
                "lead_id": proposed_update.get("lead_id"),
                "lead_source": proposed_update.get("lead_source"),
                "interest": proposed_update.get("interest"),
                "priority": proposed_update.get("priority"),
                "owner_name": proposed_update.get("owner_name"),
                "last_summary": proposed_update.get("last_summary"),
            },
        })

    if proposed_update.get("lead_status") or proposed_update.get("new_status"):
        actions.append({
            "action_type": "update_lead_status",
            "data": {
                "lead_id": proposed_update.get("lead_id"),
                "new_status": proposed_update.get("new_status") or proposed_update.get("lead_status"),
            },
        })

    if proposed_update.get("update_company"):
        actions.append({
            "action_type": "update_company",
            "data": {
                "company_id": proposed_update.get("company_id"),
                "company_name": proposed_update.get("company_name"),
                "industry": proposed_update.get("industry"),
                "size": proposed_update.get("size"),
                "location": proposed_update.get("location"),
                "website": proposed_update.get("website"),
            },
        })

    if proposed_update.get("update_contact"):
        actions.append({
            "action_type": "update_contact",
            "data": {
                "contact_id": proposed_update.get("contact_id"),
                "full_name": proposed_update.get("full_name") or proposed_update.get("contact_name"),
                "email": proposed_update.get("email"),
                "phone": proposed_update.get("phone"),
                "job_title": proposed_update.get("job_title"),
            },
        })

    if proposed_update.get("update_deal_stage"):
        actions.append({
            "action_type": "update_deal_stage",
            "data": {
                "deal_id": proposed_update.get("deal_id"),
                "new_deal_stage": proposed_update.get("new_deal_stage") or proposed_update.get("deal_stage"),
            },
        })

    if proposed_update.get("update_deal_fields"):
        actions.append({
            "action_type": "update_deal_fields",
            "data": {
                "deal_id": proposed_update.get("deal_id"),
                "deal_name": proposed_update.get("deal_name"),
                "deal_value": proposed_update.get("deal_value"),
                "probability": proposed_update.get("probability"),
                "expected_close_date": proposed_update.get("expected_close_date"),
            },
        })

    # Remove empty values from action data
    cleaned_actions = []

    for action in actions:
        data = action.get("data", {})
        cleaned_data = {
            key: value
            for key, value in data.items()
            if value is not None and value != ""
        }

        cleaned_actions.append({
            "action_type": action.get("action_type"),
            "data": cleaned_data,
        })

    return cleaned_actions