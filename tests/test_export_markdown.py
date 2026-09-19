"""Tests for the export's Markdown layout. Digests are built by hand, so these check
presentation only: no timezones, no tag vocabulary, no arithmetic."""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime

from services.export.digest import DayDigest, DigestEntry, ExportDigest, MoodStats, Theme
from services.export.markdown import render_markdown

MOMENT = datetime(2026, 9, 30, 9, 5)
FLAT = MoodStats(average=5.0, lowest=5, highest=5)


def _entry(text='x', mood=5, moment=MOMENT, tags=(), flagged=False) -> DigestEntry:
    return DigestEntry(moment=moment, mood=mood, text=text, tags=tuple(tags), flagged=flagged)


def _day(*entries: DigestEntry, mood: MoodStats = FLAT) -> DayDigest:
    return DayDigest(day=entries[0].moment.date(), entries=entries, mood=mood)


def _render(*entries: DigestEntry, **overrides) -> str:
    """A digest whose entries all fall on one day unless `days` is overridden.
    The stats are fixed values rather than computed: layout is under test here."""
    entries = entries or (_entry(),)
    digest = ExportDigest(
        name='Sam',
        today=date(2026, 9, 30),
        window_days=30,
        first_day=entries[0].moment.date(),
        last_day=entries[-1].moment.date(),
        entries=entries,
        days=(_day(*entries),),
        flagged=tuple(e for e in entries if e.flagged),
        lowest=(),
        mood=FLAT,
        themes=(),
    )
    return render_markdown(replace(digest, **overrides))


def _section(text: str, heading: str) -> str:
    return text.split(f'## {heading}\n')[1].split('\n## ')[0]


class TestHeader:
    def test_title_carries_the_name(self):
        assert _render().startswith('# Journal — Sam\n')

    def test_title_without_a_name(self):
        assert _render(name=None).startswith('# Journal\n')

    def test_span_and_export_date_without_leading_zeros(self):
        text = _render(first_day=date(2026, 9, 1), last_day=date(2026, 9, 30), today=date(2026, 10, 2))
        assert '1 Sep 2026 to 30 Sep 2026 · exported 2 Oct 2026' in text


class TestSectionOrder:
    def test_flagged_summary_chart_entries_footer(self):
        text = _render(_entry(flagged=True))
        markers = ['## To raise in session', '## At a glance', '## Mood by entry', '## Entries', '---']
        positions = [text.index(m) for m in markers]
        assert positions == sorted(positions)

    def test_no_flags_no_section(self):
        assert 'To raise in session' not in _render(_entry(), _entry())

    def test_sections_are_separated_by_one_blank_line(self):
        assert '\n\n\n' not in _render(_entry('a', flagged=True, tags=['work']))
        assert _render().endswith('._\n')


class TestFlaggedSection:
    def test_lists_only_the_flagged_entries(self):
        text = _render(_entry('an ordinary day'), _entry('the thing I want to talk about', mood=3, flagged=True))
        section = _section(text, 'To raise in session')
        assert '- Wed 30 Sep 2026, 09:05 — mood 3/10: the thing I want to talk about' in section
        assert 'an ordinary day' not in section

    def test_long_entries_are_previewed_on_one_line(self):
        section = _section(_render(_entry('word ' * 60 + '\nsecond line', flagged=True)), 'To raise in session')
        preview = [line for line in section.splitlines() if line.startswith('- ')]
        assert len(preview) == 1
        assert preview[0].endswith('…')

    def test_short_entries_are_not_truncated(self):
        section = _section(_render(_entry('line one\nline two', flagged=True)), 'To raise in session')
        assert section.splitlines()[1].endswith(': line one line two')


class TestSummarySection:
    def test_counts_and_mood(self):
        first, second = _entry(), _entry(moment=datetime(2026, 9, 29, 9, 5))
        mood = MoodStats(average=17 / 3, lowest=2, highest=9)
        text = _render(first, second, days=(_day(second), _day(first)), mood=mood)
        assert '- **Entries:** 2 on 2 different days' in text
        assert '- **Mood:** average 5.7/10, lowest 2, highest 9' in text

    def test_one_day_is_singular(self):
        assert '1 on 1 different day\n' in _render()

    def test_themes_with_counts(self):
        themes = (Theme('work', 2, 4.0), Theme('sleep', 1, 6.0))
        assert '- **Most common themes:** work (2), sleep (1)' in _render(themes=themes)

    def test_no_themes(self):
        assert '- **Most common themes:** none recorded' in _render(themes=())


class TestMoodChart:
    def test_one_fenced_row_per_entry(self):
        text = _render(_entry(mood=3), _entry(mood=10, moment=datetime(2026, 9, 30, 21, 40)))
        assert '```\nWed 30 Sep 09:05  ▓▓▓░░░░░░░  3/10\nWed 30 Sep 21:40  ▓▓▓▓▓▓▓▓▓▓  10/10\n```' in text

    def test_bar_is_clamped_to_its_width(self):
        rows = _section(_render(_entry(mood=-1), _entry(mood=11)), 'Mood by entry').splitlines()
        assert 'Wed 30 Sep 09:05  ░░░░░░░░░░  -1/10' in rows
        assert 'Wed 30 Sep 09:05  ▓▓▓▓▓▓▓▓▓▓  11/10' in rows


class TestEntriesSection:
    def test_entries_keep_the_digest_order(self):
        text = _render(_entry('first'), _entry('second'))
        assert text.index('> first') < text.index('> second')

    def test_heading_shows_time_and_mood(self):
        assert '### Wed 30 Sep 2026, 09:05 — mood 5/10' in _render()

    def test_flagged_entries_are_marked(self):
        entries = _section(_render(_entry('flag me', flagged=True)), 'Entries')
        assert '🚩 **Flagged to raise in session**' in entries

    def test_themes_line_only_when_tagged(self):
        assert 'Themes: work, sleep' in _render(_entry(tags=['work', 'sleep']))
        assert 'Themes:' not in _render(_entry())

    def test_multi_line_entries_stay_quoted(self):
        assert '> line one\n>\n> line two' in _render(_entry('line one\n\nline two'))

    def test_an_empty_entry_is_an_empty_quote(self):
        assert '### Wed 30 Sep 2026, 09:05 — mood 5/10\n\n>\n' in _render(_entry(''))

    def test_user_text_cannot_become_markdown_structure(self):
        text = _render(_entry('# not a heading\n- not a list\n  > not nested'))
        assert '> \\# not a heading' in text
        assert '> \\- not a list' in text
        assert '>   \\> not nested' in text


class TestFooter:
    def test_says_what_it_is_not(self):
        assert 'not a clinical record' in _render()
