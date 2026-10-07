"""the brief's editorial layer: the merged day, school lists, mail, projects, news, puzzles wiring."""
import datetime as dt
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

from brief_helpers import FIX, ROOT, TUE, Case, base_brief, brief, ctx_for, ev
from daybook import day as dayshape
from daybook.common import scrub_dashes, scrub_private


class DayShape(Case):
    def test_class_meeting_merges_with_matching_calendar_event(self):
        meetings = [{"day": "today", "class": "CS-2400", "name": "Database Systems", "role": "ta",
                     "time": "11 AM - 12:15 PM", "start": "11:00", "end": "12:15"}]
        out = dayshape.merge_day([ev("11:00", "12:15", "CS 2400 Database Systems")], meetings)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["class"], "CS-2400")
        self.assertEqual(out[0]["role"], "ta")

    def test_class_meeting_missing_from_calendar_is_added(self):
        meetings = [{"day": "today", "class": "CS-1300", "name": "Intro to Programming",
                     "role": "ta", "time": "2 PM - 3:15 PM", "start": "14:00", "end": "15:15"},
                    {"day": "tomorrow", "class": "X", "name": "y", "role": "student", "time": "",
                     "start": "09:00", "end": "10:00"}]
        out = dayshape.merge_day([ev("11:00", "12:00", "CS-1300 Office Hours")], meetings)
        self.assertEqual([e["start"] for e in out], ["11:00", "14:00"])
        self.assertEqual(out[1]["source"], "school")
        self.assertEqual(out[1]["kind"], "ta")
        html = brief.day_rows(out, [], [])
        self.assertIn("from the school folder", html)

    def test_bad_times_dropped_and_all_day_kept_apart(self):
        out = dayshape.merge_day([ev("25:00", "26:00", "bad"), ev("", "", "Holiday"), ev("9:30", "10:00", "ok")], [])
        self.assertEqual([e["title"] for e in out], ["Holiday", "ok"])
        self.assertTrue(out[0]["all_day"])
        self.assertEqual(out[1]["start"], "09:30")

    def test_free_blocks_and_conflicts(self):
        events = dayshape.merge_day([ev("09:00", "10:00", "A"), ev("09:30", "10:30", "B"),
                                     ev("14:00", "15:15", "C")], [])
        blocks = dayshape.free_blocks(events)
        self.assertEqual([(b["start"], b["end"]) for b in blocks], [("08:00", "09:00"), ("10:30", "14:00"),
                                                                     ("15:15", "21:00")])
        self.assertEqual(blocks[1]["minutes"], 210)
        c = dayshape.conflicts(events)
        self.assertEqual([(x["a"], x["b"], x["minutes"]) for x in c], [("A", "B", 30)])

    def test_back_to_back_is_not_a_conflict(self):
        events = dayshape.merge_day([ev("14:00", "15:15", "A"), ev("15:15", "16:45", "B")], [])
        self.assertEqual(dayshape.conflicts(events), [])


