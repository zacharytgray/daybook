import datetime as dt
import json
import os
import re
import tempfile
import threading
import unittest
from pathlib import Path

from brief_helpers import FIX, ROOT, TUE, Case, base_brief, brief, ctx_for, ev  # noqa: F401
from daybook.common import scrub_dashes, scrub_private, split_frontmatter

SAT, SUN, MON = dt.date(2026, 10, 3), dt.date(2026, 10, 4), dt.date(2026, 10, 5)


class TmpBriefs(Case):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env(DAYBOOK_BRIEFS=self.root / "briefs", DAYBOOK_DATA=self.root / "data")


class Weekends(TmpBriefs):
    """the brief runs every day; nothing may skip a weekend date."""

    def fake_pdf(self, day):
        d = brief.briefs() / day.isoformat()
        d.mkdir(parents=True)
        brief.pdf_path(day).write_bytes(b"%PDF-1.4 test")
        (d / "meta.json").write_text(json.dumps({"source_gaps": []}))

    def test_deliver_payload_every_day_of_week(self):
        for i in range(7):
            day = SAT + dt.timedelta(days=i)
            self.fake_pdf(day)
            out = brief.deliver(day)
            self.assertIn(f"MEDIA:{brief.pdf_path(day)}", out, day.strftime("%A"))

    def test_second_deliver_same_date_is_silent(self):
        self.fake_pdf(SUN)
        self.assertTrue(brief.deliver(SUN))
        self.assertEqual(brief.deliver(SUN), "")
        self.assertTrue(brief.deliver(SUN, force=True))

    def test_no_pdf_hands_off_the_local_page(self):
        d = brief.briefs() / SUN.isoformat()
        d.mkdir(parents=True)
        (d / "meta.json").write_text(json.dumps({"source_gaps": ["Gmail"]}))
        out = brief.deliver(SUN)
        self.assertIn("Morning Brief for Sunday, October 4. Not fully checked: Gmail.", out)
        self.assertIn("file://", out)
        self.assertNotIn("MEDIA:", out)

    def test_school_context_on_weekend(self):
        for day in (SAT, SUN):
            ctx = brief.school_context(day)
            self.assertEqual(ctx["date"], day.isoformat())
            self.assertFalse([m for m in ctx["class_meetings"] if m["day"] == "today"], "no classes on weekends")
        self.assertTrue([m for m in brief.school_context(SUN)["class_meetings"] if m["day"] == "tomorrow"],
                        "sunday sees monday's classes as tomorrow")

    def test_prompt_builds_for_weekend(self):
        p = brief.build_prompt(SUN, {"school": brief.school_context(SUN), "prs": []})
        self.assertIn("Sunday, October 4, 2026", p)
        self.assertNotIn("{{", p)


class Parsing(Case):
    def test_quoted_hash_survives(self):
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
            f.write('---\ntitle: "Live Session #4 - Points"\nrole: ta  # student | ta\n---\nbody\n')
        self.addCleanup(os.unlink, f.name)
        fm, body = split_frontmatter(Path(f.name))
        self.assertEqual(fm["title"], "Live Session #4 - Points")
        self.assertEqual(fm["role"], "ta")

    def test_no_em_dash(self):
        self.assertEqual(scrub_dashes("\u2014 a \u2014 b"), "a, b")

    def test_missing_sources_are_flagged(self):
        b = brief.enforce_sources({"source_status": []}, {"claude.ai Gmail": "failed"})
        status = {s["source"]: s["status"] for s in b["source_status"]}
        self.assertEqual(status["Gmail"], "unavailable")
        self.assertEqual(status["Google Calendar"], "unavailable")
        self.assertEqual(status["Weather"], "unavailable")
        # no todoist connector at all is a choice, not a gap
        self.assertEqual(status["Todoist"], "off")


