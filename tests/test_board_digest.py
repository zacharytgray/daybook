import os
import re

from helpers import DAY, FAKE_RC, Env

from daybook.board import digest


def modules():
    today = {"date": "2026-03-03", "stale": False, "shape": "A steady day", "booked": "1h", "open": "8h",
             "events": [{"title": "Advisor check-in", "start": "11:00", "start_label": "11 AM", "all_day": False}],
             "focus": {"title": "Draft the methods section \u2014 the hard part", "when": "8-11 AM"},
             "items": [{"title": "Pay the $40 parking ticket", "when": "see https://example.com/pay"}],
             "hidden": [{"title": "Call the bike shop back", "mark": {"state": "done"}},
                        {"title": "Renew the library card", "mark": {"state": "snoozed"}}]}
    agent = {"running": [{"task": "Sam asks: fix it, see " + FAKE_RC},
                         {"task": "Recover the successor to hd-paper-three-models-2, then go on"}],
             "waiting": [{"task": "Plan the dashboard 3f2b9a1c-1111-2222-3333-444455556666"}],
             "finished": [{"task": "Tidy nothing", "ended": "2026-03-03T08:00:00-07:00"},
                          {"task": "Yesterday's thing", "ended": "2026-03-02T08:00:00-07:00"}]}
    return {"today": today, "agent": agent}


class DigestTest(Env):
    def test_plain_text(self):
        t = digest.render(modules(), DAY)
        self.assertNotRegex(t, r"https?://")
        self.assertNotIn("\u2014", t)
        self.assertNotIn("$40", t)
        self.assertNotRegex(t, r"[0-9a-f]{8}-[0-9a-f]{4}-")
        self.assertNotIn("session_", t)
        self.assertIn("Focus: Draft the methods section", t)
        self.assertIn("- Call the bike shop back: done", t)
        self.assertIn("- Renew the library card: snoozed till tomorrow", t)
        self.assertIn("Next: Advisor check-in at 11 AM.", t)
        self.assertIn("finished today: Tidy nothing", t)
        self.assertIn("## Wren", t)
        self.assertIn("- waiting on you: Plan the dashboard", t)
        self.assertIn("## Marked on the board", t)
        self.assertNotIn("Yesterday's thing", t)
        self.assertNotRegex(t, r"\bhd-")
        self.assertIn("Recover the successor to a session, then go on", t)

    def test_prefix_follows_setting(self):
        os.environ["DAYBOOK_SESSION_PREFIX"] = "job-"
        m = modules()
        m["agent"]["running"] = [{"task": "pick up job-old-thing again"}]
        self.assertIn("pick up a session again", digest.render(m, DAY))

    def test_unavailable_today(self):
        t = digest.render({"today": {"error": "unavailable: x"}, "agent": {"error": "unavailable: y"}}, DAY)
        self.assertIn("not available", t)

    def test_write_only_on_change(self):
        data = self.tmp / "data"
        data.mkdir()
        self.assertTrue(digest.write(data, modules(), DAY))
        self.assertFalse(digest.write(data, modules(), DAY.replace(minute=30)))
        m = modules()
        m["today"]["items"] = []
        self.assertTrue(digest.write(data, m, DAY))
        self.assertTrue(re.search(r"Written by Daybook at", (data / "today.md").read_text()))
