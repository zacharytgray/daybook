"""the brief's settings: safe defaults, everything off until set, and names, place and zone flowing through."""
import datetime as dt
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from brief_helpers import FIX, ROOT, TUE, Case, base_brief, brief, ctx_for, ev
from daybook import config

DEMO = ROOT / "demo"
DEMO_DAY = dt.date(2026, 4, 14)


class Defaults(Case):
    def setUp(self):
        super().setUp()
        # nothing set at all: only the defaults in config.py
        for k in [k for k in os.environ if k.startswith("DAYBOOK_") and k != "DAYBOOK_ENV_FILE"]:
            del os.environ[k]

    def test_serves_on_localhost_by_default(self):
        self.assertEqual(config.setting("DAYBOOK_HOST"), "127.0.0.1")
        srv = brief.make_server(port=0)
        self.addCleanup(srv.server_close)
        self.assertEqual(srv.server_address[0], "127.0.0.1")
        self.assertEqual(brief.web_base(), "http://127.0.0.1:8735")

    def test_every_adapter_is_off(self):
        now = config.now()
        self.assertTrue(brief.school_context(TUE)["off"])
        self.assertEqual(brief.weather_context(TUE)["status"], "off")
        self.assertEqual(brief.news_candidates(now)["status"], "off")
        self.assertEqual(brief.mail_context()["status"], "off")
        self.assertEqual(brief.session_reports(now), [])
        self.assertEqual(brief.git_activity(now), [])
        self.assertEqual(brief.where_roots(), [])
        self.assertTrue(config.flag("DAYBOOK_REQUIRE_SUBSCRIPTION"))

    def test_gather_marks_off_sources_and_never_calls_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.env(DAYBOOK_DATA=tmp)
            ctx = brief.gather(TUE, Path(tmp) / "day")
        self.assertEqual(set(ctx["off"]), {"school", "reports", "git", "prs", "news", "weather", "mail"})
        self.assertIsNone(ctx["prs"])
        rows = {n: (s, t) for n, s, t, _ in brief.source_rows(base_brief(), ctx)}
        for name in ("School folder", "GitHub", "Session reports", "Git activity", "News feeds", "Second mailbox"):
            self.assertEqual(rows[name][0], "off", name)
            self.assertTrue(rows[name][1], name)  # a plain note, never empty
        self.assertNotIn("unavailable", [s for s, _ in rows.values()])

    def test_page_without_place_edition_or_school(self):
        ctx = ctx_for(TUE)
        ctx["school"] = dict(ctx["school"], off=True)
        ctx["off"] = ["school", "prs"]
        html = brief.render_html(base_brief(), ctx, TUE)
        self.assertNotIn("No. ", html)
        self.assertIn("<figcaption>Plate, autumn.", html)
        self.assertNotIn('id="school"', html)
        self.assertNotIn('id="prs"', html)
        self.assertIn(brief.DEFAULT_COLOPHON, html)
        self.assertIn("<title>Morning Brief, Tuesday October 6</title>", html)
        alm = re.search(r'<p class="almanac">(.*?)</p>', html).group(1)
        self.assertIn("Sunrise 6:30 AM", alm)  # no location: the fixed sky
        self.assertEqual(alm.count("<span>"), 5)  # date, weather, sunrise, sunset, moon: no place

    def test_utc_when_the_zone_is_bad(self):
        self.env(DAYBOOK_TZ="Not/AZone")
        self.assertEqual(str(config.tz()), "UTC")


