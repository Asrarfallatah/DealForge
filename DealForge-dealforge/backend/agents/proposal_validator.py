# backend/agents/proposal_validator.py


def has_value(value) -> bool:
    """
    Check if a value is not empty.
    """
    return value is not None and value != ""


def add_error(errors: list, action: str, field: str, message: str, repairable: bool = True):
    errors.append({
        "action": action,
        "field": field,
        "message": message,
        "repairable": repairable,
    })


def has_any_field(proposed_update: dict, fields: list[str]) -> bool:
    return any(has_value(proposed_update.get(field)) for field in fields)


def validate_proposed_update(proposed_update: dict) -> dict:
    """
    Validate the proposed CRM update before creating a pending approval.

    This does not use LLM.
    This does not update the database.
    It only checks whether the proposal has the required fields.
    """

    errors = []

    if not isinstance(proposed_update, dict) or not proposed_update:
        return {
            "success": False,
            "is_valid": False,
            "errors": [
                {
                    "action": "proposal",
                    "field": "proposed_update",
                    "message": "proposed_update is empty or invalid.",
                    "repairable": False,
                }
            ],
        }

    lead_id = proposed_update.get("lead_id")
    company_id = proposed_update.get("company_id")
    contact_id = proposed_update.get("contact_id")
    deal_id = proposed_update.get("deal_id")
    task_id = proposed_update.get("task_id")

    # ============================================================
    # CREATE COMPANY
    # ============================================================
    if proposed_update.get("create_company"):
        if not has_value(proposed_update.get("company_name")):
            add_error(
                errors,
                action="create_company",
                field="company_name",
                message="create_company requires company_name.",
                repairable=True,
            )

    # ============================================================
    # UPDATE COMPANY
    # ============================================================
    if proposed_update.get("update_company"):
        if not has_value(company_id):
            add_error(
                errors,
                action="update_company",
                field="company_id",
                message="update_company requires company_id.",
                repairable=False,
            )

        update_fields = [
            "company_name",
            "industry",
            "size",
            "location",
            "website",
            "source",
            "description",
        ]

        if not has_any_field(proposed_update, update_fields):
            add_error(
                errors,
                action="update_company",
                field="company_update_fields",
                message="update_company requires at least one company field to update.",
                repairable=True,
            )

    # ============================================================
    # CREATE CONTACT
    # ============================================================
    if proposed_update.get("create_contact"):
        if not has_value(company_id) and not proposed_update.get("create_company"):
            add_error(
                errors,
                action="create_contact",
                field="company_id",
                message="create_contact requires company_id or create_company.",
                repairable=False,
            )

        if not has_value(proposed_update.get("contact_name")) and not has_value(proposed_update.get("full_name")):
            add_error(
                errors,
                action="create_contact",
                field="contact_name",
                message="create_contact requires contact_name or full_name.",
                repairable=True,
            )

    # ============================================================
    # UPDATE CONTACT
    # ============================================================
    if proposed_update.get("update_contact"):
        if not has_value(contact_id):
            add_error(
                errors,
                action="update_contact",
                field="contact_id",
                message="update_contact requires contact_id.",
                repairable=False,
            )

        update_fields = [
            "contact_name",
            "full_name",
            "email",
            "phone",
            "job_title",
            "company_id",
        ]

        if not has_any_field(proposed_update, update_fields):
            add_error(
                errors,
                action="update_contact",
                field="contact_update_fields",
                message="update_contact requires at least one contact field to update.",
                repairable=True,
            )

    # ============================================================
    # CREATE LEAD
    # ============================================================
    if proposed_update.get("create_lead"):
        if not has_value(company_id) and not proposed_update.get("create_company"):
            add_error(
                errors,
                action="create_lead",
                field="company_id",
                message="create_lead requires company_id or create_company.",
                repairable=False,
            )

        if not has_value(contact_id) and not proposed_update.get("create_contact"):
            add_error(
                errors,
                action="create_lead",
                field="contact_id",
                message="create_lead requires contact_id or create_contact.",
                repairable=False,
            )

    # ============================================================
    # UPDATE LEAD STATUS / FIELDS
    # ============================================================
    if (
        proposed_update.get("update_lead_fields")
        or has_value(proposed_update.get("lead_status"))
        or has_value(proposed_update.get("new_status"))
    ):
        if not has_value(lead_id):
            add_error(
                errors,
                action="update_lead",
                field="lead_id",
                message="lead update requires lead_id.",
                repairable=False,
            )

    if proposed_update.get("update_lead_fields"):
        update_fields = [
            "lead_source",
            "interest",
            "priority",
            "owner_name",
            "last_summary",
            "company_id",
            "contact_id",
            "campaign_id",
        ]

        if not has_any_field(proposed_update, update_fields):
            add_error(
                errors,
                action="update_lead_fields",
                field="lead_update_fields",
                message="update_lead_fields requires at least one lead field to update.",
                repairable=True,
            )

    # ============================================================
    # CREATE DEAL
    # ============================================================
    if proposed_update.get("create_deal"):
        if not has_value(lead_id) and not proposed_update.get("create_lead"):
            add_error(
                errors,
                action="create_deal",
                field="lead_id",
                message="create_deal requires lead_id or create_lead.",
                repairable=False,
            )

        if not has_value(company_id) and not proposed_update.get("create_company"):
            add_error(
                errors,
                action="create_deal",
                field="company_id",
                message="create_deal requires company_id or create_company.",
                repairable=False,
            )

        if not has_value(proposed_update.get("deal_name")):
            add_error(
                errors,
                action="create_deal",
                field="deal_name",
                message="create_deal requires deal_name.",
                repairable=True,
            )

    # ============================================================
    # UPDATE DEAL
    # ============================================================
    if proposed_update.get("update_deal_fields") or proposed_update.get("update_deal_stage"):
        if not has_value(deal_id):
            add_error(
                errors,
                action="update_deal",
                field="deal_id",
                message="deal update requires deal_id.",
                repairable=False,
            )

    if proposed_update.get("update_deal_fields"):
        update_fields = [
            "deal_name",
            "deal_value",
            "probability",
            "expected_close_date",
        ]

        if not has_any_field(proposed_update, update_fields):
            add_error(
                errors,
                action="update_deal_fields",
                field="deal_update_fields",
                message="update_deal_fields requires at least one deal field to update.",
                repairable=True,
            )

    if proposed_update.get("update_deal_stage"):
        if not has_value(proposed_update.get("new_deal_stage")) and not has_value(proposed_update.get("deal_stage")):
            add_error(
                errors,
                action="update_deal_stage",
                field="new_deal_stage",
                message="update_deal_stage requires new_deal_stage.",
                repairable=True,
            )

    # ============================================================
    # CREATE ACTIVITY
    # ============================================================
    if proposed_update.get("create_activity"):
        if not has_value(lead_id):
            add_error(
                errors,
                action="create_activity",
                field="lead_id",
                message="create_activity requires lead_id.",
                repairable=False,
            )

        if not has_value(proposed_update.get("activity_notes")):
            add_error(
                errors,
                action="create_activity",
                field="activity_notes",
                message="create_activity requires activity_notes.",
                repairable=True,
            )

    # ============================================================
    # CREATE FOLLOW-UP TASK
    # ============================================================
    if proposed_update.get("create_follow_up_task"):
        if not has_value(lead_id):
            add_error(
                errors,
                action="create_follow_up_task",
                field="lead_id",
                message="create_follow_up_task requires lead_id.",
                repairable=False,
            )

        if not has_value(proposed_update.get("task_title")):
            add_error(
                errors,
                action="create_follow_up_task",
                field="task_title",
                message="create_follow_up_task requires task_title.",
                repairable=True,
            )

    # ============================================================
    # UPDATE TASK
    # ============================================================
    if proposed_update.get("update_task"):
        if not has_value(task_id):
            add_error(
                errors,
                action="update_task",
                field="task_id",
                message="update_task requires task_id.",
                repairable=False,
            )

        update_fields = [
            "task_title",
            "due_date",
            "task_status",
            "status",
            "priority",
        ]

        if not has_any_field(proposed_update, update_fields):
            add_error(
                errors,
                action="update_task",
                field="task_update_fields",
                message="update_task requires at least one task field to update.",
                repairable=True,
            )

    return {
        "success": len(errors) == 0,
        "is_valid": len(errors) == 0,
        "errors": errors,
    }