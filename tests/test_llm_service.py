"""Tests for LlmService.

All tests mock the Anthropic client — no real API calls are made.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services.llm_service import LlmService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _svc() -> LlmService:
    with patch.dict('os.environ', {'CLAUDE_API_KEY': 'test-key'}):
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
