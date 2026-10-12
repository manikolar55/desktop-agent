"""SubAgentConfig: bundles a focused system prompt + allowed tools for one domain."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SubAgentConfig:
    name: str
    system_prompt: str
    allowed_tools: list[str] = field(default_factory=list)
    agentic: bool = True  # step-by-step reactive loop; coordinates from screen_read
