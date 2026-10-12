"""Shared Pydantic schemas for inter-module data exchange."""

from __future__ import annotations

from pydantic import BaseModel
from typing import Any


class JobPosting(BaseModel):
    title: str = ""
    url: str = ""
    description: str = ""
    required_skills: list[str] = []
    budget_min: float = 0
    budget_max: float = 0
    hourly: bool = False
    experience_level: str = ""
    client_info: str = ""
    application_questions: list[str] = []


class ProposalResult(BaseModel):
    job_url: str
    job_title: str
    fit_score: int = 0
    recommended: bool = False
    proposal_text: str = ""
    implementation_plan: str = ""
    status: str = "drafted"
    error: str = ""


class BugReport(BaseModel):
    source: str
    reporter: str
    description: str
    thread_id: str = ""
    space_id: str = ""
    project_name: str = ""
    raw_message: str = ""
