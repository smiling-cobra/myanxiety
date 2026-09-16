"""Tests for the deterministic crisis lexicon.

The asymmetry in this file is the point. False negatives are the failure mode
that can hurt someone, so the matching cases are exhaustive and the
non-matching cases are a short list of ordinary journal sentences. Phrases that
match "wrongly" — "I could kill myself for forgetting my keys" — are asserted
as matching on purpose: that is the documented trade, and a future change that
makes them stop matching should have to edit a test that says so.
"""
from __future__ import annotations

import pytest

from services.safety import HOPELESSNESS, SELF_HARM, SUICIDAL_INTENT, detect_crisis


class TestSuicidalIntent:
    @pytest.mark.parametrize('text', [
        'I want to kill myself',
        'I keep thinking about killing myself',
        'i want to kill my self',
        'I am suicidal',
        'had suicidal thoughts all week',
        'thinking about suicide again',
        'I want to end my life',
        'sometimes I think about ending my own life',
        'I might take my own life',
        'I just want to end it all',
        'I want to die',
        'i wanna die honestly',
        'I wish I was dead',
        'I wish I were dead',
        'everyone would be better off dead without me',
        "I don't want to live anymore",
        'i dont want to be here',
        "I don't want to wake up tomorrow",
        'there is no reason to live',
        'no point in living',
        'life is not worth living',
        'kms',
        'thought about unalive',
        'I thought about hanging myself',
    ])
    def test_matches(self, text):
        assert SUICIDAL_INTENT in detect_crisis(text)


class TestSelfHarm:
    @pytest.mark.parametrize('text', [
        'I have been self-harming',
        'self harm urges are back',
        'I selfharm when it gets bad',
        'I was cutting myself last night',
        'I cut myself again',
        'I want to hurt myself',
        'thinking of harming myself',
        'I burned myself on purpose',
        'I harmed myself again',
        'I hurt myself last night',
        'I thought about an overdose',
        'I overdosed last year',
    ])
    def test_matches(self, text):
        assert SELF_HARM in detect_crisis(text)


class TestHopelessness:
    @pytest.mark.parametrize('text', [
        "I can't go on like this",
        'i cant go on',
        "I can't keep going",
        "I can't do this anymore",
        "I cant take it any more",
        'there is no way out',
        'nothing left to live for',
        'I want to give up on life',
        "what's the point of living",
        'whats the point of going on',
        'everyone would be better off without me',
    ])
    def test_matches(self, text):
        assert HOPELESSNESS in detect_crisis(text)


class TestOrdinaryEntriesDoNotMatch:
    @pytest.mark.parametrize('text', [
        'Work was stressful today, the deadline is looming',
        'I had a panic attack on the train but I got through it',
        'My therapist suggested I try journalling before bed',
        'I feel flat and tired and I do not know why',
        'She is killing me with kindness',
        'I am dying to see that film',
        'The diet is going badly',
        'I cut my finger chopping onions',
        'My manager harmed the project by rewriting it',
        'Slow morning. Coffee, emails, a walk.',
        '',
    ])
    def test_no_match(self, text):
        assert detect_crisis(text) == ()


class TestDeliberateFalsePositives:
    """Documented over-matching. Changing these is a product decision, not a bug fix."""

    @pytest.mark.parametrize('text', [
        'I could kill myself for forgetting my keys',
        'I want to die of embarrassment',
        'I overdosed on caffeine this morning',
    ])
    def test_still_matches(self, text):
        assert detect_crisis(text) != ()

    def test_negation_is_not_interpreted(self):
        """Negation handling would create the one error direction that can hurt."""
        assert detect_crisis("I don't want to kill myself, I just feel low") != ()


class TestNormalisation:
    def test_case_is_ignored(self):
        assert detect_crisis('I WANT TO KILL MYSELF') == (SUICIDAL_INTENT,)

    def test_curly_apostrophes_match(self):
        """Phone keyboards substitute these silently; an unmatched one is a miss."""
        assert detect_crisis('I can’t go on') == (HOPELESSNESS,)

    def test_line_breaks_inside_a_phrase_match(self):
        assert detect_crisis('I want to\nkill myself') == (SUICIDAL_INTENT,)

    def test_repeated_whitespace_matches(self):
        assert detect_crisis('I  want   to kill     myself') == (SUICIDAL_INTENT,)

    def test_punctuation_around_a_phrase_matches(self):
        assert detect_crisis('honestly? i want to die.') == (SUICIDAL_INTENT,)


class TestResultShape:
    def test_returns_every_matching_category(self):
        text = "I can't go on. I want to kill myself and I have been cutting myself."
        assert set(detect_crisis(text)) == {SUICIDAL_INTENT, SELF_HARM, HOPELESSNESS}

    def test_order_is_stable(self):
        text = 'I cut myself because I want to die'
        assert detect_crisis(text) == (SUICIDAL_INTENT, SELF_HARM)

    def test_each_category_appears_once(self):
        text = 'I want to die. I want to die. I want to die.'
        assert detect_crisis(text) == (SUICIDAL_INTENT,)

    def test_no_match_is_falsy(self):
        """Call sites branch on truthiness, so the empty result must be falsy."""
        assert not detect_crisis('an ordinary day')

    def test_is_pure(self):
        """No DB, no network, no model — it must work with nothing else running."""
        assert detect_crisis('I want to die') == (SUICIDAL_INTENT,)
