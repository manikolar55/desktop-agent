"""Load and validate the project registry from projects.yaml."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

REGISTRY_PATH = Path("config/projects.yaml")
EXAMPLE_PATH = Path("config/projects.example.yaml")


class ProjectConfig(BaseModel):
    name: str
    repository_path: str
    pycharm_project_path: str = ""
    browser_url: str = ""
    dev_server_command: str = ""
    test_command: str = ""
    build_command: str = ""
    lint_command: str = ""
    claude_code_session_id: str = ""
    chat_space_ids: list[str] = Field(default_factory=list)
    verification_checklist: list[str] = Field(default_factory=list)

    def repo_exists(self) -> bool:
        return bool(self.repository_path) and Path(self.repository_path).exists()


def load_registry() -> list[ProjectConfig]:
    path = REGISTRY_PATH if REGISTRY_PATH.exists() else None
    if path is None:
        log.info("No projects.yaml found — project registry is empty. Copy config/projects.example.yaml to config/projects.yaml to configure projects.")
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        projects = []
        for raw in data.get("projects", []):
            try:
                p = ProjectConfig(**raw)
                if not p.repo_exists():
                    log.warning("Project '%s': repository_path '%s' does not exist — skipping", p.name, p.repository_path)
                    continue
                projects.append(p)
            except Exception as exc:
                log.error("Invalid project config entry: %s — %s", raw.get("name", "?"), exc)
        log.info("Loaded %d valid projects from registry", len(projects))
        return projects
    except Exception as exc:
        log.error("Failed to load projects.yaml: %s", exc)
        return []


def save_to_preferences(projects: list[ProjectConfig]) -> None:
    from storage.repositories import pref_repo
    pref_repo.set("project_registry", [p.model_dump() for p in projects])


def bootstrap_registry() -> list[ProjectConfig]:
    """Load YAML registry and persist to preferences DB for runtime use."""
    projects = load_registry()
    save_to_preferences(projects)
    return projects