class TaGrading(Case):
    """past student cutoffs in TA classes are not owed work; only grading: true records are."""

    DONE_TITLES = ["Project 1: Linear & Logistic Regression", "Homework 1 (fall)"]

    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.env(DAYBOOK_SCHOOL=root, DAYBOOK_BRIEFS=root / "briefs")

        def write(cls, name, fm, role="ta", code=None):
            d = root / "classes" / cls
            (d / "assignments").mkdir(parents=True, exist_ok=True)
            (d / "class.md").write_text(f'---\ncode: {code or cls.upper()}\nrole: {role}  # student | ta\n'
                                        'schedule: "TR 11:00-12:15"\nstarts: 2026-08-24\nends: 2026-12-11\n---\n')
            (d / "assignments" / name).write_text("---\n" + fm + "\n---\nbody\n")

        # two student cutoffs that passed in TA classes
        write("cs-1300", "project-1-linear-logistic-regression.md",
              'title: "Project 1: Linear & Logistic Regression"\ndue: 2026-09-18T23:59\nstatus: open\ntodoist_task_id: ""')
        write("cs-2400", "homework-1.md",
              'title: "Homework 1 (fall)"\ndue: 2026-09-18T23:59\nstatus: open\ntodoist_task_id: ""')
        write("cs-2400", "homework-1-grading.md",
              'title: "Grade assigned portion of Homework 1"\ndue: 2026-09-28\nstatus: graded\ngrading: true')
        # still-live TA work must keep showing
        write("cs-2400", "homework-2-grading.md",
              'title: "Grade assigned portion of Homework 2"\ndue: 2026-10-02\nstatus: open\ngrading: true')
        write("cs-1300", "project-2-naive-bayes.md",
              'title: "Project 2: Naive Bayes"\ndue: 2026-10-05T23:59\nstatus: open')
        write("geo-2100", "homework-2.md", 'title: "Homework 2"\ndue: 2026-09-30T23:59\nstatus: open',
              role="student")
        self.ctx = brief.school_context(SAT)

    def html(self):
        b = {"headline": "h", "terrain_svg": "", "acts": [], "needs_attention": [], "resolved": [],
             "todoist_schedule": [], "in_lecture": [], "movement": "", "source_status": []}
        page = brief.render_html(b, {"school": self.ctx, "prs": []}, SAT)
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))

    def test_done_grading_titles_never_listed_as_owed(self):
        owed = [i["title"] for i in self.ctx["to_grade"]]
        page = self.html()
        for title in self.DONE_TITLES:
            self.assertNotIn(title, owed)
            self.assertNotIn(brief.esc(title), page)

    def test_completed_evidence_is_kept(self):
        closed = [i["title"] for i in self.ctx["ta_cutoffs_closed"]]
        for title in self.DONE_TITLES:
            self.assertIn(title, closed)
        done = self.ctx["ta_grading_done"]
        self.assertEqual([(d["title"], d["status"]) for d in done], [("Grade assigned portion of Homework 1", "graded")])

    def test_live_ta_work_still_shows(self):
        by_title = {i["title"]: i for i in self.ctx["to_grade"]}
        self.assertEqual(by_title["Grade assigned portion of Homework 2"]["kind"], "grading")
        self.assertTrue(by_title["Grade assigned portion of Homework 2"]["overdue"])
        self.assertEqual(by_title["Project 2: Naive Bayes"]["kind"], "students_due")
        page = self.html()
        self.assertIn("Grade assigned portion of Homework 2 grade by", page)
        self.assertIn("Project 2: Naive Bayes students submit", page)
        self.assertNotIn("submissions closed", page)

    def test_student_class_overdue_unchanged(self):
        self.assertEqual([(i["title"], i["overdue"]) for i in self.ctx["due_soon"]], [("Homework 2", True)])

    def test_decisions_file_is_optional(self):
        self.assertEqual(self.ctx["decisions_owed"], [])
        self.assertFalse([p for p in self.ctx["problems"] if "decisions" in p])
        (Path(os.environ["DAYBOOK_SCHOOL"]) / "inbox").mkdir()
        (Path(os.environ["DAYBOOK_SCHOOL"]) / "inbox" / "decisions.md").write_text("# d\n\n## 2026-10-02: Late work rule\n")
        ctx = brief.school_context(SAT)
        self.assertEqual(ctx["decisions_owed"], ["2026-10-02: Late work rule"])
        page = brief.render_html(base_brief(), dict(ctx_for(SAT), school=ctx), SAT)
        self.assertIn("1 decision owed</b> in inbox/decisions.md. Newest: Late work rule.", page)