class SchoolBuckets(Case):
    def item(self, title, when, overdue=False):
        return {"class": "GEO-2100", "title": title, "overdue": overdue, "sort": when, "due": when}

    def test_today_versus_upcoming(self):
        items = [self.item("late", "2026-10-02T23:59:00-06:00", True),
                 self.item("tonight", "2026-10-06T23:59:00-06:00"),
                 self.item("tomorrow", "2026-10-07T12:00:00-06:00"),
                 self.item("friday", "2026-10-09T23:59:00-06:00"),
                 self.item("later", "2026-10-18T23:59:00-06:00")]
        b = brief.school_buckets(items, TUE)
        self.assertEqual([i["title"] for i in b["overdue"]], ["late"])
        self.assertEqual([i["title"] for i in b["now"]], ["tonight", "tomorrow"])
        self.assertEqual([i["title"] for i in b["week"]], ["friday"])
        self.assertEqual([i["title"] for i in b["later"]], ["later"])

    def test_submitted_assignments_never_return(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "classes" / "geo-2100"
            (d / "assignments").mkdir(parents=True)
            (d / "class.md").write_text('---\ncode: GEO-2100\nrole: student\nschedule: "MW 14:00-15:15"\n'
                                        'starts: 2026-08-24\nends: 2026-12-11\n---\n')
            for name, status in (("hw2", "submitted"), ("hw3", "open"), ("hw4", "completed")):
                (d / "assignments" / f"{name}.md").write_text(
                    f"---\ntitle: {name}\ndue: 2026-10-07T23:59\nstatus: {status}\n---\n")
            ctx = brief.school_context(TUE, Path(tmp))
        self.assertEqual([i["title"] for i in ctx["due_soon"]], ["hw3"])

    def test_meetings_carry_clock_times_and_office_hours(self):
        ctx = brief.school_context(TUE)
        m = [x for x in ctx["class_meetings"] if x["day"] == "today"]
        self.assertTrue(m)
        self.assertTrue(all(re.match(r"^\d\d:\d\d$", x["start"]) for x in m))
        self.assertTrue(any(o["class"] == "CS-1300" for o in ctx["office_hours"]))

    def test_school_off_when_unset(self):
        self.env(DAYBOOK_SCHOOL="")
        ctx = brief.school_context(TUE)
        self.assertTrue(ctx["off"])
        html = brief.render_html(base_brief(), dict(ctx_for(TUE), school=ctx), TUE)
        self.assertNotIn('id="school"', html)
        self.assertIn("no school folder set", html)
        self.assertNotIn("School folder</span><span class=\"st st-unavailable", html)


class Mail(Case):
    def test_off_until_set(self):
        self.assertEqual(brief.mail_context()["status"], "off")

    def test_missing_handoff_is_not_connected(self):
        out = brief.mail_context(Path("/nonexistent/mail.json"))
        self.assertEqual(out["status"], "not_connected")
        self.assertEqual(out["items"], [])

    def test_unapproved_handoff_is_not_connected(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"approved": False, "command": ["/bin/echo", "{}"]}, f)
        self.addCleanup(os.unlink, f.name)
        self.assertEqual(brief.mail_context(Path(f.name))["status"], "not_connected")

    def test_approved_connector_output_is_minimized(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "fake.py"
            item = {"kind": "email", "title": "Exam room change", "from": "prof@example.edu",
                    "received": "2026-10-06T06:10:00-06:00", "due": "", "summary": "x" * 900,
                    "body": "SECRET BODY", "token": "abc"}
            script.write_text("import json\nprint(json.dumps({'fetched_at': '2026-10-06T07:30:00-06:00', "
                              f"'items': [{item!r}] * 30}}))\n")
            h = Path(tmp) / "mail.json"
            h.write_text(json.dumps({"approved": True, "approved_at": "2026-10-01",
                                     "command": ["python3", str(script)]}))
            out = brief.mail_context(h)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(len(out["items"]), brief.MAIL_MAX_ITEMS)
        first = out["items"][0]
        self.assertNotIn("body", first)
        self.assertNotIn("token", first)
        self.assertLessEqual(len(first["summary"]), 300)

    def test_mail_stays_out_of_the_prompt_without_approval(self):
        ctx = ctx_for(TUE)
        ctx["mail"] = {"status": "ok", "send_to_model": False, "note": "", "fetched_at": "",
                       "items": [{"kind": "email", "title": "Grade appeal from a student", "from": "s@example.edu",
                                  "received": "", "due": "", "summary": "private", "source": "mail"}]}
        self.assertNotIn("Grade appeal", brief.build_prompt(TUE, ctx))
        self.assertIn("Grade appeal", brief.render_html(base_brief(), ctx, TUE))
        ctx["mail"]["send_to_model"] = True
        self.assertIn("Grade appeal", brief.build_prompt(TUE, ctx))
        # the model files that mail like gmail, so code stops listing it
        self.assertNotIn("Other mail", brief.render_html(base_brief(), ctx, TUE))

    def test_failing_connector_is_unavailable(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"approved": True, "command": ["/usr/bin/false"]}, f)
        self.addCleanup(os.unlink, f.name)
        self.assertEqual(brief.mail_context(Path(f.name))["status"], "unavailable")

    def test_odd_handoff(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("[1, 2]")
        self.addCleanup(os.unlink, f.name)
        self.assertEqual(brief.mail_context(Path(f.name))["status"], "not_connected")


class Projects(Case):
    def test_reports_keep_latest_section_and_drop_private_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = Path(tmp) / "hd-thing.md"
            r.write_text("## hd-thing at 2026-10-04 10:00\n\nold news\n\n## hd-thing at 2026-10-05 20:00\n\n"
                         "Shipped it. See https://claude.ai/code/session_abc123 and "
                         "a42b8453-da12-4d4d-bcf0-864ac43c9e92.\n\nLeft for you:\n1. approve\n")
            old = Path(tmp) / "hd-old.md"
            old.write_text("## hd-old at 2026-09-01\n\nancient\n")
            os.utime(old, (0, 0))
            now = dt.datetime.now(brief.config.tz())
            out = brief.session_reports(now, Path(tmp))
        self.assertEqual([x["name"] for x in out], ["hd-thing"])
        self.assertIn("Shipped it", out[0]["text"])
        self.assertNotIn("old news", out[0]["text"])
        self.assertNotIn("claude.ai/code", out[0]["text"])
        self.assertNotIn("a42b8453", out[0]["text"])

    def test_adapters_are_off_when_unset(self):
        now = dt.datetime.now(brief.config.tz())
        self.env(DAYBOOK_SESSIONS="", DAYBOOK_PROJECTS="")
        self.assertEqual(brief.session_reports(now), [])
        self.assertEqual(brief.session_list(), [])
        self.assertEqual(brief.git_activity(now), [])
        self.assertEqual(brief.news_candidates(now)["status"], "off")

    def test_session_list_keeps_names_and_states_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "sessions").mkdir()
            (Path(tmp) / "sessions" / "hd-kite.json").write_text(json.dumps(
                {"name": "hd-kite", "status": "busy", "session_id": "secret", "url": "https://claude.ai/x"}))
            (Path(tmp) / "sessions" / "other.json").write_text("{}")
            self.env(DAYBOOK_SESSIONS=tmp)
            self.assertEqual(brief.session_list(), [{"name": "hd-kite", "status": "busy"}])


