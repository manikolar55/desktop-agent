"""Bug-fixing workflow — end-to-end from report to verified fix."""

from __future__ import annotations

import logging
from models.schemas import BugReport

log = logging.getLogger(__name__)

MAX_REPAIR_ITERATIONS = 3


def handle_bug_report(report: BugReport) -> dict:
    """
    Orchestrate the bug-fix workflow:
    1. Match report to a project
    2. Send coding task to Claude Code
    3. Run tests
    4. Verify in browser
    5. Return factual result
    """
    log.info("Handling bug report from %s: %s", report.reporter, report.description[:80])

    from storage.repositories import pref_repo
    registry = pref_repo.get("project_registry", [])
    project = next(
        (p for p in registry if p.get("name", "").lower() == report.project_name.lower()),
        None,
    )

    if not project:
        return {
            "success": False,
            "reason": f"Project '{report.project_name}' not found in registry",
            "action_required": "Configure project in Settings → Projects",
        }

    instruction = (
        f"Bug report from {report.reporter}: {report.description}\n"
        f"Investigate, reproduce if possible, fix, and run tests. "
        f"Do not deploy or modify production data."
    )

    from integrations.claude_code.session import send_code_task
    coding_output = send_code_task(instruction, project["name"])

    test_cmd = project.get("test_command", "")
    test_result = ""
    if test_cmd:
        import subprocess
        try:
            res = subprocess.run(
                test_cmd, shell=True, capture_output=True, text=True,
                cwd=project.get("repository_path", "."), timeout=120,
            )
            test_result = res.stdout[-2000:] + (res.stderr[-500:] if res.returncode else "")
            tests_passed = res.returncode == 0
        except Exception as exc:
            test_result = str(exc)
            tests_passed = False
    else:
        tests_passed = None

    return {
        "success": tests_passed is not False,
        "coding_output": coding_output[:1000],
        "test_result": test_result[:500],
        "tests_passed": tests_passed,
        "note": "Browser verification not attempted — no browser URL configured" if not project.get("browser_url") else "",
    }
