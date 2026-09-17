"""The export laid out as Markdown. Pure: everything it shows is passed in."""
from __future__ import annotations

from datetime import date, datetime, tzinfo

from services import time_utils
from services.tags import normalise_tags, tag_counts

_TOP_THEMES = 5
_BAR_WIDTH = 10
_BLOCK_MARKERS = frozenset('#>-*+=`|')
_PREVIEW_CHARS = 80


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