class NewsAndActions(Case):
    def test_news_filters_stale_future_unsourced_and_dupes(self):
        items = [
            {"headline": "A", "summary": "s", "why": "w", "status": "available", "published": "2026-10-05",
             "source_name": "Lab", "url": "https://example.com/news/a"},
            {"headline": "A again", "summary": "s", "why": "w", "status": "available", "published": "2026-10-05",
             "source_name": "Lab", "url": "https://example.com/news/a"},
            {"headline": "Old", "summary": "s", "why": "w", "status": "announced", "published": "2026-09-20",
             "source_name": "x", "url": "https://example.com/old"},
            {"headline": "Future", "summary": "s", "why": "w", "status": "announced", "published": "2026-10-09",
             "source_name": "x", "url": "https://example.com/f"},
            {"headline": "No link", "summary": "s", "why": "w", "status": "rumor", "published": "2026-10-06",
             "source_name": "x", "url": ""},
            {"headline": "Bad date", "summary": "s", "why": "w", "status": "research", "published": "soon",
             "source_name": "x", "url": "https://example.com/abs/1"},
        ]
        self.assertEqual([n["headline"] for n in brief.clean_news(items, TUE)], ["A"])

    def test_actions_dedupe_and_split(self):
        acts = [{"title": "Grade Lab 4", "why": "", "when": "", "horizon": "today", "kind": "ta",
                 "source": "", "url": ""},
                {"title": "grade lab 4.", "why": "", "when": "", "horizon": "today", "kind": "ta",
                 "source": "", "url": ""},
                {"title": "Study for Exam 1", "why": "", "when": "", "horizon": "this_week", "kind": "school",
                 "source": "", "url": "javascript:alert(1)"}]
        today, week = brief.clean_actions(acts)
        self.assertEqual([a["title"] for a in today], ["Grade Lab 4"])
        self.assertEqual([a["title"] for a in week], ["Study for Exam 1"])
        self.assertEqual(week[0]["url"], "")


