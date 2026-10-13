"""Provider-independent LLM interface with Ollama, Anthropic, and OpenAI backends."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

import httpx

from config.settings import get_settings

log = logging.getLogger(__name__)


class LLMProvider(ABC):
    @abstractmethod
    def complete(self, system: str, user: str, max_tokens: int = 2048) -> str: ...

    @abstractmethod
    def name(self) -> str: ...

    def complete_with_image(
        self, system: str, prompt: str, image_b64: str,
        media_type: str = "image/png", max_tokens: int = 1024,
    ) -> str:
        return f"[Vision not supported by {self.name()}]"

    def json_complete(self, system: str, user: str, max_tokens: int = 2048) -> Any:
        raw = self.complete(system, user + "\n\nRespond with valid JSON only.", max_tokens)
        try:
            start = raw.find("{") if "{" in raw else raw.find("[")
            end = raw.rfind("}") + 1 if "{" in raw else raw.rfind("]") + 1
            return json.loads(raw[start:end])
        except Exception:
            log.warning("LLM did not return valid JSON: %s", raw[:300])
            return {}


class OllamaProvider(LLMProvider):
    def __init__(self) -> None:
        s = get_settings()
        self._base_url = s.ollama_base_url.rstrip("/")
        self._model = s.ollama_model

    def name(self) -> str:
        return f"ollama/{self._model}"

    def complete(self, system: str, user: str, max_tokens: int = 2048) -> str:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        try:
            resp = httpx.post(
                f"{self._base_url}/api/chat",
                json=payload,
                timeout=120,
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"]
        except Exception as exc:
            log.error("Ollama request failed: %s", exc)
            raise


class AnthropicProvider(LLMProvider):
    def __init__(self) -> None:
        import anthropic
        s = get_settings()
        extra_headers = {}
        if s.anthropic_workspace_id:
            extra_headers["anthropic-workspace-id"] = s.anthropic_workspace_id
        self._client = anthropic.Anthropic(
            api_key=s.anthropic_api_key,
            default_headers=extra_headers or None,
        )

    def name(self) -> str:
        return "anthropic/claude-haiku-4-5"

    def complete(self, system: str, user: str, max_tokens: int = 2048) -> str:
        msg = self._client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return msg.content[0].text

    def complete_with_image(
        self, system: str, prompt: str, image_b64: str,
        media_type: str = "image/png", max_tokens: int = 1024,
    ) -> str:
        msg = self._client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": media_type, "data": image_b64,
                }},
                {"type": "text", "text": prompt},
            ]}],
        )
        return msg.content[0].text


class OpenAIProvider(LLMProvider):
    def __init__(self) -> None:
        import openai
        s = get_settings()
        self._client = openai.OpenAI(api_key=s.openai_api_key)

    def name(self) -> str:
        return "openai/gpt-4o"

    def complete(self, system: str, user: str, max_tokens: int = 2048) -> str:
        resp = self._client.chat.completions.create(
            model="gpt-4o",
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content or ""


class StubProvider(LLMProvider):
    """Fallback when no AI provider is configured — returns structured stubs."""

    def name(self) -> str:
        return "stub"

    def complete(self, system: str, user: str, max_tokens: int = 2048) -> str:
        return (
            "I am running without an AI provider. "
            "Please configure ANTHROPIC_API_KEY, OPENAI_API_KEY, or ensure Ollama is running."
        )

    def json_complete(self, system: str, user: str, max_tokens: int = 2048) -> Any:
        return {
            "objective": "stub objective",
            "steps": [{"description": "No AI provider configured", "tool": "none"}],
            "risk_level": "low",
        }


def build_provider() -> LLMProvider:
    s = get_settings()
    if s.ai_provider == "anthropic" and s.anthropic_api_key:
        return AnthropicProvider()
    if s.ai_provider == "openai" and s.openai_api_key:
        return OpenAIProvider()
    if s.ai_provider == "ollama":
        try:
            p = OllamaProvider()
            p.complete("ping", "pong", max_tokens=1)
            return p
        except Exception:
            log.warning("Ollama not reachable; falling back to stub provider")
    return StubProvider()


_provider: LLMProvider | None = None


def get_provider() -> LLMProvider:
    global _provider
    if _provider is None:
        _provider = build_provider()
    return _provider


def reset_provider() -> None:
    global _provider
    _provider = None
