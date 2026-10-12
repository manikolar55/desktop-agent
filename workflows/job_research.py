"""Upwork job research, proposal generation, and PDF implementation plans."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from agent.task_state import Task
from storage.repositories import proposal_repo

log = logging.getLogger(__name__)

SYSTEM_ANALYSE = """
You are a freelance proposal specialist. Analyse the job posting against the developer's profile and produce JSON:
{
  "fit_score": 0-100,
  "technical_fit": "one sentence",
  "scope_clarity": "clear|unclear|partial",
  "risks": ["..."],
  "missing_info": ["..."],
  "recommended": true|false,
  "reason": "..."
}
Only use information present in the posting. Do not invent client details.
Distinguish verified information from assumptions.
""".strip()

SYSTEM_PROPOSE = """
You are writing a freelance proposal on behalf of the configured developer.
Rules:
- Use ONLY the verified skills and experience provided in the profile
- Do NOT invent portfolio projects, testimonials, performance metrics, or client names
- Address the client's actual stated requirements
- Explain a relevant implementation approach
- Highlight only verified experience
- Note assumptions and ask clarifying questions where scope is unclear
- Avoid generic filler phrases ("I am the perfect candidate", "I have extensive experience")
- Be concise and professional
If the profile is missing required fields, note what is missing instead of inventing it.
""".strip()

SYSTEM_IMPL_PLAN = """
You are producing a technical implementation plan for a freelance project.
Produce a structured plan with:
1. Project Scope — what is included and excluded
2. Milestones — named phases with deliverables
3. Technical Approach — architecture, key technologies
4. Timeline Estimate — per milestone, with stated assumptions
5. Acceptance Criteria — how the client can verify completion
6. Open Questions — things that need clarification before starting
7. Risk Register — top 3 risks and mitigations

