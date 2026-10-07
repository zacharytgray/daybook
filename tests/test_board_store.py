import datetime as dt
import hashlib
import json
import os
import re

from helpers import DAY, Env

from daybook.board.store import Store, mark_hides, tomorrow_morning
from daybook.common import item_id, norm


def brief_norm(s):
    # the brief's norm(), copied as the contract
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


class StoreTest(Env):
    def setUp(self):
        super().setUp()
        self.s = Store(self.tmp / "data")
        self.addCleanup(self.s.close)

    def test_every_write_bumps_seq(self):
        a = self.s.seq()
        self.s.set_mark({"title": "Call the bike shop back"}, "done")
        b = self.s.seq()
        rid = self.s.add_request({"runner": "agent", "reach": "draft", "text": "t", "status": "copy", "title": "x"})
        c = self.s.seq()
        self.s.update_request(rid, status="started")
        self.assertTrue(a < b < c < self.s.seq())

    def test_seq_survives_a_restart(self):
        self.s.set_mark({"title": "x"}, "done")
        n = self.s.seq()
        again = Store(self.tmp / "data")
        self.assertEqual(again.seq(), n)
        self.assertTrue((self.tmp / "data" / "daybook.db").is_file())
        again.close()

    def test_marks_json_contract(self):
        self.s.set_mark({"title": "Call the bike shop back!", "source": "voicemail", "ref": "r1"}, "snoozed",
                        until="2026-03-04T05:00:00-07:00", at=DAY)
        d = json.loads((self.tmp / "data" / "marks.json").read_text())
        self.assertEqual(set(d), {"updated", "marks"})
        m = d["marks"][0]
        self.assertEqual(set(m), {"id", "title", "norm", "source", "ref", "state", "until", "at"})
        self.assertEqual(m["norm"], brief_norm("Call the bike shop back!"))
        self.assertEqual(m["id"], hashlib.sha1(brief_norm("Call the bike shop back!").encode()).hexdigest()[:12])
        self.assertEqual((m["state"], m["until"], m["ref"]), ("snoozed", "2026-03-04T05:00:00-07:00", "r1"))

    def test_marks_file_setting_moves_it(self):
        os.environ["DAYBOOK_MARKS"] = str(self.tmp / "elsewhere" / "marks.json")
        s = Store(self.tmp / "data2")
        self.addCleanup(s.close)
        s.set_mark({"title": "x"}, "done")
        self.assertTrue((self.tmp / "elsewhere" / "marks.json").is_file())
        self.assertFalse((self.tmp / "data2" / "marks.json").exists())

    def test_open_removes_the_mark(self):
        self.s.set_mark({"title": "x"}, "done")
        self.s.set_mark({"title": "x"}, "open")
        self.assertEqual(self.s.marks(), [])
        self.assertEqual(json.loads((self.tmp / "data" / "marks.json").read_text())["marks"], [])

    def test_bad_state_rejected(self):
        with self.assertRaises(ValueError):
            self.s.set_mark({"title": "x"}, "finished")
        rid = self.s.add_request({"runner": "agent", "reach": "draft", "text": "t", "status": "copy", "title": "x"})
        with self.assertRaises(ValueError):
            self.s.update_request(rid, status="lost")

    def test_norm_and_id(self):
        for s in ("Fix the BIO-2100 Quiz 5 date mismatch", "  Hello, World!! ", "Studio's D1-D8"):
            self.assertEqual(norm(s), brief_norm(s))
        self.assertEqual(item_id("Call the bike shop back"), item_id("call the bike shop back."))
        self.assertEqual(len(item_id("x")), 12)

    def test_mark_hides(self):
        self.assertTrue(mark_hides({"state": "done"}, DAY))
        self.assertTrue(mark_hides({"state": "dismissed"}, DAY))
        later = tomorrow_morning(DAY)
        self.assertEqual(later.isoformat(), "2026-03-04T05:00:00-07:00")
        self.assertTrue(mark_hides({"state": "snoozed", "until": later.isoformat()}, DAY))
        self.assertFalse(mark_hides({"state": "snoozed", "until": later.isoformat()}, later + dt.timedelta(minutes=1)))
        self.assertFalse(mark_hides(None, DAY))