class Page(Case):
    def page(self, **kw):
        return brief.render_html(base_brief(**kw), ctx_for(TUE), TUE)

    def test_editorial_sections_present(self):
        news = [{"headline": "Model X ships", "summary": "s", "why": "w", "status": "available",
                 "published": "2026-10-05", "source_name": "Lab", "url": "https://example.com/x"}]
        events = [ev("11:00", "12:00", "CS-1300 Office Hours", kind="ta", detail="In the lab.")]
        html = self.page(news=news, events=events)
        for h in ("Your day", "School", "Movement", "AI news", "Play", "Sources"):
            self.assertIn(h, html, h)
        self.assertIn("Tuesday", html)
        self.assertIn("October 6, 2026", html)
        self.assertIn('href="https://example.com/x"', html)
        self.assertIn("Office Hours", html)
        self.assertNotIn("\u2014", html)

    def test_backticks_become_code_and_stay_escaped(self):
        self.assertEqual(brief.esc_code("run `claude logs <x>` now"), "run <code>claude logs &lt;x&gt;</code> now")
        self.assertEqual(brief.esc_code("run `claude attach` now"), "run <code>claude attach</code> now")

    def test_quiet_news_is_truthful(self):
        html = self.page(news=[], news_note="")
        self.assertIn("No AI news from the last day cleared the bar", html)

    def test_second_mailbox_off_is_said_plainly(self):
        html = self.page()
        self.assertIn("Second mailbox", html)
        self.assertIn('class="st st-off">off<', html)
        self.assertIn("no second mailbox set", html)

    def test_hero_is_deterministic_and_svg_only(self):
        a = brief.hero_svg(TUE, [])
        self.assertEqual(a, brief.hero_svg(TUE, []))
        self.assertNotEqual(a, brief.hero_svg(TUE + dt.timedelta(days=1), []))
        self.assertTrue(a.startswith("<svg"))
        self.assertNotIn("<script", a)
        self.assertNotIn("<image", a)

    def test_page_survives_missing_new_fields(self):
        # an old-shape brief.json must still render (brief render on past dates)
        old = {"day_class": "OPEN", "headline": "h", "terrain_svg": "", "acts": [], "needs_attention": [],
               "resolved": [], "todoist_schedule": [], "in_lecture": [], "movement": "", "source_status": []}
        html = brief.render_html(old, ctx_for(TUE), TUE)
        self.assertIn("School", html)


