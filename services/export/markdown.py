"""The export laid out as Markdown. Pure: everything it shows is in the digest."""
from __future__ import annotations

from datetime import date

from services.export.digest import DayDigest, DigestEntry, ExportDigest

_LONG_DATE_FORMAT = '%d %b %Y'
_HEADING_FORMAT = '%a %d %b %Y, %H:%M'
_DAY_HEADING_FORMAT = '%a %d %b %Y'
_CHART_FORMAT = '%a %d %b'
_TIME_FORMAT = '%H:%M'

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

    Two parts. The brief — everything above "Entries" — is meant to be read
    in about ninety seconds before a session: what the user wants to raise,
    the shape of the month, the themes and how heavy each one sat, the lowest
    points, and the mood day by day. The entries follow in full, grouped by
    day, for whatever the brief makes someone want to look up. Each section
    ends with a blank line, so sections join without spacing rules.
    """
    return '\n'.join([
        *_header(digest),
        *_flagged_section(digest.flagged),
        *_summary_section(digest),
        *_lowest_section(digest.lowest),
        *_mood_chart(digest.days),
        *_entries_section(digest.days),
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
    return ["## To raise in session", "", *(_preview_line(e) for e in flagged), ""]


def _summary_section(digest: ExportDigest) -> list[str]:
    days, entries, mood = digest.day_count, len(digest.entries), digest.mood
    lines = [
        "## At a glance",
        "",
        f"- **Wrote on:** {days} of the last {digest.window_days} days "
        f"({entries} {'entry' if entries == 1 else 'entries'})",
        f"- **Mood:** average {mood.average:.1f}/10, lowest {mood.lowest}, highest {mood.highest}",
    ]
    if digest.themes:
        lines.append("- **Most common themes:**")
        lines += [
            f"  - {t.tag} — {t.count} {'entry' if t.count == 1 else 'entries'}, "
            f"average mood {t.average_mood:.1f}"
            for t in digest.themes
        ]
    else:
        lines.append("- **Most common themes:** none recorded")
    return [*lines, ""]


def _lowest_section(lowest: tuple[DigestEntry, ...]) -> list[str]:
    if not lowest:
        return []
    return ["## Lowest points", "", *(_preview_line(e) for e in lowest), ""]


def _mood_chart(days: tuple[DayDigest, ...]) -> list[str]:
    rows = (f"{d.day.strftime(_CHART_FORMAT)}  {_bar(d.mood.average)}  {_day_score(d)}" for d in days)
    return ["## Mood by day", "", "```", *rows, "```", ""]


def _day_score(day: DayDigest) -> str:
    """One entry's score, or a day's range when it has several."""
    lowest, highest = day.mood.lowest, day.mood.highest
    score = f"{lowest}/10" if lowest == highest else f"{lowest}–{highest}/10"
    return score if len(day.entries) == 1 else f"{score} · {len(day.entries)} entries"


def _entries_section(days: tuple[DayDigest, ...]) -> list[str]:
    lines = ["## Entries", ""]
    for day in days:
        lines += [f"### {day.day.strftime(_DAY_HEADING_FORMAT)}", ""]
        for entry in day.entries:
            lines += _entry(entry)
    return lines


def _entry(entry: DigestEntry) -> list[str]:
    lines = [f"**{entry.moment.strftime(_TIME_FORMAT)} — mood {entry.mood}/10**", ""]
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


def _preview_line(entry: DigestEntry) -> str:
    return f"- {entry.moment.strftime(_HEADING_FORMAT)} — mood {entry.mood}/10: {_preview(entry.text)}"


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


def _bar(score: float) -> str:
    # Half up, not Python's round-half-to-even, so a 4.5 day does not draw as a 4.
    filled = max(0, min(_BAR_WIDTH, int(score + 0.5)))
    return '▓' * filled + '░' * (_BAR_WIDTH - filled)


def _long_date(d: date) -> str:
    return d.strftime(_LONG_DATE_FORMAT).lstrip('0')
