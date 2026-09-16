"""Tests for tag normalisation — pure, no database, no model."""
from __future__ import annotations

import pytest

from services.llm_service import FALLBACK_REPLY
from services.tags import CANONICAL_TAGS, MAX_TAGS, normalise_tag, normalise_tags, parse_tag_list, top_tags


class TestVariantsCollapse:
    @pytest.mark.parametrize('raw, expected', [
        ('work', 'work'),
        ('Work', 'work'),
        ('#work', 'work'),
        ('  WORK. ', 'work'),
        ('"work"', 'work'),
        ('- work', 'work'),
        ('job', 'work'),
        ('work stress', 'work'),
        ('Work-Stress', 'work'),
        ('work_stress', 'work'),
        ('anxious', 'anxiety'),
        ('insomnia', 'sleep'),
        ('self esteem', 'self-esteem'),
        ('self_esteem', 'self-esteem'),
        ('Self-Worth', 'self-esteem'),
    ])
    def test_variant_becomes_canonical(self, raw, expected):
        assert normalise_tag(raw) == expected

    @pytest.mark.parametrize('raw, expected', [
        ('deadlines', 'work'),
        ('friends', 'friendship'),
        ('panic attacks', 'panic'),
        ('sleep issues', 'sleep'),
        ('anxieties', 'anxiety'),
    ])
    def test_regular_plural_of_a_known_form_folds(self, raw, expected):
        assert normalise_tag(raw) == expected

    @pytest.mark.parametrize('word', ['news', 'diabetes', 'stress', 'christmas', 'loneliness'])
    def test_words_ending_in_s_are_not_stemmed_blindly(self, word):
        """Folding is only ever into the vocabulary. A general stemmer would turn
        "news" into "new" and "christmas" into "christma"."""
        assert normalise_tag(word) == word


class TestUnknownTagsAreKeptClean:
    def test_a_theme_outside_the_vocabulary_survives(self):
        assert normalise_tag('Moving House') == 'moving house'

    def test_hyphens_read_as_spaces(self):
        assert normalise_tag('well-being') == 'well being'

    def test_non_latin_letters_are_letters(self):
        assert normalise_tag('ansiedad') == 'ansiedad'
        assert normalise_tag('тревога') == 'тревога'


class TestNonTagsAreDropped:
    @pytest.mark.parametrize('raw', [
        '',
        '   ',
        '#',
        'none',
        'N/A',
        'tags',
        'the user seems stressed about work',
        'a really quite remarkably long label',
        '9-5',
        'work/school',
        None,
        42,
        ['work'],
    ])
    def test_rejected(self, raw):
        assert normalise_tag(raw) is None

    def test_the_llm_fallback_apology_cannot_become_a_tag(self):
        """What every Anthropic outage used to write into the tag list."""
        assert normalise_tags(FALLBACK_REPLY.split(',')) == []

    def test_a_label_prefix_is_ignored(self):
        assert normalise_tag('Tags: work') == 'work'


class TestNormaliseTags:
    def test_duplicates_are_removed_after_canonicalising(self):
        assert normalise_tags(['job', 'Work', '#work', 'sleep']) == ['work', 'sleep']

    def test_first_seen_order_is_kept(self):
        assert normalise_tags(['sleep', 'work', 'family']) == ['sleep', 'work', 'family']

    def test_capped(self):
        raw = ['work', 'sleep', 'family', 'money', 'health', 'exercise', 'grief']
        assert len(normalise_tags(raw)) == MAX_TAGS

    def test_cap_applies_after_junk_is_removed(self):
        raw = ['none', 'none', 'work', '??', 'sleep', 'family', 'money', 'health']
        assert normalise_tags(raw) == ['work', 'sleep', 'family', 'money', 'health']

    def test_none_and_empty(self):
        assert normalise_tags(None) == []
        assert normalise_tags([]) == []


class TestIdempotence:
    """Normalisation runs at extraction *and* when counting. Two passes that
    disagreed would split a stored tag from its own re-read."""

    SAMPLES = [
        'Work', 'job', 'self_esteem', 'deadlines', 'Moving House', 'well-being', 'insomnia',
        'news', "can't sleep", 'тревога',
    ]

    @pytest.mark.parametrize('raw', SAMPLES + list(CANONICAL_TAGS))
    def test_second_pass_is_a_no_op(self, raw):
        once = normalise_tag(raw)
        assert normalise_tag(once) == once


class TestVocabularyIntegrity:
    def test_every_canonical_tag_is_its_own_normal_form(self):
        assert [t for t in CANONICAL_TAGS if normalise_tag(t) != t] == []

    def test_no_variant_is_claimed_by_two_canonical_tags(self):
        owners: dict[str, str] = {}
        clashes = []
        for canonical, variants in CANONICAL_TAGS.items():
            for form in (canonical, *variants):
                key = form.replace('-', ' ')
                if key in owners and owners[key] != canonical:
                    clashes.append((form, owners[key], canonical))
                owners[key] = canonical
        assert clashes == []

    def test_every_variant_resolves_to_its_own_canonical_tag(self):
        wrong = [
            (variant, canonical)
            for canonical, variants in CANONICAL_TAGS.items()
            for variant in variants
            if normalise_tag(variant) != canonical
        ]
        assert wrong == []


class TestParseTagList:
    def test_comma_separated(self):
        assert parse_tag_list('Work, sleep, Family') == ['work', 'sleep', 'family']

    def test_one_per_line_with_bullets(self):
        assert parse_tag_list('- work\n- sleep\n• family') == ['work', 'sleep', 'family']

    def test_labelled_reply(self):
        assert parse_tag_list('Tags: work, sleep') == ['work', 'sleep']

    def test_empty_reply(self):
        assert parse_tag_list('') == []


class TestTopTags:
    def test_legacy_variants_are_counted_together(self):
        entries = [
            {'tags': ['work']},
            {'tags': ['job']},
            {'tags': ['Work Stress', 'sleep']},
        ]
        assert top_tags(entries, 2) == ['work', 'sleep']

    def test_a_tag_counts_once_per_entry(self):
        entries = [
            {'tags': ['job', 'work', 'deadlines']},
            {'tags': ['sleep']},
            {'tags': ['sleep']},
        ]
        assert top_tags(entries, 1) == ['sleep']

    def test_stored_fallback_prose_is_not_counted(self):
        entries = [{'tags': [FALLBACK_REPLY]}, {'tags': [FALLBACK_REPLY.lower()]}]
        assert top_tags(entries, 5) == []

    def test_entries_without_tags(self):
        assert top_tags([{}, {'tags': None}, {'tags': []}], 3) == []
