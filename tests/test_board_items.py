import datetime as dt
import os

from helpers import DAY, FIX, Env

from daybook.board import items as I
from daybook.board.store import Store
from daybook.common import item_id


class ItemsTest(Env):
    def build(self, marks=(), t=DAY):
        brief, ctx = I.load_brief(I.brief_dir(t))
        return I.build(brief, ctx, list(marks), t)

    def by_title(self, rows):
        return {r["title"]: r for r in rows}

    def test_dedupe_and_order(self):
        shown, hidden = self.build()
        titles = [r["title"] for r in shown]
        self.assertEqual(titles.count("Draft the methods section"), 1)
        self.assertEqual(shown[0]["origin"], "focus")
        self.assertEqual(len({r["id"] for r in shown}), len(shown))
        self.assertEqual(hidden, [])

    def test_todoist_mirror_and_covered_school_items_drop(self):
        t = self.by_title(self.build()[0])
        self.assertNotIn("BIO-2100 lab report 4", t)  # todoist mirror of a school file
        self.assertNotIn("BIO-2100 Lab report 4", t)  # already a next action
        self.assertIn("Renew the library card", t)
        self.assertEqual(t["Renew the library card"]["ref"], "T2")
        self.assertIn("BIO-2100 Quiz 5", t)
        self.assertIn("BIO-2100 Old reading response", t)  # overdue stays
        self.assertNotIn("BIO-2100 Project proposal", t)  # past the week

    def test_no_grading_items(self):
        for r in self.build()[0]:
            self.assertNotIn("grading", r["title"].lower())

    def test_school_defaults(self):
        t = self.by_title(self.build()[0])
        d = t["Finish BIO-2100 lab report 4"]["defaults"]
        self.assertEqual((d["runner"], d["model"], d["reach"], d["from"]), ("claude", "opus", "draft", "board"))
        self.assertEqual(d["where"], str((FIX / "workspace" / "bio-2100").resolve()))
        self.assertTrue(t["Finish BIO-2100 lab report 4"]["where_ok"])
        q = t["BIO-2100 Quiz 5"]
        self.assertEqual(q["ref"], "classes/bio-2100/assignments/quiz-5.md")
        self.assertEqual(q["source"], "school")
        self.assertEqual(q["defaults"]["runner"], "claude")
        self.assertEqual(t["BIO-2100 Old reading response"]["ref"], "school BIO-2100")
        # a model the list does not offer falls back to the runner's default
        self.assertEqual(I.suggest({"handoff": {"runner": "codex", "model": "gpt-9"}}, {}, [])["model"], "gpt-5-codex")
        self.assertEqual(I.suggest({"handoff": {"runner": "codex", "model": "default"}}, {}, [])["model"], "gpt-5-codex")

    def test_class_workdir_outside_the_roots_is_not_suggested(self):
        os.environ["DAYBOOK_WORK_ROOTS"] = ""
        d = self.by_title(self.build()[0])["Finish BIO-2100 lab report 4"]["defaults"]
        self.assertEqual(d["where"], "")
        self.assertNotIn("Classes", {c["group"] for c in I.where_choices()})

    def test_pr_and_personal_defaults(self):
        t = self.by_title(self.build()[0])
        pr = t["Review the kite-app layout PR"]["defaults"]
        self.assertEqual((pr["runner"], pr["reach"]), ("claude", "branch"))
        self.assertEqual(pr["where"], str(FIX / "projects" / "kite-app"))
        call = t["Call the bike shop back"]["defaults"]
        self.assertEqual((call["runner"], call["reach"], call["where"]), ("agent", "draft", ""))
        self.assertEqual(t["Draft the methods section"]["defaults"]["runner"], "agent")

    def test_brief_handoff_field_wins(self):
        row = self.by_title(self.build()[0])["Wire board marks into the brief"]
        d = row["defaults"]
        self.assertEqual((d["runner"], d["model"], d["reach"], d["from"]), ("codex", "gpt-5-codex", "branch", "brief"))
        self.assertEqual(d["where"], os.path.expanduser("~/somewhere-else/notes-site"))
        self.assertEqual(d["where_label"], "~/somewhere-else/notes-site")
        self.assertEqual(d["prompt"], "read the plan first")
        self.assertFalse(row["where_ok"])  # outside the roots: the panel says to send it by hand

    def test_marks_filter(self):
        s = Store(self.tmp / "data")
        self.addCleanup(s.close)
        s.set_mark({"title": "Call the bike shop back"}, "done")
        s.set_mark({"title": "Renew the library card"}, "snoozed", until="2026-03-04T05:00:00-07:00")
        s.set_mark({"title": "BIO-2100 Quiz 5"}, "dismissed")
        shown, hidden = self.build(s.marks())
        titles = {r["title"] for r in shown}
        gone = {"Call the bike shop back", "Renew the library card", "BIO-2100 Quiz 5"}
        self.assertFalse(titles & gone)
        self.assertEqual({h["title"] for h in hidden}, gone)
        # the snooze ends the next morning
        shown, _ = self.build(s.marks(), DAY + dt.timedelta(days=1))
        self.assertIn("Renew the library card", {r["title"] for r in shown})
        self.assertNotIn("Call the bike shop back", {r["title"] for r in shown})

    def test_ids_are_title_hashes(self):
        for r in self.build()[0]:
            self.assertEqual(r["id"], item_id(r["title"]))

    def test_allowed_roots(self):
        pr = FIX / "projects"
        self.assertTrue(I.allowed(str(pr / "kite-app")))
        self.assertTrue(I.allowed(str(FIX / "workspace" / "bio-2100" / "anything")))
        self.assertFalse(I.allowed("/etc"))
        self.assertFalse(I.allowed(str(pr / ".." / "school")))
        self.assertFalse(I.allowed("kite-app"))
        self.assertFalse(I.allowed(str(pr) + "-evil"))
        link = self.tmp / "escape"
        os.symlink("/etc", link)
        self.assertFalse(I.allowed(str(link)))

    def test_no_roots_means_nothing_is_allowed(self):
        os.environ["DAYBOOK_PROJECTS"] = ""
        os.environ["DAYBOOK_WORK_ROOTS"] = ""
        self.assertEqual(I.allowed_roots(), [])
        self.assertFalse(I.allowed(str(FIX / "projects" / "kite-app")))
        self.assertEqual(I.where_choices(), [])

    def test_where_choices(self):
        ch = I.where_choices()
        self.assertEqual([c["group"] for c in ch], ["Projects", "Projects", "Work roots", "Classes"])
        self.assertEqual(ch[-1]["label"], "Cell Biology")
        for c in ch:
            self.assertTrue(I.allowed(c["path"]), c)

    def test_school_off(self):
        os.environ["DAYBOOK_SCHOOL"] = ""
        self.assertEqual(I.classes(), {})
        self.assertEqual(I.assignment_ref({}, "BIO-2100", "Quiz 5"), "")

    def test_class_codes(self):
        self.assertEqual(I.class_of("Finish bio 2100 notes"), "BIO-2100")
        self.assertEqual(I.class_of("HIST-2210 essay"), "HIST-2210")
        self.assertEqual(I.class_of("Call the shop"), "")


