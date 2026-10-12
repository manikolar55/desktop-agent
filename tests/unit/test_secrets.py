"""Tests for credential redaction."""

from security.secrets import redact


class TestRedact:
    def test_anthropic_key_redacted(self):
        text = 'key = "sk-ant-abc123xyz"'
        result = redact(text)
        assert "sk-ant" not in result
        assert "[REDACTED]" in result

    def test_openai_key_redacted(self):
        text = "Bearer sk-abcdefg12345 in header"
        result = redact(text)
        assert "sk-abcdefg" not in result

    def test_safe_text_unchanged(self):
        text = "Hello world, this is safe text."
        assert redact(text) == text

    def test_multiple_secrets_redacted(self):
        text = "key1=sk-abc key2=sk-def done"
        result = redact(text)
        assert "sk-abc" not in result
        assert "sk-def" not in result
        assert result.count("[REDACTED]") == 2
