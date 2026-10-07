import json
import os
import time

from helpers import FIX, Env

from daybook.board import agent as A
from daybook.board import models as M


def body(**kw):
    b = {"title": "Port the parser", "runner": "codex", "model": "", "where": str(FIX / "projects" / "kite-app"),
         "reach": "draft"}
    b.update(kw)
    return b


class ModelsTest(Env):
    def test_claude_list(self):
        c = M.catalog()["claude"]
        self.assertEqual([m["id"] for m in c["models"]], ["opus", "sonnet", "haiku"])
        self.assertEqual([m["id"] for m in c["models"] if m["default"]], ["opus"])
        self.assertEqual((c["models"][0]["label"], c["models"][0]["provider"]), ("Opus", "Anthropic"))

    def test_bad_rows_are_dropped(self):
        x = M.catalog()["codex"]["models"]
        self.assertEqual([m["id"] for m in x], ["gpt-5-codex", "gpt-5-mini"])
        self.assertEqual(x[0]["label"], "GPT-5 Codex")

    def test_unset_missing_and_broken_say_why(self):
        for value, why in (("", "no models file"), (str(self.tmp / "nowhere.json"), "missing")):
            os.environ["DAYBOOK_MODELS"] = value
            cat = M.catalog()
            for k in ("claude", "codex"):
                self.assertEqual(cat[k]["models"], [])
                self.assertIn(why, cat[k]["error"])
            self.assertEqual(M.pick("claude", "opus"), "")
        f = self.tmp / "broken.json"
        f.write_text("{not json")
        os.environ["DAYBOOK_MODELS"] = str(f)
        self.assertIn("could not read", M.catalog()["claude"]["error"])
        f.write_text("[1, 2]")
        self.assertIn("not a json object", M.catalog()["claude"]["error"])

    def test_reread_on_change_and_first_row_default(self):
        f = self.tmp / "m.json"
        f.write_text(json.dumps({"claude": [{"id": "opus"}]}))
        os.environ["DAYBOOK_MODELS"] = str(f)
        self.assertEqual(M.pick("claude"), "opus")
        self.assertIn("no codex models", M.catalog()["codex"]["error"])
        time.sleep(0.01)
        f.write_text(json.dumps({"claude": [{"id": "sonnet"}, {"id": "haiku", "default": True}]}))
        os.utime(f, ns=(time.time_ns(), time.time_ns() + 10_000_000))
        self.assertEqual(M.pick("claude"), "haiku")

    def test_pick(self):
        self.assertEqual(M.pick("codex", "gpt-5-mini"), "gpt-5-mini")
        self.assertEqual(M.pick("codex", "gpt-9"), "gpt-5-codex")
        self.assertEqual(M.pick("claude"), "opus")
        self.assertEqual(M.pick("agent", "opus"), "")

    def test_requests_refuse_unlisted_models(self):
        self.assertIn("(model gpt-5-mini)", A.request_text(A.check(body(model="gpt-5-mini"))))
        self.assertIn("(model: your pick)", A.request_text(A.check(body(model=""))))
        self.assertIn("(model sonnet)", A.request_text(A.check(body(runner="claude", model="sonnet"))))
        for bad in ("gpt-9", "opus", "Bad Id!"):
            with self.assertRaises(ValueError, msg=bad):
                A.check(body(model=bad))
