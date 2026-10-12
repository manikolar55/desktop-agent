"""Claude Code terminal session integration."""

from __future__ import annotations

import logging
import subprocess
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_session_lock = threading.Lock()


def get_project_registry() -> list[dict]:
    from storage.repositories import pref_repo
    return pref_repo.get("project_registry", [])


def find_project(name: str) -> dict | None:
    for p in get_project_registry():
        if p.get("name", "").lower() == name.lower():
            return p
    return None


def list_projects() -> list[str]:
    return [p.get("name", "") for p in get_project_registry()]


def session_is_ready(project: dict) -> tuple[bool, str]:
    """
    Check whether the Claude Code CLI is available and the project repo exists.
    Returns (ready: bool, reason: str).
    """
    repo_path = project.get("repository_path", "")
    if not repo_path or not Path(repo_path).exists():
        return False, f"Repository path does not exist: {repo_path}"

    result = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=5)
    if result.returncode != 0:
        return False, "claude CLI not found on PATH"

    return True, "ready"


def send_code_task(
    instruction: str,
    project_name: str = "",
    timeout_seconds: int = 300,
) -> str:
    """
    Send a coding task to Claude Code via the CLI `--print` flag.

    This is the safe, supported non-interactive interface. It runs the task
    in the project repository directory and returns stdout.

    We do NOT type into a running terminal window because:
    - There is no stable API for it
    - It risks interrupting unrelated work in the terminal
    - Output capture is unreliable

    For interactive use, the user should run claude in the repo directory themselves.
    """
    project = find_project(project_name) if project_name else None
    if project_name and not project:
        return (
            f"[Claude Code] Project '{project_name}' not in registry. "
            f"Available: {list_projects() or ['none — configure config/projects.yaml']}"
        )

    repo_path = project.get("repository_path", "") if project else ""
    if not repo_path or not Path(repo_path).exists():
        return (
            f"[Claude Code] Repository path missing or inaccessible: '{repo_path}'. "
            f"Update config/projects.yaml."
        )

    ready, reason = session_is_ready(project)
    if not ready:
        return f"[Claude Code] Not ready: {reason}"

    log.info("Sending code task to Claude Code in %s: %s", repo_path, instruction[:80])

    with _session_lock:
        try:
            result = subprocess.run(
                ["claude", "--print", instruction],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            output = result.stdout.strip()
            if result.returncode != 0:
                stderr = result.stderr.strip()[:500]
                log.error("Claude Code exited %d: %s", result.returncode, stderr)
                output += f"\n[exit {result.returncode}] {stderr}"
            log.info("Claude Code task completed (exit %d)", result.returncode)
            return output[:6000] or "[No output]"
        except FileNotFoundError:
            return "[Claude Code] 'claude' not found on PATH. Install Claude Code CLI."
        except subprocess.TimeoutExpired:
            return f"[Claude Code] Task timed out after {timeout_seconds}s"
        except Exception as exc:
            return f"[Claude Code] Unexpected error: {exc}"


def run_project_command(project_name: str, command_key: str) -> tuple[bool, str]:
    """
    Run a configured project command (test, build, lint, dev_server).
    Returns (success, output).
    """
    project = find_project(project_name)
    if not project:
        return False, f"Project '{project_name}' not found"

    cmd = project.get(command_key, "")
    if not cmd:
        return False, f"No '{command_key}' configured for project '{project_name}'"

    repo_path = project.get("repository_path", ".")
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            cwd=repo_path, timeout=120,
        )
        output = (result.stdout + result.stderr)[:3000]
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, f"Command timed out: {cmd}"
    except Exception as exc:
        return False, str(exc)
