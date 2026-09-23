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
    def test_brief_then_entries_then_footer(self):
        entry = _entry(flagged=True)
        text = _render(entry, lowest=(entry,))
        markers = [
            '## To raise in session', '## At a glance', '## Lowest points', '## Mood by day', '## Entries', '---',
        ]
        positions = [text.index(m) for m in markers]
        assert positions == sorted(positions)

    def test_no_flags_no_section(self):
        assert 'To raise in session' not in _render(_entry(), _entry())

    def test_sections_are_separated_by_one_blank_line(self):
        entry = _entry('a', flagged=True, tags=['work'])
        assert '\n\n\n' not in _render(entry, lowest=(entry,), themes=(Theme('work', 1, 5.0),))
        assert '\n\n\n' not in _render()
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
    def test_days_written_out_of_the_window_and_mood(self):
        first, second = _entry(), _entry(moment=datetime(2026, 9, 29, 9, 5))
        mood = MoodStats(average=17 / 3, lowest=2, highest=9)
        text = _render(first, second, days=(_day(second), _day(first)), mood=mood)
        assert '- **Wrote on:** 2 of the last 30 days (2 entries)' in text
        assert '- **Mood:** average 5.7/10, lowest 2, highest 9' in text

    def test_one_entry_is_singular(self):
        assert '(1 entry)' in _render()

    def test_each_theme_with_its_count_and_average_mood(self):
        themes = (Theme('work', 8, 4.125), Theme('sleep', 1, 6.0))
        section = _section(_render(themes=themes), 'At a glance')
        assert '- **Most common themes:**\n  - work — 8 entries, average mood 4.1\n' in section
        assert '  - sleep — 1 entry, average mood 6.0' in section

    def test_no_themes(self):
        assert '- **Most common themes:** none recorded' in _render(themes=())


class TestLowestSection:
    def test_lists_the_entries_it_is_given(self):
        low = _entry('a very hard evening', mood=2, moment=datetime(2026, 9, 30, 22, 15))
        section = _section(_render(_entry(), low, lowest=(low,)), 'Lowest points')
        assert '- Wed 30 Sep 2026, 22:15 — mood 2/10: a very hard evening' in section

    def test_absent_when_empty(self):
        assert 'Lowest points' not in _render(lowest=())


class TestMoodChart:
    def test_one_row_per_day(self):
        monday = _entry(mood=3, moment=datetime(2026, 9, 28, 9, 0))
        wednesday = _entry(mood=10, moment=datetime(2026, 9, 30, 21, 40))
        days = (_day(monday, mood=MoodStats(3, 3, 3)), _day(wednesday, mood=MoodStats(10, 10, 10)))
        text = _render(monday, wednesday, days=days)
        assert '```\nMon 28 Sep  ▓▓▓░░░░░░░  3/10\nWed 30 Sep  ▓▓▓▓▓▓▓▓▓▓  10/10\n```' in text

    def test_a_day_with_several_entries_shows_its_range_and_count(self):
        entries = (_entry(mood=3), _entry(mood=8), _entry(mood=7))
        text = _render(*entries, days=(_day(*entries, mood=MoodStats(average=6.0, lowest=3, highest=8)),))
        assert 'Wed 30 Sep  ▓▓▓▓▓▓░░░░  3–8/10 · 3 entries' in text

    def test_a_day_with_one_score_shows_no_range(self):
        entries = (_entry(mood=6), _entry(mood=6))
        text = _render(*entries, days=(_day(*entries, mood=MoodStats(average=6.0, lowest=6, highest=6)),))
        assert 'Wed 30 Sep  ▓▓▓▓▓▓░░░░  6/10 · 2 entries' in text

    def test_the_bar_rounds_half_up(self):
        entries = (_entry(mood=4), _entry(mood=5))
        text = _render(*entries, days=(_day(*entries, mood=MoodStats(average=4.5, lowest=4, highest=5)),))
        assert '▓▓▓▓▓░░░░░' in _section(text, 'Mood by day')

    def test_bar_is_clamped_to_its_width(self):
        low, high = _entry(mood=-1), _entry(mood=11, moment=datetime(2026, 10, 1, 9, 5))
        days = (_day(low, mood=MoodStats(-1, -1, -1)), _day(high, mood=MoodStats(11, 11, 11)))
        rows = _section(_render(low, high, days=days), 'Mood by day').splitlines()
        assert 'Wed 30 Sep  ░░░░░░░░░░  -1/10' in rows
        assert 'Thu 01 Oct  ▓▓▓▓▓▓▓▓▓▓  11/10' in rows


class TestEntriesSection:
    def test_entries_are_grouped_under_their_day(self):
        tuesday = _entry('tuesday', moment=datetime(2026, 9, 29, 20, 0))
        morning, evening = _entry('morning'), _entry('evening', moment=datetime(2026, 9, 30, 18, 30))
        text = _render(tuesday, morning, evening, days=(_day(tuesday), _day(morning, evening)))
        entries = _section(text, 'Entries')
        assert entries.index('### Tue 29 Sep 2026') < entries.index('> tuesday')
        assert entries.index('> tuesday') < entries.index('### Wed 30 Sep 2026')
        assert entries.index('### Wed 30 Sep 2026') < entries.index('> morning') < entries.index('> evening')
        assert entries.count('### ') == 2

    def test_each_entry_shows_time_and_mood(self):
        assert '### Wed 30 Sep 2026\n\n**09:05 — mood 5/10**\n' in _render()

    def test_flagged_entries_are_marked(self):
        entries = _section(_render(_entry('flag me', flagged=True)), 'Entries')
        assert '🚩 **Flagged to raise in session**' in entries

    def test_themes_line_only_when_tagged(self):
        assert 'Themes: work, sleep' in _render(_entry(tags=['work', 'sleep']))
        assert 'Themes:' not in _render(_entry())

    def test_multi_line_entries_stay_quoted(self):
        assert '> line one\n>\n> line two' in _render(_entry('line one\n\nline two'))

    def test_an_empty_entry_is_an_empty_quote(self):
        assert '**09:05 — mood 5/10**\n\n>\n' in _render(_entry(''))

    def test_user_text_cannot_become_markdown_structure(self):
        text = _render(_entry('# not a heading\n- not a list\n  > not nested'))
        assert '> \\# not a heading' in text
        assert '> \\- not a list' in text
        assert '>   \\> not nested' in text


class TestFooter:
    def test_says_what_it_is_not(self):
        assert 'not a clinical record' in _render()
