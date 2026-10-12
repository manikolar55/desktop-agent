"""Permission levels and per-action authorization rules."""

from __future__ import annotations

from enum import Enum
from typing import Callable


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Action(str, Enum):
    # ── LOW risk ─────────────────────────────────────────────────────────────
    READ_PUBLIC_URL = "read_public_url"
    SUMMARIZE_DOCUMENT = "summarize_document"
    DRAFT_PROPOSAL = "draft_proposal"
    RUN_LOCAL_TESTS = "run_local_tests"
    NAVIGATE_WEBSITE = "navigate_website"
    CAPTURE_SCREENSHOT = "capture_screenshot"
    READ_FILE = "read_file"
    SEARCH_WEB = "search_web"

    # ── MEDIUM risk ───────────────────────────────────────────────────────────
    SEND_STATUS_UPDATE = "send_status_update"
    EDIT_PROJECT_FILE = "edit_project_file"
    INSTALL_DEPENDENCY = "install_dependency"
    CHANGE_APP_SETTINGS = "change_app_settings"
    RUN_SHELL_COMMAND = "run_shell_command"
    OPEN_APPLICATION = "open_application"
    CLICK_FORM_ELEMENT = "click_form_element"
    FILL_FORM = "fill_form"

    # ── HIGH risk ─────────────────────────────────────────────────────────────
    DELETE_FILE = "delete_file"
    RUN_DESTRUCTIVE_COMMAND = "run_destructive_command"
    ACCESS_CREDENTIALS = "access_credentials"
    MODIFY_PRODUCTION = "modify_production"
    DEPLOY_SOFTWARE = "deploy_software"
    MAKE_PURCHASE = "make_purchase"
    ACCEPT_CONTRACT = "accept_contract"
    SEND_EXTERNAL_MESSAGE = "send_external_message"
    SUBMIT_APPLICATION = "submit_application"
    RUN_DB_MIGRATION = "run_db_migration"


_RISK_MAP: dict[Action, RiskLevel] = {
    # LOW
    Action.READ_PUBLIC_URL: RiskLevel.LOW,
    Action.SUMMARIZE_DOCUMENT: RiskLevel.LOW,
    Action.DRAFT_PROPOSAL: RiskLevel.LOW,
    Action.RUN_LOCAL_TESTS: RiskLevel.LOW,
    Action.NAVIGATE_WEBSITE: RiskLevel.LOW,
    Action.CAPTURE_SCREENSHOT: RiskLevel.LOW,
    Action.READ_FILE: RiskLevel.LOW,
    Action.SEARCH_WEB: RiskLevel.LOW,
    # MEDIUM
    Action.SEND_STATUS_UPDATE: RiskLevel.MEDIUM,
    Action.EDIT_PROJECT_FILE: RiskLevel.MEDIUM,
    Action.INSTALL_DEPENDENCY: RiskLevel.MEDIUM,
    Action.CHANGE_APP_SETTINGS: RiskLevel.MEDIUM,
    Action.RUN_SHELL_COMMAND: RiskLevel.MEDIUM,
    Action.OPEN_APPLICATION: RiskLevel.MEDIUM,
    Action.CLICK_FORM_ELEMENT: RiskLevel.MEDIUM,
    Action.FILL_FORM: RiskLevel.MEDIUM,
    # HIGH
    Action.DELETE_FILE: RiskLevel.HIGH,
    Action.RUN_DESTRUCTIVE_COMMAND: RiskLevel.HIGH,
    Action.ACCESS_CREDENTIALS: RiskLevel.HIGH,
    Action.MODIFY_PRODUCTION: RiskLevel.HIGH,
    Action.DEPLOY_SOFTWARE: RiskLevel.HIGH,
    Action.MAKE_PURCHASE: RiskLevel.HIGH,
    Action.ACCEPT_CONTRACT: RiskLevel.HIGH,
    Action.SEND_EXTERNAL_MESSAGE: RiskLevel.HIGH,
    Action.SUBMIT_APPLICATION: RiskLevel.HIGH,
    Action.RUN_DB_MIGRATION: RiskLevel.HIGH,
}


def risk_level_for(action: Action) -> RiskLevel:
    return _RISK_MAP.get(action, RiskLevel.HIGH)


def requires_approval(action: Action, auto_approved_actions: set[Action] | None = None) -> bool:
    level = risk_level_for(action)
    if level == RiskLevel.HIGH:
        return True
    if level == RiskLevel.MEDIUM:
        approved = auto_approved_actions or set()
        return action not in approved
    return False


ApprovalCallback = Callable[[str, str], bool]