class WeeklyWiring(Case):
    """friday: the model clues the week's crossword once; every page that week reads the saved clues"""
    FRI = dt.date(2026, 10, 9)

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env(DAYBOOK_BRIEFS=Path(self.tmp.name) / "briefs", DAYBOOK_DATA=Path(self.tmp.name) / "data")
        self.pz = brief.load_puzzles()

    def test_ask_on_friday_then_save_and_reuse_all_week(self):
        ents = brief.weekly_ask(self.FRI)
        self.assertEqual(ents, self.pz.weekly_entries(self.FRI))
        prompt = brief.build_prompt(self.FRI, dict(ctx_for(self.FRI), weather={}, news={"items": []}), ents)
        self.assertIn(f'{ents[0]["answer"]} {ents[0]["enum"]}', prompt)
        self.assertNotIn("{{WEEKLY}}", prompt)
        day_dir = brief.briefs() / self.FRI.isoformat()
        day_dir.mkdir(parents=True)
        got = [{"answer": e["answer"], "clue": f"Model clue number {i}"} for i, e in enumerate(ents)]
        got[0]["clue"] = f"Has {ents[0]['answer'].lower()} inside"  # leaks, so the bank clue stays
        brief.weekly_save(self.FRI, ents, got, day_dir)
        saved = json.loads((day_dir / "weekly.json").read_text())
        self.assertEqual(saved["week"], self.FRI.isoformat())
        self.assertEqual(len(saved["clues"]), len(ents) - 1)
        self.assertNotIn(ents[0]["answer"], saved["clues"])
        self.assertIsNone(brief.weekly_ask(self.FRI + dt.timedelta(days=3)))  # monday: already clued
        page = brief.render_html(base_brief(), ctx_for(self.FRI + dt.timedelta(days=3)), self.FRI + dt.timedelta(days=3))
        self.assertIn("Model clue number 1", page)
        self.assertEqual(page.count('class="pz-pick"'), 6)
        self.assertNotIn("Last week", page)  # only on fridays

    def test_half_clean_or_nothing(self):
        ents = brief.weekly_ask(self.FRI)
        day_dir = brief.briefs() / self.FRI.isoformat()
        day_dir.mkdir(parents=True)
        brief.weekly_save(self.FRI, ents, [{"answer": ents[0]["answer"], "clue": "Only one"}], day_dir)
        self.assertFalse((day_dir / "weekly.json").exists())
        self.assertEqual(brief.weekly_ask(self.FRI + dt.timedelta(days=1)), ents)  # saturday asks again
        brief.weekly_save(self.FRI, None, None, day_dir)  # not asked: nothing happens

    def test_friday_page_prints_the_weekly_and_last_weeks_answers(self):
        prev = brief.briefs() / (self.FRI - dt.timedelta(days=3)).isoformat()
        prev.mkdir(parents=True, exist_ok=True)
        (prev / "brief.html").write_text('<div data-game="weekly"></div>')  # last week's grid was shown
        page = brief.render_html(base_brief(), ctx_for(self.FRI), self.FRI)
        last = self.pz.weekly_answers_for(self.FRI)
        self.assertIn("Last week", page)
        self.assertIn(last["answer_text"].split(";")[0][:40], page)
        self.assertNotIn('class="puzzle puzzle-weekly wk-short"', page)
        self.assertIn('class="puzzle puzzle-weekly"', page)
        tue = brief.render_html(base_brief(), ctx_for(TUE), TUE)
        self.assertIn('class="puzzle puzzle-weekly wk-short"', tue)
        self.assertIn("runs until Thursday", tue)

    def test_bad_weekly_file_falls_back_to_bank_clues(self):
        d = brief.briefs() / self.FRI.isoformat()
        d.mkdir(parents=True)
        (d / "weekly.json").write_text("[1, 2]")
        self.assertEqual(brief.weekly_clues(self.pz, self.FRI), {})
        page = brief.render_html(base_brief(), ctx_for(self.FRI), self.FRI)
        self.assertIn('data-puzzles="ok"', page)

    def stub(self, fake_pdf, fake_check, chrome="/fake/chrome", validate=True):
        names = ("html_to_pdf", "validate_pdf", "web_up", "find_chrome", "can_validate")
        old = {n: getattr(brief, n) for n in names}
        brief.html_to_pdf, brief.validate_pdf = fake_pdf, fake_check
        brief.web_up, brief.find_chrome, brief.can_validate = (lambda: False), (lambda: chrome), (lambda: validate)
        self.addCleanup(lambda: [setattr(brief, n, f) for n, f in old.items()])

    def test_puzzles_step_down_until_the_pdf_fits(self):
        # a long friday: the full weekly, then its one-line form, then puzzles off paper. never no brief
        calls = []

        def fake_pdf(html_file, pdf, chrome=None):
            calls.append(html_file.read_text())
            pdf.write_text("pdf")

        def fake_check(pdf, b, day, school=True):
            if len(calls) < 3:
                raise brief.PageCount(f"pdf has {9 - len(calls)} pages")
            return 7, 100
        self.stub(fake_pdf, fake_check)
        (brief.briefs() / self.FRI.isoformat()).mkdir(parents=True)
        brief.render(self.FRI, base_brief(source_status=[]), ctx_for(self.FRI))
        self.assertEqual(len(calls), 3)
        self.assertIn('class="puzzle puzzle-weekly"', calls[0])
        self.assertIn('class="puzzle puzzle-weekly wk-short"', calls[1])
        self.assertIn('pz-games print-skip', calls[2])
        self.assertIn("did not fit on paper", calls[2])
        self.assertTrue(brief.pdf_path(self.FRI).exists())
        log = (brief.briefs() / self.FRI.isoformat() / "run.log").read_text()
        self.assertIn("with puzzles printed full", log)
        self.assertIn("with puzzles printed short", log)

    def test_no_chrome_is_never_a_failure(self):
        self.stub(None, None, chrome=None)
        out = brief.render(TUE, base_brief(source_status=[]), ctx_for(TUE))
        d = brief.briefs() / TUE.isoformat()
        self.assertEqual(out, d / "brief.html")
        self.assertTrue((d / "brief.html").exists())
        self.assertTrue((d / "puzzles.json").exists())
        self.assertFalse(brief.pdf_path(TUE).exists())
        self.assertNotIn("PDF version", (d / "brief.html").read_text())
        meta = json.loads((d / "meta.json").read_text())
        self.assertEqual(meta["pdf"], "")
        self.assertIn("no Chrome", meta["pdf_note"])

    def test_pdf_without_the_text_check_off_macos(self):
        def fake_pdf(html_file, pdf, chrome=None):
            pdf.write_text("pdf")

        def no_check(*a, **k):
            raise AssertionError("must not validate")
        self.stub(fake_pdf, no_check, validate=False)
        brief.render(TUE, base_brief(source_status=[]), ctx_for(TUE))
        meta = json.loads((brief.briefs() / TUE.isoformat() / "meta.json").read_text())
        self.assertTrue(meta["pdf"])
        self.assertIn("not checked", meta["pdf_note"])
        self.assertIn("PDF version", (brief.briefs() / TUE.isoformat() / "brief.html").read_text())

    def test_chrome_failure_keeps_the_page(self):
        def bad_pdf(html_file, pdf, chrome=None):
            raise RuntimeError("chrome produced no pdf")
        self.stub(bad_pdf, None)
        out = brief.render(TUE, base_brief(source_status=[]), ctx_for(TUE))
        self.assertEqual(out.name, "brief.html")
        meta = json.loads((brief.briefs() / TUE.isoformat() / "meta.json").read_text())
        self.assertIn("pdf failed", meta["pdf_note"])
        self.assertNotIn("PDF version", out.read_text())

    def test_schema_has_the_clue_field(self):
        sch = json.loads((ROOT / "prompt" / "schema.json").read_text())
        self.assertIn("weekly_clues", sch["required"])
        item = sch["properties"]["weekly_clues"]["items"]
        self.assertEqual(item["required"], ["answer", "clue"])


