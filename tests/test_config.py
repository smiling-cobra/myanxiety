"""Tests for the startup configuration check."""
import pytest

from config import REQUIRED, missing_config, require_config

COMPLETE = {'TELEGRAM_TOKEN': 't', 'CLAUDE_API_KEY': 'k', 'MONGODB_URI': 'mongodb://localhost'}


class TestMissingConfig:
    def test_nothing_missing(self):
        assert missing_config(COMPLETE) == []

    def test_every_missing_variable_is_named(self):
        assert missing_config({}) == list(REQUIRED)

    @pytest.mark.parametrize('blank', ['', '   '])
    def test_a_blank_value_counts_as_missing(self, blank):
        """`.env.example` ships `TELEGRAM_TOKEN=`, which loads as an empty string."""
        assert missing_config({**COMPLETE, 'TELEGRAM_TOKEN': blank}) == ['TELEGRAM_TOKEN']

    def test_the_model_is_optional(self):
        assert 'ANTHROPIC_MODEL' not in REQUIRED


class TestRequireConfig:
    def test_passes_when_complete(self):
        require_config(COMPLETE)

    def test_exits_naming_what_is_missing(self, caplog):
        with pytest.raises(SystemExit) as exc:
            require_config({'CLAUDE_API_KEY': 'k'})
        assert exc.value.code == 1
        assert 'TELEGRAM_TOKEN, MONGODB_URI' in caplog.text
