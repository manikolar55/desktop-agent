"""Head agent router: classifies a task into the right sub-agent domain."""

from __future__ import annotations

import logging

from agent.subagents.base import SubAgentConfig
from agent.subagents.browser import browser_agent
from agent.subagents.desktop import desktop_agent
from agent.subagents.email_chat import email_chat_agent
from agent.subagents.file_docs import file_docs_agent

log = logging.getLogger(__name__)

_AGENTS: dict[str, SubAgentConfig] = {
    "browser":    browser_agent,
    "desktop":    desktop_agent,
    "email_chat": email_chat_agent,
    "file_docs":  file_docs_agent,
}

_ROUTER_SYSTEM = """
You are a task router for an AI desktop assistant.
Classify the user's task into exactly ONE of these agent types:

browser    — opening URLs, web search, YouTube, navigating websites, reading web pages
desktop    — opening/closing apps, clicking UI, keyboard shortcuts, screenshots, window control
email_chat — email (Gmail/Outlook), chat (WhatsApp/Slack/Telegram/Google Chat), video calls
file_docs  — reading/writing local files, Word/Excel/PDF documents, summarising, creating reports

Reply with ONLY the agent type word. Nothing else.

Examples:
"Open YouTube" → browser
"Search for Python tutorials" → browser
"Take a screenshot" → desktop
"Open Notepad and type hello" → desktop
"Close Chrome" → desktop
"Check my Gmail" → email_chat
"Send a WhatsApp message to John" → email_chat
"Read the PDF at C:/report.pdf" → file_docs
"Summarise this document" → file_docs
"Save this text to a file" → file_docs
""".strip()

# Keywords used when Claude API is unavailable
_EMAIL_CHAT_KW = (
    "email", "gmail", "outlook", "whatsapp", "telegram", "slack", "chat",
    "message", "meet", "zoom", "teams", "discord", "send message", "inbox",
    "reply", "compose", "draft email", "text someone",
)
_FILE_DOCS_KW = (
    "file", "folder", "document", "pdf", "word", "excel", "spreadsheet",
    "read file", "write file", "save file", "report", "summarize", "summarise",
    "create doc", "txt", "csv", ".docx", ".xlsx",
)
_BROWSER_KW = (
    "search", "google", "youtube", "website", "url", "open tab", "navigate",
    "browse", "web", "browser", "http", "www", "visit", "chrome", "internet",
    "look up", "find online", "open link",
)


class Router:
    """Classifies tasks into sub-agent domains.
    Uses Claude claude-haiku-4-5 when ANTHROPIC_API_KEY is configured, falls back to keywords."""

    def __init__(self) -> None:
        self._client = None
        self._ready = False
        self._init_claude()

    def _init_claude(self) -> None:
        try:
            from config.settings import get_settings
            s = get_settings()
            key = s.anthropic_api_key
            workspace_id = s.anthropic_workspace_id
        except Exception:
            key = workspace_id = ""
        if not key:
            log.info("Router: no ANTHROPIC_API_KEY — using keyword classifier")
            return
        try:
            import anthropic
            # sk-ant-usr-* keys are user-scoped and require the workspace ID header.
            # sk-ant-api03-* keys are workspace-scoped and work without it.
            extra_headers = {}
            if workspace_id:
                extra_headers["anthropic-workspace-id"] = workspace_id
            elif key.startswith("sk-ant-usr-"):
                log.warning(
                    "Router: user-scoped API key detected (sk-ant-usr-*). "
                    "Add ANTHROPIC_WORKSPACE_ID to .env, or use a workspace key "
                    "from console.anthropic.com — falling back to keyword classifier."
                )
                return
            self._client = anthropic.Anthropic(
                api_key=key,
                default_headers=extra_headers or None,
            )
            self._ready = True
            log.info("Router: Claude claude-haiku-4-5 ready")
        except ImportError:
            log.warning("Router: anthropic package not installed — using keyword classifier")

    def route(self, instruction: str) -> SubAgentConfig:
        """Return the SubAgentConfig for this instruction."""
        agent_type = self._classify(instruction)
        config = _AGENTS.get(agent_type, desktop_agent)
        log.info("Router: [%s] → %s", instruction[:70], config.name)
        return config

    def _classify(self, instruction: str) -> str:
        if self._ready and self._client:
            try:
                msg = self._client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=8,
                    system=_ROUTER_SYSTEM,
                    messages=[{"role": "user", "content": instruction}],
                )
                result = msg.content[0].text.strip().lower()
                if result in _AGENTS:
                    return result
                log.warning("Router: unexpected response '%s' — falling back to keywords", result)
            except Exception as exc:
                log.warning("Router: Claude call failed (%s) — falling back to keywords", exc)

        return self._keyword_classify(instruction)

    def _keyword_classify(self, instruction: str) -> str:
        t = instruction.lower()
        # Desktop-first: close/quit/kill/open/launch an app are always desktop actions.
        _DESKTOP_PRIORITY = (
            "close ", "quit ", "exit ", "kill ", "terminate ", "shut down ",
            "open app", "launch ", "restart ", "minimize ", "maximize ",
            "screenshot", "take a screen", "hotkey", "keyboard shortcut",
        )
        for kw in _DESKTOP_PRIORITY:
            if kw in t:
                return "desktop"
        for kw in _EMAIL_CHAT_KW:
            if kw in t:
                return "email_chat"
        for kw in _FILE_DOCS_KW:
            if kw in t:
                return "file_docs"
        for kw in _BROWSER_KW:
            if kw in t:
                return "browser"
        return "desktop"


_router: Router | None = None


def get_router() -> Router:
    global _router
    if _router is None:
        _router = Router()
    return _router
