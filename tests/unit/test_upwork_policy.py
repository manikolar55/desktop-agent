"""Tests for Upwork proposal policy — no fabrication, duplicate prevention."""

import pytest


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    db_file = tmp_path / "upwork_test.db"
    monkeypatch.setenv("DB_PATH", str(db_file))
    import threading, importlib
    import storage.database as db_mod
    db_mod._local = threading.local()
    importlib.reload(db_mod)
    db_mod.init_db()
    import storage.repositories as repo_mod
    importlib.reload(repo_mod)
    yield db_file


class TestProposalDuplicatePrevention:
    def test_already_applied_false_for_new_url(self, fresh_db):
        import importlib
        import storage.repositories as repo_mod
        importlib.reload(repo_mod)
        repo = repo_mod.ProposalRepository()
        assert repo.already_applied("https://upwork.com/jobs/new") is False

    def test_already_applied_true_after_save(self, fresh_db):
        import importlib
        import storage.repositories as repo_mod
        importlib.reload(repo_mod)
        repo = repo_mod.ProposalRepository()
        url = "https://upwork.com/jobs/~01abc"
        repo.save(url, "Test Job", "upwork", "My proposal text")
        assert repo.already_applied(url) is True

    def test_second_save_updates_not_duplicates(self, fresh_db):
        import importlib
        import storage.repositories as repo_mod
        importlib.reload(repo_mod)
        repo = repo_mod.ProposalRepository()
        url = "https://upwork.com/jobs/~02abc"
        repo.save(url, "Job A", "upwork", "proposal v1")
        repo.save(url, "Job A", "upwork", "proposal v2")
        recent = repo.list_recent(5)
        assert len([r for r in recent if r["job_url"] == url]) == 1

    def test_mark_submitted_updates_status(self, fresh_db):
        import importlib
        import storage.repositories as repo_mod
        importlib.reload(repo_mod)
        repo = repo_mod.ProposalRepository()
        url = "https://upwork.com/jobs/~03abc"
        repo.save(url, "Job B", "upwork", "proposal")
        repo.mark_submitted(url)
        recent = repo.list_recent(5)
        match = next(r for r in recent if r["job_url"] == url)
        assert match["status"] == "submitted"
        assert match["submitted_at"] is not None


class TestProfileCompleteness:
    def test_empty_profile_is_incomplete(self, fresh_db):
        from integrations.upwork.profile import profile_is_complete
        complete, missing = profile_is_complete()
        assert complete is False
        assert "name" in missing or "skills" in missing

    def test_profile_with_required_fields_is_complete(self, fresh_db):
        import importlib
        import storage.repositories as repo_mod
        importlib.reload(repo_mod)
        from integrations.upwork.profile import save_profile, profile_is_complete
        save_profile({
            "name": "Test User",
            "skills": ["Python", "React"],
            "experience_years": 5,
        })
        complete, missing = profile_is_complete()
        assert complete is True
        assert missing == []
