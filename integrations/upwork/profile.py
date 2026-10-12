"""Upwork user profile configuration — stored in local preferences."""

from __future__ import annotations

from storage.repositories import pref_repo

DEFAULT_PROFILE: dict = {
    "name": "",
    "title": "",
    "skills": [],
    "languages": [],
    "frameworks": [],
    "experience_years": 0,
    "portfolio_projects": [],
    "achievements": [],
    "preferred_categories": [],
    "min_budget_usd": 500,
    "hourly_rate_usd": 0,
    "availability": "full_time",
    "engagement_type": "any",
    "restrictions": [],
    "proposal_preferences": "",
}


def get_profile() -> dict:
    return pref_repo.get("upwork_profile", DEFAULT_PROFILE)


def save_profile(profile: dict) -> None:
    for key in DEFAULT_PROFILE:
        if key not in profile:
            profile[key] = DEFAULT_PROFILE[key]
    pref_repo.set("upwork_profile", profile)


def profile_is_complete() -> tuple[bool, list[str]]:
    profile = get_profile()
    missing = []
    if not profile.get("name"):
        missing.append("name")
    if not profile.get("skills"):
        missing.append("skills")
    if not profile.get("experience_years"):
        missing.append("experience_years")
    return len(missing) == 0, missing
