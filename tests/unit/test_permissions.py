"""Tests for permission and risk-level classification."""

from config.permissions import Action, RiskLevel, risk_level_for, requires_approval


class TestRiskLevels:
    def test_read_public_url_is_low(self):
        assert risk_level_for(Action.READ_PUBLIC_URL) == RiskLevel.LOW

    def test_edit_file_is_medium(self):
        assert risk_level_for(Action.EDIT_PROJECT_FILE) == RiskLevel.MEDIUM

    def test_delete_file_is_high(self):
        assert risk_level_for(Action.DELETE_FILE) == RiskLevel.HIGH

    def test_submit_application_is_high(self):
        assert risk_level_for(Action.SUBMIT_APPLICATION) == RiskLevel.HIGH

    def test_make_purchase_is_high(self):
        assert risk_level_for(Action.MAKE_PURCHASE) == RiskLevel.HIGH


class TestRequiresApproval:
    def test_high_risk_always_requires_approval(self):
        assert requires_approval(Action.DELETE_FILE) is True
        assert requires_approval(Action.DEPLOY_SOFTWARE) is True

    def test_low_risk_never_requires_approval(self):
        assert requires_approval(Action.READ_PUBLIC_URL) is False
        assert requires_approval(Action.NAVIGATE_WEBSITE) is False

    def test_medium_risk_requires_approval_without_auto_set(self):
        assert requires_approval(Action.EDIT_PROJECT_FILE) is True

    def test_medium_risk_skipped_when_auto_approved(self):
        auto = {Action.EDIT_PROJECT_FILE}
        assert requires_approval(Action.EDIT_PROJECT_FILE, auto) is False

    def test_high_risk_not_skipped_even_if_in_auto_set(self):
        auto = {Action.DELETE_FILE}
        assert requires_approval(Action.DELETE_FILE, auto) is True
