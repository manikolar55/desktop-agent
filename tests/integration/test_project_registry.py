"""Tests for project registry YAML loading and runtime use."""

import pytest
from pathlib import Path


@pytest.fixture
def registry_yaml(tmp_path):
    content = """
projects:
  - name: "Test App"
    repository_path: "{path}"
    browser_url: "http://localhost:3000"
    test_command: "pytest"
    chat_space_ids:
      - "spaces/ABC"
  - name: "Missing Path App"
    repository_path: "C:/nonexistent/path/that/does/not/exist"
    test_command: "pytest"
""".format(path=str(tmp_path).replace("\\", "/"))
    yaml_file = tmp_path / "projects_test.yaml"
    yaml_file.write_text(content)
    return yaml_file


class TestRegistryLoading:
    def test_valid_project_loaded(self, registry_yaml, monkeypatch):
        monkeypatch.setattr("config.project_registry.REGISTRY_PATH", registry_yaml)
        from config.project_registry import load_registry
        projects = load_registry()
        names = [p.name for p in projects]
        assert "Test App" in names

    def test_nonexistent_repo_skipped(self, registry_yaml, monkeypatch):
        monkeypatch.setattr("config.project_registry.REGISTRY_PATH", registry_yaml)
        from config.project_registry import load_registry
        projects = load_registry()
        names = [p.name for p in projects]
        assert "Missing Path App" not in names

    def test_missing_yaml_returns_empty(self, monkeypatch):
        monkeypatch.setattr(
            "config.project_registry.REGISTRY_PATH",
            Path("config/nonexistent_projects_xyz.yaml")
        )
        from config.project_registry import load_registry
        assert load_registry() == []

    def test_project_fields_parsed_correctly(self, registry_yaml, monkeypatch):
        monkeypatch.setattr("config.project_registry.REGISTRY_PATH", registry_yaml)
        from config.project_registry import load_registry
        projects = load_registry()
        p = next(x for x in projects if x.name == "Test App")
        assert p.browser_url == "http://localhost:3000"
        assert p.test_command == "pytest"
        assert "spaces/ABC" in p.chat_space_ids

    def test_bootstrap_saves_to_preferences(self, registry_yaml, monkeypatch, tmp_path):
        db_file = tmp_path / "reg_test.db"
        monkeypatch.setenv("DB_PATH", str(db_file))
        import threading, importlib
        import storage.database as db_mod
        db_mod._local = threading.local()
        importlib.reload(db_mod)
        db_mod.init_db()
        import storage.repositories as repo_mod
        importlib.reload(repo_mod)

        monkeypatch.setattr("config.project_registry.REGISTRY_PATH", registry_yaml)
        from config.project_registry import bootstrap_registry
        bootstrap_registry()

        saved = repo_mod.pref_repo.get("project_registry", [])
        names = [p["name"] for p in saved]
        assert "Test App" in names


class TestClaudeCodeProjectLookup:
    def test_find_project_by_name(self, monkeypatch):
        monkeypatch.setattr(
            "integrations.claude_code.session.get_project_registry",
            lambda: [{"name": "Alpha", "repository_path": "C:/code/alpha"}]
        )
        from integrations.claude_code.session import find_project
        result = find_project("Alpha")
        assert result is not None
        assert result["name"] == "Alpha"

    def test_unknown_project_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            "integrations.claude_code.session.get_project_registry",
            lambda: []
        )
        from integrations.claude_code.session import find_project
        assert find_project("NoSuchProject") is None

    def test_send_task_fails_gracefully_for_unknown_project(self, monkeypatch):
        monkeypatch.setattr(
            "integrations.claude_code.session.get_project_registry",
            lambda: []
        )
        from integrations.claude_code.session import send_code_task
        result = send_code_task("fix the bug", "UnknownProject")
        assert "not in registry" in result or "not found" in result
