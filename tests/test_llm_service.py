"""Tests for LlmService.

All tests mock the Anthropic client — no real API calls are made.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from services.llm_service import FALLBACK_REPLY, LlmService

DEFAULT_MODEL = 'claude-3-5-sonnet-latest'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _svc(model: str | None = None) -> LlmService:
    env = {'CLAUDE_API_KEY': 'test-key'}
    if model is not None:
        env['ANTHROPIC_MODEL'] = model

    with patch.dict('os.environ', env, clear=True):
        svc = LlmService()
    svc._client = MagicMock()
    return svc


def _mock_response(text: str) -> MagicMock:
    msg = MagicMock()
    msg.content[0].text = text
    return msg


# ---------------------------------------------------------------------------
# get_psychological_guidance
# ---------------------------------------------------------------------------

class TestGetPsychologicalGuidance:
    def test_returns_llm_text(self):
        svc = _svc()
        svc._client.messages.create.return_value = _mock_response('1. Try breathing.')
        result = svc.get_psychological_guidance(3, 'feeling anxious')
        assert result == '1. Try breathing.'

    def test_low_mood_uses_600_max_tokens(self):
        svc = _svc()
        svc._client.messages.create.return_value = _mock_response('ok')
        svc.get_psychological_guidance(3, 'bad day')
        _, kwargs = svc._client.messages.create.call_args
        assert kwargs['max_tokens'] == 600

    def test_very_low_mood_uses_600_max_tokens(self):
        svc = _svc()
        svc._client.messages.create.return_value = _mock_response('ok')
        svc.get_psychological_guidance(1, 'crisis')
        _, kwargs = svc._client.messages.create.call_args
        assert kwargs['max_tokens'] == 600

    def test_very_low_mood_prompt_contains_tipp(self):
        svc = _svc()
        captured = {}

        def capture(**kwargs):
            captured['prompt'] = kwargs['messages'][0]['content']
            return _mock_response('ok')

        svc._client.messages.create.side_effect = capture
        svc.get_psychological_guidance(2, 'really struggling')
        assert 'TIPP' in captured['prompt']

    def test_low_mood_prompt_contains_behavioral_activation(self):
        svc = _svc()
        captured = {}

        def capture(**kwargs):
            captured['prompt'] = kwargs['messages'][0]['content']
            return _mock_response('ok')

        svc._client.messages.create.side_effect = capture
        svc.get_psychological_guidance(4, 'rough day')
        assert 'Behavioral Activation' in captured['prompt']

    def test_very_low_mood_prompt_does_not_include_crisis_hotlines(self):
        svc = _svc()
        captured = {}

        def capture(**kwargs):
            captured['prompt'] = kwargs['messages'][0]['content']
            return _mock_response('ok')

        svc._client.messages.create.side_effect = capture
        svc.get_psychological_guidance(1, 'in crisis')
        assert '741741' not in captured['prompt']
        assert 'Samaritans' not in captured['prompt']

    def test_prompt_includes_mood_score(self):
        svc = _svc()
        captured = {}

        def capture(**kwargs):
            captured['prompt'] = kwargs['messages'][0]['content']
            return _mock_response('ok')

        svc._client.messages.create.side_effect = capture
        svc.get_psychological_guidance(3, 'some entry')
        assert '3/10' in captured['prompt']

    def test_prompt_includes_entry_text(self):
        svc = _svc()
        captured = {}

        def capture(**kwargs):
            captured['prompt'] = kwargs['messages'][0]['content']
            return _mock_response('ok')

        svc._client.messages.create.side_effect = capture
        svc.get_psychological_guidance(3, 'my unique entry text')
        assert 'my unique entry text' in captured['prompt']

    def test_api_error_returns_fallback(self):
        svc = _svc()
        svc._client.messages.create.side_effect = Exception('API down')
        result = svc.get_psychological_guidance(3, 'entry')
        assert 'having trouble' in result.lower()


# ---------------------------------------------------------------------------
# _call max_tokens default preserved for existing methods
# ---------------------------------------------------------------------------

class TestCallMaxTokens:
    def test_empathetic_response_uses_512(self):
        svc = _svc()
        svc._client.messages.create.return_value = _mock_response('response')
        svc.get_empathetic_response(7, 'good day')
        _, kwargs = svc._client.messages.create.call_args
        assert kwargs['max_tokens'] == 512

    def test_extract_tags_uses_512(self):
        svc = _svc()
        svc._client.messages.create.return_value = _mock_response('work, stress')
        svc.extract_tags('had a tough day at work')
        _, kwargs = svc._client.messages.create.call_args
        assert kwargs['max_tokens'] == 512


# ---------------------------------------------------------------------------
# model selection
# ---------------------------------------------------------------------------

class TestModelSelection:
    def test_uses_model_from_environment(self):
        svc = _svc(model='claude-test-model')
        svc._client.messages.create.return_value = _mock_response('response')

        svc.get_empathetic_response(7, 'good day')

        _, kwargs = svc._client.messages.create.call_args
        assert kwargs['model'] == 'claude-test-model'

    def test_uses_default_model_when_environment_missing(self):
        svc = _svc()
        svc._client.messages.create.return_value = _mock_response('response')

        svc.get_empathetic_response(7, 'good day')

        _, kwargs = svc._client.messages.create.call_args
        assert kwargs['model'] == DEFAULT_MODEL


# ---------------------------------------------------------------------------
# extract_tags — a failed call must not become a tag
#
# `_call` answers a failure with an apology for a person to read. Split on
# commas, that apology used to be saved as the entry's tags on every outage.
# ---------------------------------------------------------------------------

class TestExtractTagsOnFailure:
    def test_api_error_yields_no_tags(self):
        svc = _svc()
        svc._client.messages.create.side_effect = Exception('API down')
        assert svc.extract_tags('had a tough day at work') == []

    def test_fallback_prose_never_reaches_the_tags(self):
        svc = _svc()
        svc._client.messages.create.side_effect = Exception('API down')
        tags = svc.extract_tags('had a tough day at work')
        assert not any(fragment.strip().lower() in tags for fragment in FALLBACK_REPLY.split(','))

    def test_malformed_response_yields_no_tags(self):
        svc = _svc()
        svc._client.messages.create.return_value = MagicMock(content=[])
        assert svc.extract_tags('had a tough day at work') == []

    def test_successful_call_is_still_parsed(self):
        svc = _svc()
        svc._client.messages.create.return_value = _mock_response('Work, Sleep')
        assert svc.extract_tags('had a tough day at work') == ['work', 'sleep']

    def test_prose_methods_still_fall_back_for_the_reader(self):
        svc = _svc()
        svc._client.messages.create.side_effect = Exception('API down')
        assert svc.get_empathetic_response(5, 'entry') == FALLBACK_REPLY
