"""Head agent router: classifies a task into the right sub-agent domain."""

from __future__ import annotations

import logging

from agent.subagents.base import SubAgentConfig
from agent.subagents.browser import browser_agent
from agent.subagents.desktop import desktop_agent
from agent.subagents.email_chat import email_chat_agent
from agent.subagents.file_docs import file_docs_agent
from agent.subagents.system_explorer import system_explorer_agent
from agent.subagents.voice_qa import voice_qa_agent
from agent.subagents.discussion import discussion_agent

log = logging.getLogger(__name__)

_AGENTS: dict[str, SubAgentConfig] = {
    "browser":         browser_agent,
    "desktop":         desktop_agent,
    "email_chat":      email_chat_agent,
    "file_docs":       file_docs_agent,
    "system_explorer": system_explorer_agent,
    "voice_qa":        voice_qa_agent,
    "discussion":      discussion_agent,
}

_ROUTER_SYSTEM = """
You are a task router for an AI desktop assistant.
Classify the user's task into exactly ONE of these agent types:

browser         — opening URLs, web search, YouTube, navigating to any website (Upwork, Gmail, GitHub, etc.)
desktop         — opening/closing LOCAL apps (Notepad, Calculator, VS Code), clicking UI, keyboard shortcuts, screenshots, window management
email_chat      — composing/reading email (Gmail/Outlook), chat messages (WhatsApp/Slack/Telegram), video calls
file_docs       — reading/writing local files, Word/Excel/PDF documents, summarising text, creating reports
system_explorer — finding files on the computer by name, listing folder contents, opening files by name
voice_qa        — answering questions verbally: what is X, how does Y work, explain Z, calculate, define
discussion      — processing long spoken transcripts: meeting notes, dictation, summarise what I said

KEY RULES:
- Any website/online service → browser
- Opening a LOCAL app → desktop
- "where is", "find file", "locate my" → system_explorer
- Questions about what is on the user's SCREEN or what they have open right now
  ("what's on my screen", "which project is open in PyCharm", "what am I doing",
  "read my screen", "look at my screen") → desktop
- Questions starting with what/how/why/explain/define/calculate/tell me → voice_qa
- "summarise what I said", "take notes", "what did I say", "discussion notes" → discussion

Reply with ONLY the agent type word. Nothing else.

Examples:
"Open YouTube" → browser
"Open Upwork" → browser
"Take a screenshot" → desktop
"Open Notepad" → desktop
"Close Chrome" → desktop
"What is on my screen right now?" → desktop
"Which project do I have open in PyCharm?" → desktop
"Look at my screen and tell me what I'm doing" → desktop
"Check my Gmail" → email_chat
"Send a WhatsApp message to John" → email_chat
"Where is my CV?" → system_explorer
"Find the PDF I downloaded" → system_explorer
"Open my resume" → system_explorer
"What files are on my desktop?" → system_explorer
"Read the PDF at C:/report.pdf" → file_docs
"Save this text to a file" → file_docs
"What is Python?" → voice_qa
"How does machine learning work?" → voice_qa
"What is 15 percent of 200?" → voice_qa
"Explain what a CPU does" → voice_qa
"Define blockchain" → voice_qa
"Summarise what I just said" → discussion
"Take notes on this discussion" → discussion
"What did I say?" → discussion
""".strip()

# Keywords used when Claude API is unavailable
_SYSTEM_EXPLORER_KW = (
    "where is", "where is my", "find file", "find the file", "find my",
    "locate", "which folder", "what folder", "open my cv", "open my resume",
    "open the file", "open the pdf", "open the video", "open the photo",
    "show downloads", "show desktop files", "list files", "list my files",
    "what files", "find pdf", "find excel", "find word", "find the document",
    "find the video", "find the image", "find the photo", "find the folder",
    "my documents", "my downloads", "my desktop files",
)

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

        # Screen questions — need the desktop agent's screen_ask, not plain Q&A
        _SCREEN_KW = (
            "my screen", "the screen", "on screen", "currently open", "open right now",
            "i have open", "i opened", "i am doing", "i'm doing", "which project",
            "what window", "which window", "what app is",
        )
        if any(kw in t for kw in _SCREEN_KW):
            return "desktop"

        # Voice Q&A — direct questions (no computer action)
        _QA_KW = (
            "what is ", "what are ", "how does ", "how do ", "how is ",
            "why is ", "why does ", "explain ", "define ", "tell me about",
            "calculate ", "what's the difference", "how many ", "how much ",
        )
        for kw in _QA_KW:
            if t.startswith(kw):
                return "voice_qa"

        # Discussion — long spoken content processing
        _DISCUSSION_KW = (
            "summarise what i said", "summarize what i said",
            "what did i say", "take notes", "discussion notes",
            "note this down", "save this discussion", "what did we discuss",
        )
        for kw in _DISCUSSION_KW:
            if kw in t:
                return "discussion"

        # System explorer — file-finding queries
        for kw in _SYSTEM_EXPLORER_KW:
            if kw in t:
                return "system_explorer"

        # Browser-priority: opening a named website always goes to browser.
        _BROWSER_SITES = (
            "youtube", "upwork", "gmail", "google", "github", "linkedin",
            "twitter", "facebook", "instagram", "netflix", "amazon", "reddit",
            "wikipedia", "stackoverflow", "trello", "notion", "figma", "canva",
        )
        for site in _BROWSER_SITES:
            if site in t:
                return "browser"

        # Desktop-first: close/quit/kill/open/launch a local app are desktop actions.
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
