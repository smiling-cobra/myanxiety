"""The export laid out as Markdown. Pure: everything it shows is in the digest."""
from __future__ import annotations

from datetime import date

from services.export.digest import DigestEntry, ExportDigest

_LONG_DATE_FORMAT = '%d %b %Y'
_HEADING_FORMAT = '%a %d %b %Y, %H:%M'
_CHART_FORMAT = '%a %d %b %H:%M'

_BAR_WIDTH = 10
_BLOCK_MARKERS = frozenset('#>-*+=`|')
_PREVIEW_CHARS = 80

_FOOTER = (
    "_Written by the journal's owner in a private journalling bot. Mood is self-rated from "
    "1 (worst) to 10 (best) at the time of writing. Themes are tagged automatically and may be "
    "imperfect. This is not a clinical record._"
)


def render_markdown(digest: ExportDigest) -> str:
    """The export as Markdown.

    The file reads top to bottom as a summary a therapist can take in at a
    glance, then the entries themselves in the order they were lived. Each
    section ends with a blank line, so sections join without spacing rules.
    """
    return '\n'.join([
        *_header(digest),
        *_flagged_section(digest.flagged),
        *_summary_section(digest),
        *_mood_chart(digest.entries),
        *_entries_section(digest.entries),
        *_footer(),
    ])


def _header(digest: ExportDigest) -> list[str]:
    title = f"# Journal — {digest.name}" if digest.name else "# Journal"
    span = f"{_long_date(digest.first_day)} to {_long_date(digest.last_day)}"
    return [title, "", f"{span} · exported {_long_date(digest.today)}", ""]


def _flagged_section(flagged: tuple[DigestEntry, ...]) -> list[str]:
    # First after the header, because it is the point of the file: what the
    # user decided, at the time, that they wanted to talk about.
    if not flagged:
        return []
    return ["## To raise in session", "", *(f"- {_heading(e)}: {_preview(e.text)}" for e in flagged), ""]


def _summary_section(digest: ExportDigest) -> list[str]:
    days, mood, themes = digest.day_count, digest.mood, digest.themes
    theme_list = ', '.join(f"{tag} ({count})" for tag, count in themes) if themes else "none recorded"
    return [
        "## At a glance",
        "",
        f"- **Entries:** {len(digest.entries)} on {days} different {'day' if days == 1 else 'days'}",
        f"- **Mood:** average {mood.average:.1f}/10, lowest {mood.lowest}, highest {mood.highest}",
        f"- **Most common themes:** {theme_list}",
        "",
    ]


def _mood_chart(entries: tuple[DigestEntry, ...]) -> list[str]:
    rows = (f"{e.moment.strftime(_CHART_FORMAT)}  {_bar(e.mood)}  {e.mood}/10" for e in entries)
    return ["## Mood by entry", "", "```", *rows, "```", ""]


def _entries_section(entries: tuple[DigestEntry, ...]) -> list[str]:
    lines = ["## Entries", ""]
    for entry in entries:
        lines += _entry(entry)
    return lines


def _entry(entry: DigestEntry) -> list[str]:
    lines = [f"### {_heading(entry)}", ""]
    if entry.flagged:
        lines += ["🚩 **Flagged to raise in session**", ""]
    if entry.tags:
        lines += [f"Themes: {', '.join(entry.tags)}", ""]
    lines += _quote(entry.text)
    lines.append("")
    return lines


def _footer() -> list[str]:
    return ["---", "", _FOOTER, ""]


def _quote(text: str) -> list[str]:
    """The user's text as a blockquote, which keeps their words visibly theirs."""
    return [f"> {_literal(line)}" if line.strip() else ">" for line in text.splitlines() or ['']]


def _heading(entry: DigestEntry) -> str:
    return f"{entry.moment.strftime(_HEADING_FORMAT)} — mood {entry.mood}/10"


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
    return d.strftime(_LONG_DATE_FORMAT).lstrip('0')
