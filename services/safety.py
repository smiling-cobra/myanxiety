"""Deterministic crisis detection over entry text.

This is a safety gate, so it is a fixed keyword lexicon and nothing else. It is
pure: no network, no database, no model. `LlmService._call` swallows every
exception and returns fallback prose, so an LLM-backed classifier here would
**fail open** — an Anthropic outage would silently reclassify a crisis as "no
crisis", and the decision site would log nothing. A lexicon cannot have an
outage. An LLM signal may be added later as an additional trigger, never as the
gate that decides a match is absent.

Two deliberate design choices, both biased the same way:

* **No negation handling.** "I don't want to kill myself" matches. Teaching the
  matcher to recognise negation would buy a cleaner event stream at the cost of
  a new false-*negative* path — the only kind of error here that can hurt
  someone. Showing an extra block of hotline numbers to someone who did not
  need it is a small cost, paid in the safe direction.
* **Plain phrasing only.** No leetspeak, letter-spacing or deliberate
  obfuscation. Someone evading a keyword filter in their own private journal is
  not the user this exists to catch; chasing that would add false positives for
  everyone else and still not be exhaustive.

The lexicon is English-only, which matches the crisis resources the bot can
actually offer (`GUIDANCE_CRISIS_RESOURCES`).
"""
from __future__ import annotations

import re
import unicodedata

# Category names are a closed vocabulary: they are recorded on the
# `crisis_resources_shown` analytics event, which must never carry the user's
# own words. Renaming one breaks continuity in that event stream.
SUICIDAL_INTENT = 'suicidal_intent'
SELF_HARM = 'self_harm'
HOPELESSNESS = 'hopelessness'

# Patterns run against normalised text (see `_normalise`): lowercase, ASCII
# apostrophes, single-spaced. `my\s?self` covers "myself" and "my self";
# `'?` covers "can't" and "cant", which is how people actually type at 3am.
_LEXICON: tuple[tuple[str, tuple[str, ...]], ...] = (
    (SUICIDAL_INTENT, (
        r'\bsuicid(?:e|es|al|ality)\b',
        r'\bunalive\b',
        r'\bkms\b',
        r'\bkill(?:ing)?\s+my\s?self\b',
        r'\bhang(?:ing)?\s+my\s?self\b',
        r'\bslit\s+my\s+wrists?\b',
        r'\bend(?:ing)?\s+my\s+(?:own\s+)?life\b',
        r'\btak(?:e|ing)\s+my\s+own\s+life\b',
        r'\bend\s+it\s+all\b',
        r'\bwant\s+to\s+die\b',
        r'\bwanna\s+die\b',
        r'\bready\s+to\s+die\b',
        r'\bwish\s+i\s+(?:was|were)\s+dead\b',
        r'\bbetter\s+off\s+dead\b',
        r'\bdon\'?t\s+want\s+to\s+(?:live|be\s+here|wake\s+up)\b',
        r'\bno\s+(?:reason|point)\s+(?:to|in)\s+liv(?:e|ing)\b',
        r'\bnot\s+worth\s+living\b',
    )),
    (SELF_HARM, (
        r'\bself[\s-]?harm(?:ing|ed)?\b',
        r'\bcut(?:ting)?\s+my\s?self\b',
        r'\bhurt(?:ing)?\s+my\s?self\b',
        r'\bharm(?:ing|ed)?\s+my\s?self\b',
        r'\bburn(?:ing|ed|t)?\s+my\s?self\b',
        r'\boverdos(?:e|es|ing|ed)\b',
    )),
    (HOPELESSNESS, (
        r'\bcan\'?t\s+(?:go\s+on|keep\s+going)\b',
        r'\bcan\'?t\s+(?:do|take)\s+(?:it|this)\s+any\s?more\b',
        r'\bno\s+way\s+out\b',
        r'\bnothing\s+left\s+to\s+live\s+for\b',
        r'\bgive\s+up\s+on\s+life\b',
        r'\bwhat\'?s\s+the\s+point\s+of\s+(?:living|life|going\s+on)\b',
        r'\bbetter\s+off\s+without\s+me\b',
    )),
)

_COMPILED: tuple[tuple[str, re.Pattern], ...] = tuple(
    (category, re.compile('|'.join(patterns)))
    for category, patterns in _LEXICON
)

# Unicode apostrophes and quotes that phone keyboards substitute silently.
# Without this, "can't" from an iPhone is "can’t" and matches nothing.
_APOSTROPHES = str.maketrans({'‘': "'", '’': "'", 'ʼ': "'", '´': "'", '`': "'"})


def _normalise(text: str) -> str:
    folded = unicodedata.normalize('NFKC', text).translate(_APOSTROPHES).lower()
    return re.sub(r'\s+', ' ', folded)


def detect_crisis(text: str) -> tuple[str, ...]:
    """Categories from the lexicon present in `text`, in lexicon order.

    An empty tuple means no phrase matched — not that the writer is safe. This
    is one trigger among several; the mood-score threshold is the other, and
    neither is a clinical assessment.
    """
    if not text:
        return ()
    normalised = _normalise(text)
    return tuple(category for category, pattern in _COMPILED if pattern.search(normalised))
