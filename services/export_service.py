"""The therapist-shareable export, v0.

The product bet this exists to test is narrow: will someone actually take their
journal into a therapy session? So this is deliberately rough — plain Markdown,
one file, the last few weeks — and it ships before it is designed, because a
polished artifact that nobody brings to a session answers nothing. Phase 6
reworks the format once there is evidence it is used.

Two properties are deliberate rather than rough:

* **No model call.** The file is built from what is stored, deterministically.
  It costs nothing against the LLM budget, it cannot fail because Anthropic is
  down, and nothing in it was written by anyone but the user — which matters
  for a document handed to a clinician.
* **It is the user's own words in full.** The file goes to them, in their own
  chat, and where it goes next is their choice. Nothing is summarised away and
  nothing the user did not write is added beyond counts and dates.

Tags are read through `services.tags`, so the themes line reflects the current
vocabulary however old the entries are.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, tzinfo

from repositories.user_repo import UserRepository
from services import time_utils
from services.journal_service import JournalService
from services.tags import normalise_tags, tag_counts

# Roughly a month: long enough to cover the gap between fortnightly sessions
# with room to spare, short enough to read in the waiting room.
EXPORT_DAYS = 30

_TOP_THEMES = 5
_BAR_WIDTH = 10
_BLOCK_MARKERS = frozenset('#>-*+=`|')
_PREVIEW_CHARS = 80


@dataclass(frozen=True)
class Export:
    filename: str
    content: bytes
    entry_count: int
    flagged_count: int


class ExportService:
    def __init__(self):
        self._journal = JournalService()
        self._users = UserRepository()

    def build(self, telegram_id: int) -> Export | None:
        """The export for the last `EXPORT_DAYS` local days, or None if there is nothing in it."""
        user = self._users.find(telegram_id) or {}
        timezone_name = user.get('timezone')
        entries = self._journal.get_entries_for_days(telegram_id, EXPORT_DAYS, timezone_name)
        if not entries:
            return None

        tz = time_utils.resolve_timezone(timezone_name, telegram_id)
        today = time_utils.now().astimezone(tz).date()
        markdown = render_export(user.get('name'), entries, tz, today)
        return Export(
            filename=f'journal-{today.isoformat()}.md',
            content=markdown.encode('utf-8'),
            entry_count=len(entries),
            flagged_count=sum(1 for e in entries if e.get('flagged_for_session')),
        )


def render_export(name: str | None, entries: list, tz: tzinfo, today: date) -> str:
    """The export as Markdown. Pure: everything it shows is passed in.

    `entries` are expected oldest first, as `JournalService` returns them. The
    file reads top to bottom as a summary a therapist can take in at a glance,
    then the entries themselves in the order they were lived.
    """
    local = [(time_utils.to_local(e['created_at'], tz), e) for e in entries]
    first_day, last_day = local[0][0].date(), local[-1][0].date()

    lines = [f"# Journal — {name}" if name else "# Journal", ""]
    lines.append(f"{_long_date(first_day)} to {_long_date(last_day)} · exported {_long_date(today)}")
    flagged = [(moment, e) for moment, e in local if e.get('flagged_for_session')]
    if flagged:
        # First, because it is the point of the file: what the user decided, at
        # the time, that they wanted to talk about.
        lines += ["", "## To raise in session", ""]
        lines += [f"- {_heading(moment, e)}: {_preview(e['text'])}" for moment, e in flagged]
    lines += ["", "## At a glance", ""]
    lines += _summary(local)
    lines += ["", "## Mood by entry", "", "```"]
    lines += [
        f"{moment.strftime('%a %d %b %H:%M')}  {_bar(e['mood_score'])}  {e['mood_score']}/10"
        for moment, e in local
    ]
    lines += ["```", "", "## Entries", ""]
    for moment, entry in local:
        lines += _entry(moment, entry)
    lines += [
        "---",
        "",
        "_Written by the journal's owner in a private journalling bot. Mood is self-rated from "
        "1 (worst) to 10 (best) at the time of writing. Themes are tagged automatically and may be "
        "imperfect. This is not a clinical record._",
        "",
    ]
    return '\n'.join(lines)


def _summary(local: list) -> list:
    scores = [e['mood_score'] for _, e in local]
    days = len({moment.date() for moment, _ in local})
    themes = tag_counts((e for _, e in local), _TOP_THEMES)
    return [
        f"- **Entries:** {len(local)} on {days} different {'day' if days == 1 else 'days'}",
        f"- **Mood:** average {sum(scores) / len(scores):.1f}/10, lowest {min(scores)}, highest {max(scores)}",
        "- **Most common themes:** "
        + (', '.join(f"{tag} ({count})" for tag, count in themes) if themes else "none recorded"),
    ]


def _entry(moment: datetime, entry: dict) -> list:
    lines = [f"### {_heading(moment, entry)}", ""]
    if entry.get('flagged_for_session'):
        lines += ["🚩 **Flagged to raise in session**", ""]
    tags = normalise_tags(entry.get('tags') or [])
    if tags:
        lines += [f"Themes: {', '.join(tags)}", ""]
    # A blockquote keeps the user's words visibly theirs.
    lines += [f"> {_literal(line)}" if line.strip() else ">" for line in entry['text'].splitlines() or ['']]
    lines.append("")
    return lines


def _heading(moment: datetime, entry: dict) -> str:
    return f"{moment.strftime('%a %d %b %Y, %H:%M')} — mood {entry['mood_score']}/10"


def _preview(text: str) -> str:
    """The start of an entry, on one line. The full text is further down the file."""
    flat = ' '.join(text.split())
    return flat if len(flat) <= _PREVIEW_CHARS else flat[:_PREVIEW_CHARS].rstrip() + '…'


def _literal(line: str) -> str:
    """Escape a leading block marker, so a line of the user's that starts with "#"
    or "-" reads as they typed it rather than as a heading or a list inside the quote."""
    stripped = line.lstrip()
    if stripped[:1] in _BLOCK_MARKERS:
        indent = line[:len(line) - len(stripped)]
        return f"{indent}\\{stripped}"
    return line


def _bar(score: int) -> str:
    filled = max(0, min(_BAR_WIDTH, score))
    return '▓' * filled + '░' * (_BAR_WIDTH - filled)


def _long_date(d: date) -> str:
    return d.strftime('%d %b %Y').lstrip('0')
