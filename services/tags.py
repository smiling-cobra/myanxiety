"""Tag normalisation.

Tags are what turn a pile of entries into something a person — or their
therapist — can read at a glance: "work came up in nine of twelve entries" is
only true if "work", "Work", "#work", "job", "work stress" and "deadlines" are
counted as one thing. Left raw, the model's free-text tags fragment every count
built on them, and the long tail of one-off variants is exactly the noise that
makes a summary illegible.

Everything here is pure and deterministic — no model, no database — and it is
**idempotent**: normalising an already-normalised tag returns it unchanged. That
property is what lets it run in two places without disagreement:

* at extraction (`LlmService.extract_tags`), so what is stored is clean; and
* wherever tags are counted (`top_tags`), so entries stored before this existed,
  or before the vocabulary below last changed, are read through the current
  rules. No backfill is needed, and none ever will be when the vocabulary grows.

The vocabulary is a first cut, not a taxonomy. It is not clinical and not
exhaustive: a tag outside it is kept, cleaned, rather than discarded, because a
theme nobody anticipated is still a theme. Expect to revise it once there is
real tag data to look at; `top_tags` means a revision applies retroactively.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable

MAX_TAGS = 5

# The extraction prompt asks for one or two words. Anything longer is the model
# explaining itself ("the user seems stressed about work"), not a tag.
_MAX_WORDS = 2
_MAX_CHARS = 24

# Canonical tag -> the variants that mean the same thing. Keys are what gets
# stored and shown. Variants are matched after cleaning (lowercase, hyphens and
# underscores read as spaces), and a regular plural of any entry matches too,
# so "deadlines" and "friends" need no row of their own.
CANONICAL_TAGS: dict[str, tuple[str, ...]] = {
    # Feelings
    'anxiety': ('anxious', 'worry', 'worrying', 'nervous', 'nerves', 'nervousness'),
    'stress': ('stressed', 'stressful', 'pressure'),
    'panic': ('panic attack', 'panicking'),
    'overwhelm': ('overwhelmed', 'overwhelming'),
    'sadness': ('sad', 'unhappy', 'low mood', 'feeling down'),
    'anger': ('angry', 'rage'),
    'frustration': ('frustrated', 'irritation', 'irritated', 'annoyance', 'annoyed'),
    'guilt': ('guilty',),
    'loneliness': ('lonely', 'isolation', 'isolated', 'alone'),
    'uncertainty': ('future', 'the future', 'unknown'),
    'rumination': ('overthinking', 'racing thoughts'),
    'self-esteem': ('self worth', 'confidence', 'insecurity', 'self doubt', 'self criticism'),
    'hope': ('hopeful', 'optimism', 'optimistic'),
    'calm': ('calmness', 'peace', 'peaceful', 'relaxed'),
    'gratitude': ('grateful', 'thankful', 'appreciation'),
    'achievement': ('accomplishment', 'progress', 'success', 'pride'),
    # Body
    'sleep': ('insomnia', 'poor sleep', 'bad sleep', 'sleep issue', 'sleep problem', 'sleeplessness'),
    'fatigue': ('tired', 'tiredness', 'exhaustion', 'exhausted', 'low energy'),
    'burnout': ('burned out', 'burnt out'),
    'health': ('illness', 'sick', 'sickness', 'physical health', 'medical', 'pain', 'doctor'),
    'medication': ('meds', 'medicine'),
    'exercise': ('workout', 'gym', 'running', 'fitness'),
    'body image': ('appearance', 'weight'),
    'rest': ('relaxation', 'relaxing', 'downtime', 'self care'),
    # Life
    'work': ('job', 'career', 'boss', 'workplace', 'office', 'coworker', 'colleague', 'deadline',
             'meeting', 'work stress'),
    'school': ('study', 'studying', 'exam', 'university', 'college', 'homework', 'grade', 'coursework'),
    'money': ('finance', 'finances', 'financial stress', 'bill', 'debt', 'rent', 'budget'),
    'family': ('parent', 'mum', 'mom', 'mother', 'dad', 'father', 'sibling', 'family issue', 'family stress'),
    'relationship': ('partner', 'romance', 'dating', 'boyfriend', 'girlfriend', 'husband', 'wife',
                     'breakup', 'relationship issue'),
    'friendship': ('friend',),
    'parenting': ('kid', 'child', 'children', 'baby'),
    'socialising': ('socializing', 'social situation', 'social event', 'social life', 'party'),
    'conflict': ('argument', 'arguing', 'fight', 'fighting', 'disagreement', 'tension'),
    'grief': ('loss', 'bereavement', 'grieving'),
    'therapy': ('therapist', 'counselling', 'counseling', 'session'),
}

# Words a model produces when it has nothing to say, or labels its own output
# with. None of them is a theme.
_NOISE = frozenset({'none', 'na', 'nothing', 'tag', 'tags', 'other', 'misc', 'general', 'entry', 'journal'})

# Characters that decorate a tag without being part of it: hashtags, bullets,
# quotes, trailing full stops.
_EDGE_CHARS = '#*•-–—"\'“”‘’`.,;:!?()[] \t'

# Letters (any script), joined by single spaces or apostrophes. No digits and no
# punctuation beyond that — "work/school" or "9-5" is not a tag this layer can
# safely guess the meaning of.
_TAG_SHAPE = re.compile(r"^[^\W\d_]+(?:['\s][^\W\d_]+)*$")


def _key(text: str) -> str:
    """The comparison form: lowercase, NFKC, separators as single spaces."""
    folded = unicodedata.normalize('NFKC', text).lower().replace('’', "'")
    return ' '.join(re.sub(r'[-_]+', ' ', folded).split())


def _build_lookup() -> dict[str, str]:
    lookup = {}
    for canonical, variants in CANONICAL_TAGS.items():
        for form in (canonical, *variants):
            lookup[_key(form)] = canonical
    return lookup


_LOOKUP = _build_lookup()


def _canonical(key: str) -> str | None:
    """The canonical tag for `key`, allowing a regular plural of any known form."""
    if key in _LOOKUP:
        return _LOOKUP[key]
    # Plural folding is only ever *into* the vocabulary, never applied to an
    # unknown word — "news", "stress" and "diabetes" are not plurals, and a
    # general stemmer would mangle them.
    if key.endswith('ies') and key[:-3] + 'y' in _LOOKUP:
        return _LOOKUP[key[:-3] + 'y']
    if key.endswith('s') and not key.endswith('ss') and key[:-1] in _LOOKUP:
        return _LOOKUP[key[:-1]]
    return None


def normalise_tag(raw: object) -> str | None:
    """One tag in its stored form, or None if it is not a usable tag."""
    if not isinstance(raw, str):
        return None

    text = raw
    if ':' in text:  # "Tags: work" — keep what follows the model's label
        text = text.rsplit(':', 1)[1]
    key = _key(text.strip(_EDGE_CHARS))
    if not key or key in _NOISE:
        return None

    canonical = _canonical(key)
    if canonical is not None:
        return canonical

    if len(key) > _MAX_CHARS or len(key.split()) > _MAX_WORDS or not _TAG_SHAPE.match(key):
        return None
    return key


def normalise_tags(raw_tags: Iterable[object]) -> list[str]:
    """Clean, canonicalise and de-duplicate tags, keeping first-seen order."""
    seen: list[str] = []
    for raw in raw_tags or ():
        tag = normalise_tag(raw)
        if tag is not None and tag not in seen:
            seen.append(tag)
    return seen[:MAX_TAGS]


def parse_tag_list(raw: str) -> list[str]:
    """Tags from a model reply. Asked for a comma-separated list, models also
    answer with one tag per line or a bulleted list, so all three are read."""
    return normalise_tags(re.split(r'[,;\n]', raw or ''))


def top_tags(entries: Iterable[dict], limit: int) -> list[str]:
    """The most common tags across `entries`, most frequent first."""
    return [tag for tag, _ in tag_counts(entries, limit)]


def tag_counts(entries: Iterable[dict], limit: int) -> list[tuple[str, int]]:
    """The most common tags across `entries` with the number of entries each came up in.

    Stored tags are re-normalised on the way in, so the count reflects the
    current vocabulary however old the entries are. Each tag counts once per
    entry: the question is how many entries a theme came up in.
    """
    counts = Counter(tag for entry in entries for tag in normalise_tags(entry.get('tags') or []))
    return counts.most_common(limit)
