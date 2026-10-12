"""Tests for the voice command parser."""

from voice.commands import parse_command, CommandIntent


class TestStopCommands:
    def test_stop_everything(self):
        for phrase in ["stop everything", "Stop Everything", "cancel all", "emergency stop", "halt"]:
            assert parse_command(phrase).intent == CommandIntent.STOP_EVERYTHING

    def test_cancel_current(self):
        for phrase in ["stop this task", "cancel current task", "stop", "cancel the operation"]:
            assert parse_command(phrase).intent == CommandIntent.CANCEL_CURRENT


class TestControlCommands:
    def test_pause(self):
        assert parse_command("pause").intent == CommandIntent.PAUSE
        assert parse_command("hold on").intent == CommandIntent.PAUSE

    def test_resume(self):
        assert parse_command("continue").intent == CommandIntent.RESUME
        assert parse_command("resume").intent == CommandIntent.RESUME
        assert parse_command("go ahead").intent == CommandIntent.RESUME


class TestQueryCommands:
    def test_status_query(self):
        for phrase in ["what are you doing", "what is happening", "status"]:
            assert parse_command(phrase).intent == CommandIntent.STATUS_QUERY

    def test_explain_error(self):
        for phrase in ["what went wrong", "explain the error", "why did it fail"]:
            assert parse_command(phrase).intent == CommandIntent.EXPLAIN_ERROR


class TestConfirmDeny:
    def test_confirm(self):
        for phrase in ["yes", "yeah", "approve", "confirm", "ok", "okay"]:
            assert parse_command(phrase).intent == CommandIntent.CONFIRM

    def test_deny(self):
        for phrase in ["no", "nope", "deny", "reject"]:
            assert parse_command(phrase).intent == CommandIntent.DENY


class TestNewTask:
    def test_arbitrary_instruction_is_new_task(self):
        cmd = parse_command("Open my browser and go to Upwork")
        assert cmd.intent == CommandIntent.NEW_TASK
        assert "Upwork" in cmd.task_instruction

    def test_task_instruction_preserved(self):
        cmd = parse_command("Research Python jobs and save a report")
        assert cmd.task_instruction == "Research Python jobs and save a report"