class Web(TmpBriefs):
    """the server answers brief.html and the pdf for each date, and nothing else."""

    def setUp(self):
        super().setUp()
        for day in ("2026-10-05", "2026-10-06"):
            d = brief.briefs() / day
            d.mkdir(parents=True)
            (d / "brief.html").write_text(f"<html>brief {day}</html>")
            (d / f"morning-brief-{day}.pdf").write_bytes(b"%PDF-1.4 x")
            (d / "context.json").write_text('{"secret": 1}')
            (d / "meta.json").write_text(json.dumps({"source_gaps": []}))
        self.srv = brief.make_server("127.0.0.1", 0)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def get(self, path, host=None):
        import urllib.error
        import urllib.request

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        req = urllib.request.Request(self.base + path, headers={"Host": host} if host else {})
        try:
            with urllib.request.build_opener(NoRedirect).open(req, timeout=5) as r:
                return r.status, r.read().decode(errors="replace"), dict(r.headers)
        except urllib.error.HTTPError as e:
            e.close()
            return e.code, "", dict(e.headers)

    def test_routes(self):
        code, body, headers = self.get("/2026-10-06/")
        self.assertEqual((code, body), (200, "<html>brief 2026-10-06</html>"))
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        self.assertNotIn("Access-Control-Allow-Origin", headers)
        self.assertEqual(self.get("/2026-10-06/morning-brief-2026-10-06.pdf")[0], 200)
        code, _, headers = self.get("/")
        self.assertEqual(code, 302)
        self.assertEqual(headers["Location"], "/2026-10-06/")
        self.assertEqual(self.get("/health")[0], 200)

    def test_private_files_and_traversal_are_refused(self):
        for path in ("/2026-10-06/context.json", "/2026-10-06/brief.json", "/2026-10-06/run.log",
                     "/../daybook/brief.py", "/2026-10-06/../../daybook/brief.py", "/2026-10-07/",
                     "/2026-10-06/morning-brief-2026-10-05.pdf"):
            self.assertEqual(self.get(path)[0], 404, path)

    def test_foreign_host_names_are_refused(self):
        self.assertEqual(self.get("/2026-10-06/", host="evil.example.com")[0], 421)
        for ok in ("localhost:8735", "desk", "[::1]:8735", "192.0.2.10:8735"):
            self.assertEqual(self.get("/health", host=ok)[0], 200, ok)
        # dotted names, tailnet ones included, only when listed (the board's rule)
        self.assertEqual(self.get("/health", host="desk.tail1234.ts.net")[0], 421)
        self.env(DAYBOOK_ALLOWED_HOSTS="brief.example.org,.tail1234.ts.net")
        self.assertEqual(self.get("/health", host="brief.example.org")[0], 200)
        self.assertEqual(self.get("/health", host="desk.tail1234.ts.net")[0], 200)

    def test_deliver_sends_link_when_hosting_is_live(self):
        self.env(DAYBOOK_BRIEF_WEB=self.base)
        out = brief.deliver(TUE)
        self.assertIn(f"{self.base}/2026-10-06/", out)
        self.assertNotIn("MEDIA:", out)

    def test_deliver_falls_back_to_pdf_when_hosting_is_down(self):
        out = brief.deliver(TUE)
        self.assertIn(f"MEDIA:{brief.pdf_path(TUE)}", out)


