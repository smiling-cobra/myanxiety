"""The export laid out as Markdown. Pure: everything it shows is in the digest."""
from __future__ import annotations

from datetime import date

from services.export.digest import DigestEntry, ExportDigest

_BAR_WIDTH = 10
_BLOCK_MARKERS = frozenset('#>-*+=`|')
_PREVIEW_CHARS = 80


def render_markdown(digest: ExportDigest) -> str:
    """The export as Markdown.

    The file reads top to bottom as a summary a therapist can take in at a
    glance, then the entries themselves in the order they were lived.
    """
    lines = [f"# Journal — {digest.name}" if digest.name else "# Journal", ""]
    lines.append(
        f"{_long_date(digest.first_day)} to {_long_date(digest.last_day)} · exported {_long_date(digest.today)}"
    )
    if digest.flagged:
        # First, because it is the point of the file: what the user decided, at
        # the time, that they wanted to talk about.
        lines += ["", "## To raise in session", ""]
        lines += [f"- {_heading(entry)}: {_preview(entry.text)}" for entry in digest.flagged]
    lines += ["", "## At a glance", ""]
    lines += _summary(digest)
    lines += ["", "## Mood by entry", "", "```"]
    lines += [
        f"{entry.moment.strftime('%a %d %b %H:%M')}  {_bar(entry.mood)}  {entry.mood}/10"
        for entry in digest.entries
    ]
    lines += ["```", "", "## Entries", ""]
    for entry in digest.entries:
        lines += _entry(entry)
    lines += [
        "---",
        "",
        "_Written by the journal's owner in a private journalling bot. Mood is self-rated from "
        "1 (worst) to 10 (best) at the time of writing. Themes are tagged automatically and may be "
        "imperfect. This is not a clinical record._",
        "",
    ]
    return '\n'.join(lines)


def _summary(digest: ExportDigest) -> list:
    days, mood, themes = digest.day_count, digest.mood, digest.themes
    return [
        f"- **Entries:** {len(digest.entries)} on {days} different {'day' if days == 1 else 'days'}",
        f"- **Mood:** average {mood.average:.1f}/10, lowest {mood.lowest}, highest {mood.highest}",
        "- **Most common themes:** "
        + (', '.join(f"{tag} ({count})" for tag, count in themes) if themes else "none recorded"),
    ]


def _entry(entry: DigestEntry) -> list:
    lines = [f"### {_heading(entry)}", ""]
    if entry.flagged:
        lines += ["🚩 **Flagged to raise in session**", ""]
    if entry.tags:
        lines += [f"Themes: {', '.join(entry.tags)}", ""]
    # A blockquote keeps the user's words visibly theirs.
    lines += [f"> {_literal(line)}" if line.strip() else ">" for line in entry.text.splitlines() or ['']]
    lines.append("")
    return lines


def _heading(entry: DigestEntry) -> str:
    return f"{entry.moment.strftime('%a %d %b %Y, %H:%M')} — mood {entry.mood}/10"


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