class WindowTest(Env):
    def test_parser_forms(self):
        cases = {
            "1-2 PM, between lab and the seminar": ("13:00", "14:00"),
            "3:15-3:45 PM, right after lab": ("15:15", "15:45"),
            "8-11 AM, before office hours": ("08:00", "11:00"),
            "3:45-5 PM today, after lab. It has no due date": ("15:45", "17:00"),
            "11 AM-1 PM": ("11:00", "13:00"),
            "11-1 PM": ("11:00", "13:00"),
            "12-1 PM": ("12:00", "13:00"),
            "after 7 PM": ("19:00", "21:00"),
            "Tonight, after 7 PM": ("19:00", "21:00"),
        }
        for text, (a, b) in cases.items():
            self.assertEqual(I.window_of(text), {"start": a, "end": b}, text)
        self.assertEqual(I.window_of("after 7 PM", end="22:00"), {"start": "19:00", "end": "22:00"})
        self.assertEqual(I.window_of("after 10 PM"), {"start": "22:00", "end": "23:59"})

    def test_parser_refuses_other_days_and_loose_words(self):
        for text in ("Fri Mar 6 or Saturday", "due Thu Mar 5, 8:45 PM", "due Thu, 1-2 PM", "Fri Mar 6, 2-4 PM",
                     "tomorrow, 1-2 PM", "Noon", "This week", "", None, "13-14 PM", "steps H1-H8a plus the SSD check",
                     "Both close Sun Mar 8 at 11:59 PM", "Read it first. 1-2 PM"):
            self.assertIsNone(I.window_of(text), text)

    def test_only_todays_items_and_why_fallback(self):
        self.assertEqual(I.window({"horizon": "today", "when": "", "why": "3:45-5 PM today, after lab."}),
                         {"start": "15:45", "end": "17:00"})
        self.assertIsNone(I.window({"horizon": "this_week", "when": "1-2 PM"}))
        self.assertIsNone(I.window({"horizon": "today", "origin": "school", "when": "1-2 PM"}))
        self.assertEqual(I.window({"horizon": "today", "when": "1-2 PM", "why": "3-4 PM"})["start"], "13:00")