class Feeds(Case):
    def now(self):
        return dt.datetime(2026, 10, 6, 7, 30, tzinfo=brief.config.tz())

    def test_atom_keeps_recent_releases_and_drops_prereleases(self):
        xml = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
        <entry><title>v0.31.0</title><link rel="alternate" href="https://example.com/v/releases/tag/v0.31.0"/>
          <updated>2026-10-05T06:45:00Z</updated><content type="html">&lt;p&gt;preload cache&lt;/p&gt;</content></entry>
        <entry><title>v0.40.0-rc2</title><link href="https://example.com/o/rc2"/><updated>2026-10-05T10:00:00Z</updated></entry>
        <entry><title>rust-v0.161.0-alpha.3</title><link href="https://example.com/c/a3"/><updated>2026-10-05T10:00:00Z</updated></entry>
        <entry><title>b11434: kernel updates</title><link href="https://example.com/l/b"/><updated>2026-10-05T10:00:00Z</updated></entry>
        <entry><title>v0.29.0</title><link href="https://example.com/v/old"/><updated>2026-09-20T10:00:00Z</updated></entry>
        </feed>"""
        out = brief.parse_feed(xml, "Runtime", self.now())
        self.assertEqual([(i["title"], i["published"]) for i in out], [("v0.31.0", "2026-10-05")])
        self.assertEqual(out[0]["summary"], "preload cache")

    def test_rss_dates(self):
        xml = """<rss><channel><item><title>Text provenance</title><link>https://example.com/index/tp</link>
        <pubDate>Mon, 05 Oct 2026 15:00:00 GMT</pubDate><description>policy</description></item>
        <item><title>Future</title><link>https://example.com/f</link><pubDate>Fri, 09 Oct 2026 15:00:00 GMT</pubDate></item>
        </channel></rss>"""
        out = brief.parse_feed(xml, "Lab", self.now())
        self.assertEqual([i["title"] for i in out], ["Text provenance"])

    def test_feed_date_overrides_model_date(self):
        cands = [{"source": "Runtime", "title": "v0.31.0", "url": "https://example.com/v/releases/tag/v0.31.0",
                  "published": "2026-10-05", "summary": ""}]
        items = [{"headline": "Runtime 0.31", "summary": "s", "why": "", "status": "update", "published": "2025-10-05",
                  "source_name": "Example", "url": "https://example.com/v/releases/tag/v0.31.0"}]
        out = brief.clean_news(items, TUE, cands)
        self.assertEqual(out[0]["published"], "2026-10-05")

    def test_garbage_feed_is_empty(self):
        self.assertEqual(brief.parse_feed("<html>nope", "x", self.now()), [])

    def test_feeds_file_parsing(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write("# comment\nLab\thttps://example.com/feed.xml\nno tab here\n\n")
        self.addCleanup(os.unlink, f.name)
        self.assertEqual(brief.read_feeds(f.name), [["Lab", "https://example.com/feed.xml"]])
        self.assertEqual(brief.read_feeds("/nonexistent/feeds.txt"), [])


def write_marks(tmp, marks):
    p = Path(tmp) / "marks.json"
    p.write_text(json.dumps({"updated": "2026-10-06T06:00:00-06:00", "marks": marks}))
    return p


def mark(title, state="done", at="2026-10-05T18:00:00-06:00", until=None, ref="", source="todoist"):
    return {"id": "m-" + title[:4], "title": title, "norm": brief.norm(title), "source": source, "ref": ref,
            "state": state, "until": until, "at": at}


class Marks(Case):
    """the board's done, snoozed and dismissed marks keep handled to-dos out of the brief."""

    def test_active_window(self):
        self.assertTrue(brief.mark_active(mark("a"), TUE))
        self.assertTrue(brief.mark_active(mark("a", "dismissed", at="2026-09-22T09:00:00Z"), TUE))
        self.assertFalse(brief.mark_active(mark("a", at="2026-09-20T09:00:00-06:00"), TUE))
        self.assertTrue(brief.mark_active(mark("a", "snoozed", until="2026-10-07"), TUE))
        self.assertFalse(brief.mark_active(mark("a", "snoozed", until="2026-10-06"), TUE))
        self.assertFalse(brief.mark_active(mark("a", "snoozed", until=None), TUE))
        self.assertFalse(brief.mark_active(mark("a", "maybe"), TUE))
        self.assertFalse(brief.mark_active(mark("a", at="yesterday"), TUE))

    def test_load_keeps_active_and_minimizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write_marks(tmp, [mark("Call the plumber back", ref="", source="manual"),
                                  mark("Old thing", at="2026-08-01T09:00:00-06:00"),
                                  {"title": "No norm given", "state": "done", "at": "2026-10-06T07:00:00-06:00"},
                                  "garbage", {"state": "done", "at": "2026-10-06T07:00:00-06:00"}])
            got = brief.load_marks(TUE, p)
        self.assertEqual(got["status"], "ok")
        self.assertEqual([m["norm"] for m in got["items"]], ["no norm given", "call the plumber back"])  # newest first
        self.assertNotIn("at", got["items"][0])
        self.assertIn("from the board", got["note"])

    def test_setting_points_at_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write_marks(tmp, [mark("Call the bank")])
            self.env(DAYBOOK_MARKS=p)
            self.assertEqual(len(brief.load_marks(TUE)["items"]), 1)
            # empty DAYBOOK_MARKS falls back to <DAYBOOK_DATA>/marks.json
            self.env(DAYBOOK_MARKS="", DAYBOOK_DATA=tmp)
            self.assertEqual(len(brief.load_marks(TUE)["items"]), 1)

    def test_missing_or_malformed_file_is_no_marks(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(brief.load_marks(TUE, Path(tmp) / "nope.json"),
                             {"status": "none", "items": [], "note": "no marks file"})
            bad = Path(tmp) / "bad.json"
            bad.write_text("{not json")
            self.assertEqual(brief.load_marks(TUE, bad)["status"], "unavailable")
            bad.write_text(json.dumps({"marks": "nope"}))
            self.assertEqual(brief.load_marks(TUE, bad)["status"], "unavailable")
            bad.write_text("[]")
            self.assertEqual(brief.load_marks(TUE, bad)["items"], [])

    def test_drop_by_norm_and_by_todoist_ref(self):
        b = base_brief(
            next_actions=[{"title": "Call the plumber back.", "kind": "personal"}, {"title": "Renew passport", "kind": "task"},
                          {"title": "Grade Lab 4", "kind": "ta"}],
            todoist_schedule=[{"id": "111", "title": "Renew passport", "sentence": "s"},
                              {"id": "222", "title": "call the plumber back", "sentence": "s"},
                              {"id": "333", "title": "Buy coffee", "sentence": "s"}])
        marks = [mark("Call the plumber back", source="manual"), dict(mark("renew it", ref="111"), norm="renew it")]
        out, gone = brief.drop_marked(b, marks)
        self.assertEqual([a["title"] for a in out["next_actions"]], ["Grade Lab 4"])
        self.assertEqual([t["id"] for t in out["todoist_schedule"]], ["333"])
        self.assertEqual(len(gone), 4)
        self.assertEqual(brief.drop_marked(b, [])[0], b)

    def test_prompt_lists_marked_titles_and_workdirs(self):
        ctx = ctx_for(TUE, workdirs={"GEO-2100": "/x/coursework/geo"})
        ctx["marks"] = {"status": "ok", "items": [dict(mark("Call the plumber back"), norm="call the plumber back")]}
        ctx["weather"] = {"status": "unavailable"}
        p = brief.build_prompt(TUE, ctx)
        self.assertIn('MARKED (titles', p)
        self.assertIn('["Call the plumber back"]', p)
        self.assertIn('"workdirs":{"GEO-2100":"/x/coursework/geo"}', p)
        del ctx["marks"]
        self.assertIn("on the board, computed by code):\nnone", brief.build_prompt(TUE, ctx))

    def test_sources_row_only_when_the_file_exists(self):
        ctx = ctx_for(TUE)
        names = lambda c: [r[0] for r in brief.source_rows(base_brief(), c)]
        self.assertNotIn("Board marks", names(ctx))
        ctx["marks"] = {"status": "none", "items": [], "note": "no marks file"}
        self.assertNotIn("Board marks", names(ctx))
        ctx["marks"] = {"status": "unavailable", "items": [], "note": "marks file malformed"}
        self.assertIn("Board marks", names(ctx))


class MarksNeverRaise(Case):
    """nothing the board writes can abort generate."""

    def test_overflowing_and_odd_marks_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write_marks(tmp, [mark("Far future", at="9999-12-31T23:59:59-12:00"),
                                  mark("Far past", at="0001-01-01T00:00:00+14:00"),
                                  mark("Big until", "snoozed", until="99999-01-01"),
                                  dict(mark("List title"), title=["x"], norm=None),
                                  {"state": {"a": 1}, "at": []}, None, 7,
                                  mark("Fine one")])
            got = brief.load_marks(TUE, p)
        self.assertEqual(got["status"], "ok")
        self.assertIn("fine one", [m["norm"] for m in got["items"]])

    def test_huge_file_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "marks.json"
            p.write_text(json.dumps({"marks": [mark("x" * 100)] * 9000}))
            self.assertGreater(p.stat().st_size, brief.MARKS_MAX_BYTES)
            self.assertEqual(brief.load_marks(TUE, p),
                             {"status": "unavailable", "items": [], "note": "marks file too large"})

    def test_deep_json_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "marks.json"
            p.write_text("[" * 200000 + "]" * 200000)
            self.assertEqual(brief.load_marks(TUE, p)["status"], "unavailable")

    def test_prompt_gets_the_newest_forty_with_short_titles(self):
        marks = [mark(f"task {i:02d} " + "y" * 200, at=f"2026-10-0{1 + i % 5}T{i % 24:02d}:00:00-06:00")
                 for i in range(60)]
        with tempfile.TemporaryDirectory() as tmp:
            every = brief.load_marks(TUE, write_marks(tmp, marks))["items"]
        self.assertEqual(len(every), 60)
        got = every[:brief.MARKS_MAX]
        self.assertTrue(all(len(m["title"]) <= brief.MARK_TITLE for m in every))
        # the prompt sees forty, but an older mark still drops its to-do
        old = next(m["title"] for m in marks if m["title"].startswith(every[-1]["title"][:8]))
        b, gone = brief.drop_marked({"next_actions": [{"title": old}], "todoist_schedule": []}, every)
        self.assertEqual(gone, [old])
        times = [brief.mark_time(m) for m in marks]
        newest = sorted(range(60), key=lambda i: times[i], reverse=True)[:40]
        self.assertEqual({m["title"][:7] for m in got}, {f"task {i:02d}" for i in newest})


def check(schema, v, path="$"):
    """the slice of json schema that prompt/schema.json uses for the hand-off."""
    if schema.get("type") == "object":
        assert isinstance(v, dict), path
        assert set(schema["required"]) <= set(v), f"{path} missing {set(schema['required']) - set(v)}"
        if schema.get("additionalProperties") is False:
            assert set(v) <= set(schema["properties"]), f"{path} extra {set(v) - set(schema['properties'])}"
        for k, sub in schema["properties"].items():
            if k in v:
                check(sub, v[k], f"{path}.{k}")
    elif schema.get("type") == "string":
        assert isinstance(v, str), path
        assert "enum" not in schema or v in schema["enum"], f"{path}={v!r}"
        assert "pattern" not in schema or re.match(schema["pattern"], v), f"{path}={v!r}"


class Handoff(Case):
    """each next action carries suggested defaults for the board's hand-off panel."""

    def schema(self):
        return json.loads((ROOT / "prompt" / "schema.json").read_text())["properties"]["next_actions"]["items"]

    def test_schema_requires_a_closed_handoff_object(self):
        item = self.schema()
        self.assertIn("handoff", item["required"])
        r = item["properties"]["handoff"]
        good = {"runner": "claude", "model": "default", "where": str(FIX / "projects" / "x"), "reach": "branch",
                "prompt": "Fix the failing test."}
        check(r, good)
        check(r, dict(good, runner="agent", model="opus"))
        for bad in (dict(good, runner="human"), dict(good, reach="push"), dict(good, extra=1),
                    dict(good, model="Not A Model!"), {k: v for k, v in good.items() if k != "prompt"}):
            with self.assertRaises(AssertionError):
                check(r, bad)

    def test_where_must_be_inside_an_allowed_root(self):
        pj, wk = str(FIX / "projects"), str(FIX / "work")
        self.assertEqual(brief.safe_where(pj + "/garden"), pj + "/garden")
        self.assertEqual(brief.safe_where(pj + "/garden/"), pj + "/garden")
        self.assertEqual(brief.safe_where(wk + "/cs-1300"), wk + "/cs-1300")
        for bad in ("", "projects/x", "/etc", pj + "/../.ssh", pj + "X/repo", str(FIX), None, 3, "~/projects/x"):
            self.assertEqual(brief.safe_where(bad), "", bad)

    def test_no_roots_means_no_where(self):
        self.env(DAYBOOK_PROJECTS="", DAYBOOK_WORK_ROOTS="")
        self.assertEqual(brief.where_roots(), [])
        self.assertEqual(brief.safe_where(str(FIX / "projects" / "x")), "")
        self.assertIn('none (always use "")', brief.build_prompt(TUE, ctx_for(TUE)))

    def test_clean_handoff_fills_and_fixes(self):
        self.assertEqual(brief.clean_handoff(None),
                         {"runner": "agent", "model": "default", "where": "", "reach": "draft", "prompt": ""})
        r = brief.clean_handoff({"runner": "rocket", "model": "GPT 5!", "where": "/tmp", "reach": "yolo",
                                 "prompt": "  Draft the\nreply. "})
        self.assertEqual(r, {"runner": "agent", "model": "default", "where": "", "reach": "draft",
                             "prompt": "Draft the reply."})
        self.assertEqual(brief.clean_handoff({"runner": "codex", "model": "gpt-5-codex"})["model"], "gpt-5-codex")
        self.assertEqual(brief.clean_handoff({"model": "x" * 41})["model"], "default")

    def test_school_context_carries_class_workdirs(self):
        wd = brief.school_context(TUE).get("workdirs", {})
        self.assertEqual(wd, {"CS-1300": str(FIX / "work" / "cs-1300")})
        for code, path in wd.items():
            self.assertEqual(brief.safe_where(path), path, code)

    def test_page_is_unchanged_by_handoff_and_old_briefs_render(self):
        acts = [{"title": "Finish homework 2", "why": "Due Thursday.", "when": "2-4 PM", "horizon": "today",
                 "kind": "school", "source": "school folder", "url": ""}]
        with_h = [dict(a, handoff={"runner": "claude", "model": "default", "where": str(FIX / "work"), "reach": "draft",
                                   "prompt": "Start homework 2."}) for a in acts]
        old = brief.render_html(base_brief(next_actions=acts), ctx_for(TUE), TUE)
        new = brief.render_html(base_brief(next_actions=with_h), ctx_for(TUE), TUE)
        self.assertEqual(old, new)
        self.assertIn("Finish homework 2", old)
        self.assertNotIn("Start homework 2", new)


class ReadOnlyRun(Case):
    """the model run is read-only, refuses api billing, and code never trusts the extra tools blindly."""

    def test_write_tools_never_allowed(self):
        tools = brief.read_tools()
        self.assertFalse(set(tools) & set(brief.WRITE_TOOLS))
        for t in ("Bash", "Write", "Edit", "mcp__claude_ai_Gmail__send_message", "mcp__todoist__todoist_task_close"):
            self.assertIn(t, brief.WRITE_TOOLS)
        self.assertIn("mcp__todoist__todoist_task_get", tools)

    def test_extra_read_tools_are_filtered(self):
        self.env(DAYBOOK_EXTRA_READ_TOOLS="mcp__mail__mail_search, mcp__mail__mail_thread, mcp__mail__mail_send, "
                                          "mcp__mail__draft_reply, Bash, mcp__mail, mcp__mail__*, "
                                          "mcp__claude_ai_Gmail__send_message, mcp__claude_ai_Notion__notion-search")
        # mail_thread reads too, but its name does not say so; the check goes by the name
        self.assertEqual(brief.extra_read_tools(), ["mcp__mail__mail_search"])

    def fake_claude(self, api_source):
        tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, tmp)
        f = Path(tmp) / "claude"
        init = {"type": "system", "subtype": "init", "apiKeySource": api_source, "model": "test", "mcp_servers": []}
        result = {"type": "result", "is_error": False, "structured_output": {"headline": "h"}, "num_turns": 1}
        f.write_text("#!/bin/sh\ncat >/dev/null\n" + "".join(f"echo '{json.dumps(x)}'\n" for x in (init, result)))
        f.chmod(0o755)
        self.env(DAYBOOK_CLAUDE=f)
        return Path(tmp)

    def test_api_key_billing_is_refused(self):
        day_dir = self.fake_claude("ANTHROPIC_API_KEY") / "day"
        with self.assertRaisesRegex(RuntimeError, "refusing"):
            brief.run_claude(day_dir.parent, "prompt", 1)

    def test_subscription_run_returns_the_brief(self):
        d = self.fake_claude("none")
        got, servers = brief.run_claude(d, "prompt", 1)
        self.assertEqual(got, {"headline": "h"})
        self.env(DAYBOOK_REQUIRE_SUBSCRIPTION="1")
        self.fake_claude("ANTHROPIC_API_KEY")
        with self.assertRaises(RuntimeError):
            brief.run_claude(d, "prompt", 2)
        self.env(DAYBOOK_REQUIRE_SUBSCRIPTION="0")
        self.assertEqual(brief.run_claude(d, "prompt", 3)[0], {"headline": "h"})

    def test_billing_keys_never_reach_the_child(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, tmp)
        f = tmp / "claude"
        init = {"type": "system", "subtype": "init", "apiKeySource": "none", "mcp_servers": []}
        f.write_text("#!/bin/sh\ncat >/dev/null\nenv > \"$(dirname \"$0\")/env.txt\"\n"
                     f"echo '{json.dumps(init)}'\n")
        f.chmod(0o755)
        self.env(DAYBOOK_CLAUDE=f, ANTHROPIC_API_KEY="sk-test-not-real")
        with self.assertRaises(RuntimeError):
            brief.run_claude(tmp, "prompt", 1)  # no result line: no brief
        self.assertNotIn("ANTHROPIC_API_KEY", (tmp / "env.txt").read_text())


class PrivateBits(Case):
    def test_reports_drop_private_links_and_ids(self):
        self.assertNotIn("A42B8453", scrub_private("id A42B8453-DA12-4D4D-BCF0-864AC43C9E92"))
        self.assertEqual(scrub_dashes("a \u2e3a b \u2e3b c"), "a, b, c")


if __name__ == "__main__":
    unittest.main()