Base the plan ONLY on the job description and developer profile provided.
State assumptions clearly. Do not promise fixed timelines for undefined scope.
""".strip()


def upwork_tool(tool: str, params: dict, task: Task) -> str:
    if tool == "upwork_search":
        return _search(params)
    if tool == "upwork_analyse":
        return _analyse(params)
    if tool == "upwork_propose":
        return _propose(params, task)
    if tool == "upwork_implementation_plan":
        return _implementation_plan(params, task)
    if tool == "upwork_process_queue":
        return _process_job_queue(params, task)
    return f"Unknown Upwork tool: {tool}"


def _search(params: dict) -> str:
    keywords = params.get("keywords", "")
    return (
        f"[Upwork Search] Automated job search requires Upwork API approval (client ID + secret).\n"
        f"Manual workflow: open Upwork → search '{keywords}' → paste each job description here.\n"
        f"Alternatively, provide job URLs and I will use the browser to read the posting."
    )


def _analyse(params: dict) -> str:
    job_text = params.get("job_text", "")
    job_url = params.get("job_url", "")
    if not job_text and job_url:
        job_text = _fetch_job_text(job_url)
    if not job_text:
        return "No job text provided. Paste the job description or provide a URL."

    from models.provider import get_provider
    from storage.repositories import pref_repo
    profile = pref_repo.get("upwork_profile", {})
    profile_str = _format_profile(profile)

    prompt = f"Job posting:\n{job_text[:3000]}\n\nDeveloper profile:\n{profile_str}"
    provider = get_provider()
    result = provider.json_complete(SYSTEM_ANALYSE, prompt)

    score = result.get("fit_score", 0)
    recommended = result.get("recommended", False)
    risks = result.get("risks", [])
    missing = result.get("missing_info", [])

    lines = [
        f"Fit score: {score}/100 | Recommended: {'Yes' if recommended else 'No'}",
        f"Technical fit: {result.get('technical_fit', '')}",
        f"Scope clarity: {result.get('scope_clarity', 'unknown')}",
        f"Reason: {result.get('reason', '')}",
    ]
    if risks:
        lines.append(f"Risks: {'; '.join(risks)}")
    if missing:
        lines.append(f"Missing info: {'; '.join(missing)}")
    return "\n".join(lines)


def _propose(params: dict, task: Task) -> str:
    job_url = params.get("job_url", "")
    job_title = params.get("job_title", "Unknown Job")
    job_text = params.get("job_text", "")

    if not job_text and job_url:
        job_text = _fetch_job_text(job_url)
    if not job_text:
        return "Cannot write proposal: no job description provided."

    if job_url and proposal_repo.already_applied(job_url):
        return f"Already drafted/submitted for {job_url} — skipping duplicate."

    from models.provider import get_provider
    from storage.repositories import pref_repo
    profile = pref_repo.get("upwork_profile", {})
    profile_str = _format_profile(profile)

    complete, missing = _profile_complete(profile)
    if not complete:
        return (
            f"Cannot generate proposal — profile is missing: {', '.join(missing)}. "
            f"Open Settings → Upwork Profile to complete it."
        )

    prompt = f"Job posting:\n{job_text[:3000]}\n\nDeveloper profile:\n{profile_str}"
    provider = get_provider()
    proposal_text = provider.complete(SYSTEM_PROPOSE, prompt, max_tokens=1024)

    if job_url:
        proposal_repo.save(job_url, job_title, "upwork", proposal_text)

    output = f"PROPOSAL ({len(proposal_text)} chars):\n\n{proposal_text}"

    # Optionally generate PDF too
    if params.get("generate_pdf", False):
        pdf_result = _implementation_plan(params, task)
        output += f"\n\n---\n{pdf_result}"

    return output


def _implementation_plan(params: dict, task: Task) -> str:
    job_text = params.get("job_text", "")
    job_title = params.get("job_title", "Project")
    if not job_text:
        return "No job description provided for implementation plan."

    from models.provider import get_provider
    from storage.repositories import pref_repo
    profile = pref_repo.get("upwork_profile", {})
    profile_str = _format_profile(profile)

    prompt = f"Job posting:\n{job_text[:3000]}\n\nDeveloper profile:\n{profile_str}"
    provider = get_provider()
    plan_text = provider.complete(SYSTEM_IMPL_PLAN, prompt, max_tokens=1500)

    # Save as PDF
    from workflows.documents import draft_document
    result = draft_document({
        "title": f"Implementation Plan — {job_title}",
        "content": plan_text,
        "format": "pdf",
        "output_dir": "data/proposals",
    })
    return f"Implementation plan generated.\n{result}\n\nPlan preview:\n{plan_text[:500]}..."


def _process_job_queue(params: dict, task: Task) -> str:
    """
    Process a queue of job URLs or job texts sequentially.
    Stops when the queue is exhausted, the task is cancelled, or the max limit is reached.
    """
    jobs: list[dict] = params.get("jobs", [])
    max_proposals = params.get("max_proposals", 10)
    min_fit_score = params.get("min_fit_score", 60)

    if not jobs:
        return "No jobs in queue. Provide a list of {'job_url': ..., 'job_text': ..., 'job_title': ...} dicts."

    results = []
    processed = 0

    for job in jobs:
        if task.cancelled:
            results.append("Queue processing stopped by cancellation.")
            break
        if processed >= max_proposals:
            results.append(f"Reached max_proposals limit ({max_proposals}). Stopping.")
            break

        url = job.get("job_url", "")
        if url and proposal_repo.already_applied(url):
            results.append(f"SKIP (duplicate): {url}")
            continue

        # Analyse first
        analysis = _analyse(job)
        score_line = next((l for l in analysis.splitlines() if "Fit score" in l), "")
        try:
            score = int(score_line.split(":")[1].split("/")[0].strip())
        except Exception:
            score = 0

        if score < min_fit_score:
            results.append(f"SKIP (score {score}<{min_fit_score}): {job.get('job_title', url)}")
            continue

        proposal_result = _propose(job, task)
        results.append(
            f"PROPOSED [{score}/100]: {job.get('job_title', url)}\n"
            f"{proposal_result[:200]}..."
        )
        processed += 1

    summary = f"Processed {processed}/{len(jobs)} jobs."
    return summary + "\n\n" + "\n---\n".join(results)


def _fetch_job_text(url: str) -> str:
    """Use the browser to read a job posting URL."""
    try:
        from browser.manager import get_browser_manager
        bm = get_browser_manager()
        bm.navigate(url)
        return bm.read_page()[:4000]
    except Exception as exc:
        log.error("Failed to fetch job URL %s: %s", url, exc)
        return ""


def _format_profile(profile: dict) -> str:
    if not profile or not any(profile.values()):
        return (
            "[Profile not configured — open Settings → Upwork Profile to add your "
            "verified skills, experience, and preferences. "
            "Profile information is required before proposals can be generated.]"
        )
    lines = []
    field_labels = {
        "name": "Name",
        "title": "Title",
        "skills": "Skills",
        "languages": "Languages",
        "frameworks": "Frameworks",
        "experience_years": "Years of experience",
        "portfolio_projects": "Verified portfolio projects",
        "achievements": "Achievements",
        "preferred_categories": "Preferred project types",
        "hourly_rate_usd": "Hourly rate (USD)",
        "availability": "Availability",
        "proposal_preferences": "Proposal preferences",
    }
    for key, label in field_labels.items():
        val = profile.get(key)
        if val:
            if isinstance(val, list):
                val = ", ".join(str(v) for v in val) if val else ""
            if val:
                lines.append(f"{label}: {val}")
    return "\n".join(lines) if lines else "[Empty profile]"


def _profile_complete(profile: dict) -> tuple[bool, list[str]]:
    missing = []
    if not profile.get("name"):
        missing.append("name")
    if not profile.get("skills"):
        missing.append("skills")
    if not profile.get("experience_years"):
        missing.append("experience_years")
    return len(missing) == 0, missing
