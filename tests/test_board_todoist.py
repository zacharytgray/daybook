import io
import json
import os
import urllib.error
import urllib.request

from helpers import Env

from daybook.board import todoist as T


class Fake:
    """stands in for urllib.request.urlopen; answers from a table and records every call."""

    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def __call__(self, req, timeout=None):
        url = req.full_url
        self.calls.append((req.get_method(), url, req.get_header("Authorization"), timeout))
        for (method, part), ans in self.answers.items():
            if req.get_method() == method and part in url:
                if isinstance(ans, Exception):
                    raise ans
                return Resp(ans)
        raise AssertionError(f"unexpected call {req.get_method()} {url}")


class Resp(io.BytesIO):
    def __init__(self, obj):
        super().__init__(b"" if obj is None else json.dumps(obj).encode())

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TodoistTest(Env):
    def setUp(self):
        super().setUp()
        self.real = urllib.request.urlopen
        self.addCleanup(setattr, urllib.request, "urlopen", self.real)
        os.environ["TODOIST_API_TOKEN"] = "tok-test"

    def fake(self, answers):
        f = Fake(answers)
        urllib.request.urlopen = f
        return f

    def test_not_connected_marks_locally(self):
        os.environ["TODOIST_API_TOKEN"] = ""
        f = self.fake({})
        r = T.close({"origin": "todoist", "ref": "T2", "title": "Renew the library card"})
        self.assertFalse(r["ok"])
        self.assertIn("Todoist not connected", r["message"])
        self.assertEqual(f.calls, [])

    def test_close_a_todoist_row(self):
        f = self.fake({("GET", "/tasks/T2"): {"id": "T2", "due": {"is_recurring": False}},
                       ("POST", "/tasks/T2/close"): None})
        r = T.close({"origin": "todoist", "ref": "T2", "title": "Renew the library card"})
        self.assertEqual((r["ok"], r["id"], r["message"]), (True, "T2", "Closed in Todoist."))
        self.assertEqual([c[0] for c in f.calls], ["GET", "POST"])
        self.assertTrue(f.calls[1][1].startswith("https://api.todoist.com/api/v1/tasks/T2/close"))
        self.assertEqual(f.calls[1][2], "Bearer tok-test")
        self.assertEqual(f.calls[1][3], 8)

    def test_recurring_says_so(self):
        self.fake({("GET", "/tasks/T2"): {"id": "T2", "due": {"is_recurring": True}}, ("POST", "/tasks/T2/close"): None})
        r = T.close({"origin": "todoist", "ref": "T2", "title": "Water the plants"})
        self.assertTrue(r["recurring"])
        self.assertIn("repeats", r["message"])
        self.fake({("POST", "/tasks/T2/reopen"): None})
        r = T.reopen("T2", True)
        self.assertTrue(r["ok"])
        self.assertIn("Reopened in Todoist. It repeats", r["message"])

    def test_find_by_title_across_pages(self):
        f = self.fake({("GET", "cursor=c2"): {"results": [{"id": "B9", "content": "Renew the library card!"}], "next_cursor": None},
                       ("GET", "/tasks/filter"): {"results": [{"id": "A1", "content": "Something else"}], "next_cursor": "c2"},
                       ("GET", "/tasks/B9"): {"id": "B9", "due": None}, ("POST", "/tasks/B9/close"): None})
        r = T.close({"title": "Renew the library card", "source": "Todoist"})
        self.assertEqual((r["ok"], r["id"]), (True, "B9"))
        self.assertIn("query=today+%7C+overdue", f.calls[0][1])

    def test_no_single_match_touches_nothing(self):
        for results, why in (([], "no single Todoist task"),
                             ([{"id": "1", "content": "Call the shop"}, {"id": "2", "content": "call the shop"}], "more than one")):
            f = self.fake({("GET", "/tasks/filter"): {"results": results, "next_cursor": None}})
            r = T.close({"title": "Call the Shop", "source": "Todoist"})
            self.assertFalse(r["ok"])
            self.assertIn(why, r["message"])
            self.assertEqual([c[0] for c in f.calls], ["GET"])

    def test_errors_never_raise(self):
        self.fake({("GET", "/tasks/T2"): urllib.error.HTTPError("u", 404, "nf", {}, None)})
        r = T.close({"origin": "todoist", "ref": "T2", "title": "x"})
        self.assertIn("the task is gone", r["message"])
        self.fake({("POST", "/reopen"): TimeoutError()})
        self.assertIn("did not answer", T.reopen("T2")["message"])

    def test_which_items_are_todoist(self):
        self.assertTrue(T.is_todoist({"origin": "todoist"}))
        self.assertTrue(T.is_todoist({"source": "Todoist, mail"}))
        self.assertTrue(T.is_todoist({"url": "https://todoist.com/app/task/renew-card-6XGgmFVcrG5RRjVr"}))
        self.assertFalse(T.is_todoist({"source": "school"}))
        self.assertEqual(T.task_id({"url": "https://todoist.com/app/task/renew-card-6XGgmFVcrG5RRjVr"}), "6XGgmFVcrG5RRjVr")
        self.assertEqual(T.task_id({"url": "https://todoist.com/showTask?id=8812345678"}), "8812345678")

    def test_off_by_default(self):
        os.environ.pop("TODOIST_API_TOKEN", None)
        self.assertFalse(T.connected())