class Overrides(Case):
    def test_names_place_zone_and_ids_reach_the_prompt(self):
        self.env(DAYBOOK_USER_NAME="Robin", DAYBOOK_AGENT_NAME="Wren", DAYBOOK_TZ="Europe/Lisbon",
                 DAYBOOK_LOCATION="Harbor Town", DAYBOOK_CALENDAR_ID="team@example.com",
                 DAYBOOK_TODOIST_PROJECT="12345")
        p = brief.build_prompt(TUE, ctx_for(TUE))
        self.assertIn("Write Robin's morning brief for Tuesday, October 6, 2026 (2026-10-06, Europe/Lisbon)", p)
        self.assertIn("handing the action to Wren", p)
        self.assertIn("Location: Harbor Town", p)
        self.assertIn('calendarId "team@example.com"', p)
        self.assertIn("tasks from the project with id 12345 only", p)
        self.assertIn("The reader is Robin.", p)  # no about.md: a plain default
        self.assertIn(json.dumps([str(FIX / "projects"), str(FIX / "work")], separators=(",", ":")), p)
        self.assertNotIn("{{", p)
        self.env(DAYBOOK_TODOIST_PROJECT="")
        self.assertIn("tasks from the Inbox project only", brief.build_prompt(TUE, ctx_for(TUE)))

    def test_about_file_is_used_when_present(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        shutil.copy(ROOT / "prompt" / "brief.md", tmp / "brief.md")
        (tmp / "about.md").write_text("<!-- a note -->\nRobin studies tides.\n")
        old = brief.PROMPT
        brief.PROMPT = tmp
        self.addCleanup(setattr, brief, "PROMPT", old)
        p = brief.build_prompt(TUE, ctx_for(TUE))
        self.assertIn("Robin studies tides.", p)
        self.assertNotIn("a note", p)

    def test_masthead_place_title_edition_and_colophon(self):
        self.env(DAYBOOK_LOCATION="Harbor Town", DAYBOOK_BRIEF_TITLE="Daily Sheet",
                 DAYBOOK_FIRST_EDITION="2026-10-01", DAYBOOK_COLOPHON="Printed at home.")
        html = brief.render_html(base_brief(), ctx_for(TUE), TUE)
        self.assertIn('<span class="brand">Daily Sheet</span><span class=no>No. 6</span>', html)
        self.assertIn("<span>Harbor Town</span>", html)
        self.assertIn("<figcaption>Plate 6, autumn.", html)
        self.assertIn("Printed at home.", html)
        self.assertIn("<title>Daily Sheet, Tuesday October 6</title>", html)
        # a date before the first edition gets no number
        self.assertNotIn("No. ", brief.render_html(base_brief(), ctx_for(TUE), dt.date(2026, 9, 30)))

    def test_zone_changes_the_due_times(self):
        self.env(DAYBOOK_TZ="Asia/Tokyo")
        ctx = brief.school_context(TUE)
        self.assertTrue(all(i["sort"].endswith("+09:00") for i in ctx["due_soon"]))
        self.assertEqual(brief.parse_due("2026-10-07")[0].tzinfo, config.tz())

    def test_frozen_clock(self):
        self.env(DAYBOOK_NOW="2026-04-14T10:20:00", DAYBOOK_TZ="America/Denver")
        self.assertEqual(brief.today(), DEMO_DAY)
        self.assertEqual(config.now().utcoffset(), dt.timedelta(hours=-6))


class Demo(Case):
    """the shipped demo renders with no network, no model and no chrome."""

    def test_demo_brief_renders_offline(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        shutil.copytree(DEMO / "briefs", tmp / "briefs")
        for k in [k for k in os.environ if k.startswith("DAYBOOK_")]:
            del os.environ[k]
        os.environ["DAYBOOK_ENV_FILE"] = str(DEMO / "demo.env")
        config.load_env()
        self.env(DAYBOOK_BRIEFS=tmp / "briefs", DAYBOOK_DATA=tmp / "data", DAYBOOK_CHROME="/nonexistent/chrome",
                 DAYBOOK_BRIEF_WEB="http://127.0.0.1:9")
        self.assertEqual(brief.main(["render", "--date", "2026-04-14"]), 0)
        d = tmp / "briefs" / "2026-04-14"
        html = (d / "brief.html").read_text()
        self.assertIn("No. 100", html)
        self.assertIn("<span>Lakeside</span>", html)
        self.assertIn('data-tz="America/Denver"', html)
        self.assertIn('data-now="2026-04-14T10:20-06:00"', html)
        self.assertIn("Every name, event and message here is invented.", html)
        self.assertNotIn("\u2014", html)
        meta = json.loads((d / "meta.json").read_text())
        self.assertEqual(meta["source_gaps"], [])
        self.assertTrue((d / "puzzles.json").exists())

    def test_demo_inputs_are_clean(self):
        b = json.loads((DEMO / "briefs" / "2026-04-14" / "brief.json").read_text())
        ctx = json.loads((DEMO / "briefs" / "2026-04-14" / "context.json").read_text())
        self.assertEqual(len(b["next_actions"]), 5)
        for a in b["next_actions"]:
            self.assertEqual(a["handoff"], brief.clean_handoff(a["handoff"]))
            self.assertEqual(set(a), {"title", "why", "when", "horizon", "kind", "source", "url", "handoff"})
        text = json.dumps(b) + json.dumps(ctx)
        self.assertNotIn("\u2014", text)
        self.assertNotIn("/Users/", text)
        for u in re.findall(r'https?://[^"\s]+', text):
            self.assertTrue(u.startswith("https://example.com/"), u)
        events = brief.merge_day(b["events"], ctx["school"]["class_meetings"])
        self.assertEqual(len(brief.conflicts(events)), 1)


if __name__ == "__main__":
    unittest.main()