class VerifierFindings(Case):
    def test_late_and_overnight_events_do_not_crash(self):
        evs = [ev("23:45", "", "late"), ev("23:50", "23:40", "backwards"), ev("22:00", "01:00", "overnight"),
               ev("14:00:00", "15:00:00", "seconds")]
        out = dayshape.merge_day(evs, [{"day": "today", "class": "X-1", "name": "late", "role": "student",
                                        "time": "", "start": "23:30", "end": "23:59"}])
        self.assertEqual([e["end"] for e in out if e["title"] == "overnight"], ["23:59"])
        self.assertIn("seconds", [e["title"] for e in out])
        dayshape.free_blocks(out)
        dayshape.conflicts(out)
        brief.render_html(base_brief(events=evs), ctx_for(TUE), TUE)

    def test_yesterday_answers_come_from_saved_file_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.env(DAYBOOK_BRIEFS=tmp)
            page = brief.render_html(base_brief(), ctx_for(TUE), TUE)
            self.assertNotIn("Yesterday", page)
            y = Path(tmp) / "2026-10-05"
            y.mkdir()
            (y / "puzzles.json").write_text(json.dumps([{"title": "Rungs", "answer_text": "COLD, CORD"}]))
            page = brief.render_html(base_brief(), ctx_for(TUE), TUE)
            self.assertIn("COLD, CORD", page)

    def test_bad_yesterday_does_not_cost_today(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.env(DAYBOOK_BRIEFS=tmp)
            y = Path(tmp) / "2026-10-05"
            y.mkdir()
            (y / "puzzles.json").write_text("not json")
            page = brief.render_html(base_brief(), ctx_for(TUE), TUE)
        self.assertIn('data-puzzles="ok"', page)

    def test_odd_ids(self):
        self.assertNotIn("A42B8453", scrub_private("id A42B8453-DA12-4D4D-BCF0-864AC43C9E92"))
        self.assertEqual(scrub_dashes("a \u2e3a b \u2e3b c"), "a, b, c")


class ShortClassNames(Case):
    """calendar titles abbreviate class names; they are still the same meeting."""

    def test_abbreviated_titles_merge(self):
        meetings = [{"day": "today", "class": "STAT-3100", "name": "Statistical Pattern Recognition", "role": "student",
                     "time": "", "start": "14:00", "end": "15:15"},
                    {"day": "today", "class": "MATH-5200", "name": "Advanced Mathematical Modeling", "role": "student",
                     "time": "", "start": "15:30", "end": "16:45"}]
        out = dayshape.merge_day([ev("14:00", "15:15", "Stat Pattern Recognition", where="Hall 120"),
                                  ev("15:30", "16:45", "Adv Mathematical Model", where="Hall 314")], meetings)
        self.assertEqual([e["class"] for e in out], ["STAT-3100", "MATH-5200"])
        self.assertEqual(dayshape.conflicts(out), [])

    def test_unrelated_overlap_stays_separate(self):
        meetings = [{"day": "today", "class": "CS-2400", "name": "Database Systems", "role": "ta",
                     "time": "", "start": "11:00", "end": "12:15"}]
        out = dayshape.merge_day([ev("11:00", "12:00", "CS-1300 Office Hours")], meetings)
        self.assertEqual(len(out), 2)


class LastWeekGate(Case):
    """last week's crossword answers print only if last week's crossword was actually shown."""

    def page(self, tmp, shown):
        fri = dt.date(2026, 10, 9)
        self.env(DAYBOOK_BRIEFS=tmp)
        if shown:
            d = Path(tmp) / "2026-10-05"
            d.mkdir()
            (d / "brief.html").write_text('<div data-game="weekly"></div>')
        return brief.render_html(base_brief(), ctx_for(fri), fri)

    def test_first_friday_has_no_last_week(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertNotIn("Last week", self.page(tmp, False))

    def test_later_friday_shows_last_week(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIn("Last week", self.page(tmp, True))


if __name__ == "__main__":
    unittest.main()
