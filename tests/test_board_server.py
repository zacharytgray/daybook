import datetime as dt
import http.server
import json
import os
import re
import subprocess
import threading
import urllib.error
import urllib.request

from helpers import DAY, FAKE_RC, SECRETS, Env

NOW = DAY + dt.timedelta(hours=2)

from daybook.board import agent as A
from daybook.board import server as S


class ServerBase(Env):
    def setUp(self):
        super().setUp()
        # the board's clock stands at 11 AM on the fixture day, two hours after the sessions below started
        os.environ["DAYBOOK_NOW"] = NOW.isoformat()
        self.session("hd-run", DAY.timestamp(), task="Sam asks to wire the marks")
        self.session("hd-old", DAY.timestamp() - 3600, ended=True, ended_at=DAY.timestamp() - 60)
        self.app = S.App(self.tmp / "data")
        self.app.refresh()
        self.srv = S.make_server(self.app, "127.0.0.1", 0, quiet=True)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.app.stop.set()
        self.srv.shutdown()
        self.srv.server_close()
        self.app.store.close()
        super().tearDown()

    def call(self, path, body=None, headers=None, method=None):
        data = json.dumps(body).encode() if isinstance(body, dict) else body
        h = {"Content-Type": "application/json", "X-Daybook-Token": self.app.token}
        h.update(headers or {})
        req = urllib.request.Request(self.base + path, data=data, method=method or ("POST" if data is not None else "GET"),
                                     headers={k: v for k, v in h.items() if v is not None})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, dict(e.headers), e.read()

    def state(self):
        return json.loads(self.call("/api/state")[2])

    def mark(self, **kw):
        b = {"title": "Call the bike shop back", "state": "done"}
        b.update(kw)
        return self.call("/api/marks", b)

    def ask(self, **kw):
        b = {"title": "Wire the marks", "runner": "claude", "model": "opus", "where": "", "reach": "branch"}
        b.update(kw)
        return self.call("/api/requests", b)


class ServerTest(ServerBase):
    def test_page_carries_token_names_and_strict_headers(self):
        code, h, body = self.call("/")
        page = body.decode()
        self.assertEqual(code, 200)
        self.assertIn(f'name="daybook-token" content="{self.app.token}"', page)
        self.assertIn('src="/modules/today.js"', page)
        self.assertIn('src="/modules/agent.js"', page)
        self.assertIn("<title>Daybook</title>", page)
        self.assertIn('id="tab-name-agent">Wren</span>', page)
        self.assertNotRegex(page, r"<script>(?!</script>)")  # no inline script
        csp = h["Content-Security-Policy"]
        for part in ("default-src 'self'", "connect-src 'self'", "script-src 'self'", "frame-ancestors 'none'"):
            self.assertIn(part, csp)
        self.assertNotIn("unsafe-inline", csp)
        self.assertEqual(h["X-Content-Type-Options"], "nosniff")
        self.assertEqual(h["Referrer-Policy"], "no-referrer")
        self.assertNotIn("Access-Control-Allow-Origin", h)

    def test_names_are_escaped_in_the_page(self):
        os.environ["DAYBOOK_TITLE"] = "<b>x</b>"
        os.environ["DAYBOOK_AGENT_NAME"] = "<i>"
        page = self.call("/")[2].decode()
        self.assertIn("<title>&lt;b&gt;x&lt;/b&gt;</title>", page)
        self.assertNotIn("<i>", page)

    def test_tokens_differ_per_start(self):
        other = S.App(self.tmp / "data2")
        self.assertNotEqual(self.app.token, other.token)
        other.store.close()

    def test_write_guards(self):
        self.assertEqual(self.mark()[0], 200)
        self.assertEqual(self.call("/api/marks", {"title": "x", "state": "done"}, {"X-Daybook-Token": None})[0], 403)
        self.assertEqual(self.call("/api/marks", {"title": "x", "state": "done"}, {"X-Daybook-Token": "nope"})[0], 403)
        self.assertEqual(self.call("/api/marks", {"title": "x", "state": "done"}, {"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.call("/api/marks", {"title": "x", "state": "done"},
                                   {"Origin": "http://evil.example"})[0], 403)
        host = self.base.split("//")[1]
        self.assertEqual(self.call("/api/marks", {"title": "x", "state": "done"}, {"Origin": f"http://{host}"})[0], 200)
        self.assertEqual(self.call("/api/marks", b"x" * (S.BODY_MAX + 1))[0], 413)
        self.assertEqual(self.call("/api/marks", {"title": "x", "state": "burnt"})[0], 400)
        self.assertEqual(self.call("/api/marks", {"title": "x", "state": "done", "item_id": "000000000000"})[0], 400)

    def test_dns_rebinding_host_refused(self):
        self.assertEqual(self.call("/api/state", headers={"Host": "evil.example.com"})[0], 421)
        for ok in ("192.0.2.10:8740", "127.0.0.1", "[::1]:8740", "localhost:8740", "desk:8740"):
            self.assertTrue(S.host_ok(ok), ok)
        # a dotted name only when listed
        for name in ("desk.example-tailnet.ts.net", "board.example.net", ""):
            self.assertFalse(S.host_ok(name), name)
        os.environ["DAYBOOK_ALLOWED_HOSTS"] = ".ts.net, board.example.net"
        self.assertTrue(S.host_ok("desk.example-tailnet.ts.net:8740"))
        self.assertTrue(S.host_ok("board.example.net"))
        self.assertFalse(S.host_ok("evil-board.example.net"))
        self.assertFalse(S.host_ok("ts.net.evil.example"))

    def test_state_since(self):
        full = self.state()
        self.assertEqual(set(full["modules"]), {"today", "agent", "fleet"})
        seq = full["seq"]
        self.assertEqual(json.loads(self.call(f"/api/state?since={seq}")[2])["modules"], {})
        self.mark()
        d = json.loads(self.call(f"/api/state?since={seq}")[2])
        self.assertGreater(d["seq"], seq)
        self.assertEqual(set(d["modules"]), {"today"})
        self.assertEqual(d["marks"][0]["state"], "done")
        today = d["modules"]["today"]
        self.assertNotIn("Call the bike shop back", [i["title"] for i in today["items"]])
        self.assertEqual(today["done_count"], 1)
        self.assertEqual(self.mark(state="open")[0], 200)
        today = self.state()["modules"]["today"]
        self.assertIn("Call the bike shop back", [i["title"] for i in today["items"]])

    def test_state_config_block(self):
        c = self.state()["config"]
        self.assertEqual(c, {"title": "Daybook", "user": "Sam", "agent": "Wren", "tz": "America/Denver", "location": "",
                             "now": "2026-03-03T11:00:00-07:00", "brief_web": "http://127.0.0.1:9", "prefix": "hd-",
                             "transport": "copy", "actions": {"dispatch": False}})
        os.environ["DAYBOOK_LOCATION"] = "Lakeside"
        os.environ["DAYBOOK_DISPATCH_CMD"] = "/bin/false"
        os.environ["DAYBOOK_NOW"] = ""
        c = self.state()["config"]
        self.assertEqual((c["location"], c["now"], c["actions"]), ("Lakeside", "", {"dispatch": True}))

    def test_today_windows_sun_and_session_titles(self):
        d = self.state()
        today = d["modules"]["today"]
        self.assertFalse(today["stale"])
        self.assertEqual(today["sun"], {"rise": "06:32", "set": "17:53"})
        self.assertEqual(today["brief_url"], "http://127.0.0.1:9/2026-03-03/")
        self.assertEqual(today["focus"]["window"], {"start": "08:00", "end": "11:00"})
        rows = {i["title"]: i for i in today["items"]}
        self.assertIsNone(rows["Call the bike shop back"]["window"])  # "Noon" is not a range
        self.assertIsNone(rows["Wire board marks into the brief"]["window"])  # this week
        self.assertEqual(d["layout"][0], {"name": "today", "title": "Today", "room": "today"})
        self.assertEqual(d["layout"][1], {"name": "agent", "title": "Wren", "room": "agent"})
        self.assertEqual(d["modules"]["agent"]["running"][0]["title"], "Run")
        self.assertEqual(d["modules"]["agent"]["running"][0]["task"], "Sam asks to wire the marks")
        # the school meeting merged in with its neutral source label
        self.assertIn("school", {e["source"] for e in today["events"]})

    def test_stale_brief_has_no_windows(self):
        from daybook.board.modules import today as M
        stale = M.collect({"store": self.app.store, "now": DAY + dt.timedelta(days=1)})
        self.assertTrue(stale["stale"])
        self.assertIsNone(stale["focus"]["window"])

    def test_snooze_defaults_to_tomorrow(self):
        self.mark(state="snoozed")
        m = self.state()["marks"][0]
        self.assertEqual(m["until"], "2026-03-04T05:00:00-07:00")

    def test_no_private_meta_fields_leave(self):
        self.ask()
        self.app.match_requests()
        self.app.refresh()
        raw = self.call("/api/state")[2].decode()
        for s in SECRETS:
            self.assertNotIn(s, raw)
        for k in ("chat_guid", "session_id", "thread_id", "last_prompt_id", "delivered_"):
            self.assertNotIn(f'"{k}', raw)
        self.assertEqual(json.loads(raw)["modules"]["agent"]["running"][0]["url"], FAKE_RC)

    def test_request_copy_when_no_transport(self):
        code, _, b = self.ask(item_id="abc")
        d = json.loads(b)
        self.assertEqual((code, d["ok"], d["status"], d["sms_url"]), (200, True, "copy", ""))
        self.assertTrue(d["text"].startswith("From Daybook, Sam asks: start a Claude Code session"))
        self.assertIn("send it to Wren yourself", d["message"])
        r = self.app.store.request(d["id"])
        self.assertEqual((r["status"], r["via"]), ("copy", "copy"))
        ag = self.state()["modules"]["agent"]
        self.assertEqual(ag["requests"][0]["text"], d["text"])
        self.assertEqual(ag["requests"][0]["sms_url"], "")
        # then you say you sent it, and only then can it match
        self.session("hd-wire", NOW.timestamp() + 5, task="Sam asks to wire the marks into the brief")
        self.app.match_requests()
        self.assertEqual(self.app.store.request(d["id"])["status"], "copy")
        code, _, b = self.call("/api/requests/sent", {"id": d["id"], "sent": True})
        self.assertEqual((code, json.loads(b)["status"]), (200, "sent"))
        self.app.match_requests()
        r = self.app.store.request(d["id"])
        self.assertEqual((r["session_name"], r["status"], r["via"]), ("hd-wire", "started", "copy"))
        self.assertEqual(self.state()["modules"]["agent"]["requests"][0]["text"], "")

    def test_request_prefilled_logged_and_matched(self):
        os.environ["DAYBOOK_AGENT_SMS"] = "agent@example.com"
        code, _, b = self.ask(item_id="abc")
        d = json.loads(b)
        self.assertEqual((code, d["status"]), (200, "prefilled"))
        self.assertTrue(d["sms_url"].startswith("sms:agent@example.com&body="))
        log = (self.tmp / "data" / "requests.log").read_text()
        self.assertNotIn("sms:", log)
        self.assertNotIn("http", log)
        self.session("hd-wire", NOW.timestamp() + 5, task="Sam asks to wire the marks into the brief")
        self.app.match_requests()
        self.assertEqual(self.app.store.request(d["id"])["status"], "prefilled")
        self.assertTrue(self.state()["modules"]["agent"]["requests"][0]["sms_url"].startswith("sms:"))
        code, _, b = self.call("/api/requests/sent", {"id": d["id"], "sent": True})
        self.assertEqual((code, json.loads(b)["status"]), (200, "sent"))
        self.app.match_requests()
        r = self.app.store.request(d["id"])
        self.assertEqual((r["session_name"], r["status"], r["via"]), ("hd-wire", "started", "sms"))
        self.assertEqual(self.call("/api/requests/sent", {"id": d["id"], "sent": False})[0], 409)

    def test_didnt_send(self):
        d = json.loads(self.ask()[2])
        self.assertEqual(json.loads(self.call("/api/requests/sent", {"id": d["id"], "sent": False})[2])["status"], "not_sent")
        self.assertEqual(self.call("/api/requests/sent", {"id": 999, "sent": True})[0], 400)

    def test_hardening(self):
        import http.client
        port = self.srv.server_address[1]

        def raw(method, path, headers, body=b""):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            c.putrequest(method, path)
            for k, v in headers.items():
                c.putheader(k, v)
            c.endheaders(body or None)
            r = c.getresponse()
            out = (r.status, r.read())
            c.close()
            return out
        j = {"Content-Type": "application/json"}
        # a non-ascii token is a plain 403
        self.assertEqual(raw("POST", "/api/marks", dict(j, **{"X-Daybook-Token": "t\u00e9st".encode("utf-8"),
                                                               "Content-Length": "2"}), b"{}")[0], 403)
        tok = {"X-Daybook-Token": self.app.token}
        for bad in ("-5", "abc", "1e3"):
            self.assertEqual(raw("POST", "/api/marks", dict(j, **tok, **{"Content-Length": bad}))[0], 400, bad)
        code, data = raw("HEAD", "/api/events", {})
        self.assertEqual((code, data), (200, b""))

    def test_request_outside_roots(self):
        code, _, b = self.ask(title="Edit hosts", where="/etc", reach="draft")
        d = json.loads(b)
        self.assertEqual((code, d["error"], d["sms_url"]), (400, "outside", ""))
        self.assertEqual(d["message"], "That folder is outside the allowed roots, so a click cannot start it. "
                                       "Send it to Wren yourself.")
        self.assertIn("Where: /etc", d["text"])
        self.assertEqual(self.app.store.requests(), [])
        os.environ["DAYBOOK_AGENT_SMS"] = "agent@example.com"
        self.assertTrue(json.loads(self.ask(where="/etc")[2])["sms_url"].startswith("sms:"))

    def test_webhook_signed_v2(self):
        seen = {}

        class Hook(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                seen["body"] = self.rfile.read(int(self.headers["Content-Length"]))
                seen["ts"] = self.headers["X-Webhook-Timestamp"]
                seen["sig"] = self.headers["X-Webhook-Signature-V2"]
                self.send_response(202)
                self.end_headers()

            def log_message(self, *a):
                pass
        hook = http.server.HTTPServer(("127.0.0.1", 0), Hook)
        threading.Thread(target=hook.handle_request, daemon=True).start()
        os.environ["DAYBOOK_WEBHOOK_URL"] = f"http://127.0.0.1:{hook.server_address[1]}/webhooks/daybook"
        os.environ["DAYBOOK_WEBHOOK_SECRET"] = "s3cret"
        try:
            code, _, b = self.ask(title="Call the bike shop back", runner="agent", reach="draft")
        finally:
            hook.server_close()
        d = json.loads(b)
        self.assertEqual((code, d["status"], d["sms_url"]), (200, "sent", ""))
        self.assertEqual(self.app.store.request(d["id"])["via"], "webhook")
        self.assertEqual(seen["sig"], A.sign("s3cret", seen["ts"], seen["body"]))
        payload = json.loads(seen["body"])
        self.assertEqual(payload["request_id"], d["id"])
        self.assertIn("handle this yourself", payload["text"])

    def test_webhook_failure_falls_back(self):
        os.environ["DAYBOOK_WEBHOOK_URL"] = "http://127.0.0.1:9/webhooks/daybook"
        os.environ["DAYBOOK_WEBHOOK_SECRET"] = "s3cret"
        d = json.loads(self.ask(title="Call the bike shop back", runner="agent", reach="draft")[2])
        self.assertEqual(d["status"], "copy")
        self.assertIn("webhook failed", d["error"])
        os.environ["DAYBOOK_AGENT_SMS"] = "agent@example.com"
        self.assertEqual(json.loads(self.ask(runner="agent")[2])["status"], "prefilled")

    def test_module_failure_is_contained(self):
        os.environ["DAYBOOK_BRIEFS"] = str(self.tmp / "nothing")
        f = self.tmp / "broken-services.json"
        f.write_text("{nope")
        os.environ["DAYBOOK_SERVICES_FILE"] = str(f)
        self.app.refresh()
        d = self.state()
        self.assertTrue(d["modules"]["today"]["error"].startswith("unavailable: "))
        self.assertIn("error", d["modules"]["fleet"]["services"])  # services unreadable, devices still listed
        self.assertEqual(d["modules"]["fleet"]["devices"][0]["hostname"], "test-hub")
        self.assertIn("running", d["modules"]["agent"])

    def test_static_and_unknown(self):
        self.assertEqual(self.call("/app.js")[0], 200)
        self.assertEqual(self.call("/modules/today.js")[0], 200)
        self.assertEqual(self.call("/modules/../server.py")[0], 404)
        self.assertEqual(self.call("/data/daybook.db")[0], 404)
        self.assertEqual(self.call("/.env")[0], 404)

    def test_events_stream_starts_with_seq(self):
        req = urllib.request.Request(self.base + "/api/events")
        with urllib.request.urlopen(req, timeout=5) as r:
            self.assertTrue(r.headers["Content-Type"].startswith("text/event-stream"))
            first = r.read1(200).decode()
        self.assertRegex(first, r"event: seq\ndata: \d+")

    def test_digest_written(self):
        self.app.write_digest()
        text = (self.tmp / "data" / "today.md").read_text()
        self.assertIn("Draft the methods section", text)
        self.assertIn("## Wren", text)
        self.assertFalse(re.search(r"https?://|claude\.ai|session_|\u2014", text))


class Done:
    def __init__(self, code, out, err=""):
        self.returncode, self.stdout, self.stderr = code, out, err


class ActionsOffTest(ServerBase):
    """with no dispatch command, archive and revive are refused before anything runs."""

    def test_off_by_default(self):
        calls = []
        self.app.run = lambda *a, **kw: calls.append(a)
        for path, name in (("/api/sessions/archive", "hd-run"), ("/api/sessions/revive", "hd-old")):
            code, _, b = self.call(path, {"name": name})
            self.assertEqual((code, json.loads(b)), (403, {"ok": False, "error": "actions are off"}))
        self.assertEqual(calls, [])


class DispatchBase(ServerBase):
    def setUp(self):
        super().setUp()
        self.cmd = str(self.tmp / "no-dispatch")
        os.environ["DAYBOOK_DISPATCH_CMD"] = self.cmd + " --quiet"


class FeaturesTest(DispatchBase):
    """archive, todoist on marks, and token rotation. no real session or api is touched."""

    def stub(self, code=0, out="stopped hd-run.\n", raise_=None):
        calls = []

        def run(argv, **kw):
            calls.append((argv, kw))
            if raise_:
                raise raise_
            return Done(code, out)
        self.app.run = run
        return calls

    def test_archive_runs_dispatch_stop(self):
        calls = self.stub()
        code, _, b = self.call("/api/sessions/archive", {"name": "hd-run"})
        d = json.loads(b)
        self.assertEqual((code, d["ok"], d["message"]), (200, True, "stopped hd-run."))
        argv, kw = calls[0]
        self.assertEqual(argv, [self.cmd, "--quiet", "stop", "hd-run"])
        self.assertEqual(kw["timeout"], 60)
        self.assertNotIn("shell", kw)
        log = (self.tmp / "data" / "requests.log").read_text()
        self.assertIn('"action": "archive"', log)
        self.assertNotIn("http", log)

    def test_archive_refuses_and_reports(self):
        calls = self.stub()
        for name in ("hd-RUN", "../hd-run", "hd-run; rm", "", None, "x-run"):
            self.assertEqual(self.call("/api/sessions/archive", {"name": name})[0], 400, name)
        self.assertEqual(self.call("/api/sessions/archive", {"name": "hd-old"})[0], 404)  # ended, not current
        self.assertEqual(self.call("/api/sessions/archive", {"name": "hd-run"}, {"X-Daybook-Token": None})[0], 403)
        self.assertEqual(calls, [])
        self.stub(0, "could not stop it: tmux gone\n")
        code, _, b = self.call("/api/sessions/archive", {"name": "hd-run"})
        self.assertEqual((code, json.loads(b)["message"]), (502, "could not stop it: tmux gone"))
        self.stub(2, "a handoff from hd-run is in progress; rerun with --yes.\n")
        self.assertEqual(self.call("/api/sessions/archive", {"name": "hd-run"})[0], 502)
        self.stub(raise_=subprocess.TimeoutExpired("x", 60))
        code, _, b = self.call("/api/sessions/archive", {"name": "hd-run"})
        self.assertEqual(code, 502)
        self.assertIn("did not answer", json.loads(b)["message"])

    def test_todoist_close_and_reopen_on_marks(self):
        from daybook.board import todoist as T
        seen = []
        T_close, T_reopen = T.close, T.reopen
        self.addCleanup(setattr, T, "close", T_close)
        self.addCleanup(setattr, T, "reopen", T_reopen)
        T.close = lambda item: seen.append(("close", item.get("ref"))) or {"ok": True, "id": "T2", "recurring": False,
                                                                            "message": "Closed in Todoist."}
        T.reopen = lambda tid, rec=False: seen.append(("reopen", tid)) or {"ok": True, "id": tid, "recurring": rec,
                                                                           "message": "Reopened in Todoist."}
        d = json.loads(self.mark(title="Renew the library card")[2])
        self.assertEqual(d["todoist"]["message"], "Closed in Todoist.")
        m = self.app.store.mark(d["id"])
        self.assertEqual(m["todoist_id"], "T2")
        self.assertTrue(json.loads(m["todoist_sync"])["ok"])
        marks = json.loads((self.tmp / "data" / "marks.json").read_text())["marks"]
        self.assertEqual(set(marks[0]), {"id", "title", "norm", "source", "ref", "state", "until", "at"})
        d = json.loads(self.mark(title="Renew the library card", state="open")[2])
        self.assertEqual(d["todoist"]["message"], "Reopened in Todoist.")
        self.assertEqual(seen, [("close", "T2"), ("reopen", "T2")])
        # a non-todoist item and a snooze never touch todoist
        self.assertIsNone(json.loads(self.mark(title="Call the bike shop back")[2])["todoist"])
        self.assertIsNone(json.loads(self.mark(title="Renew the library card", state="snoozed")[2])["todoist"])
        self.assertEqual(len(seen), 2)

    def test_todoist_not_connected_never_fails_the_mark(self):
        code, _, b = self.mark(title="Renew the library card")
        d = json.loads(b)
        self.assertEqual(code, 200)
        self.assertIn("Todoist not connected", d["todoist"]["message"])
        self.assertEqual(self.app.store.mark(d["id"])["state"], "done")

    def test_stale_token_and_refresh(self):
        code, _, b = self.call("/api/marks", {"title": "x", "state": "done"}, {"X-Daybook-Token": "from-an-old-start"})
        self.assertEqual((code, json.loads(b)["error"]), (403, "stale token"))
        code, _, b = self.call("/api/token", headers={"Sec-Fetch-Site": "same-origin", "Content-Type": None,
                                                      "X-Daybook-Token": None})
        self.assertEqual((code, json.loads(b)["token"]), (200, self.app.token))
        self.assertEqual(self.call("/api/token", headers={"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.call("/api/token", headers={"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.call("/api/token", headers={"Host": "evil.example.com"})[0], 421)

    def test_state_carries_models(self):
        m = self.state()["models"]
        self.assertEqual(m["claude"]["models"][0]["id"], "opus")
        self.assertIn("gpt-5-mini", [x["id"] for x in m["codex"]["models"]])


class ReviveTest(DispatchBase):
    """revive through a stubbed dispatch command. no real session is revived or stopped."""

    OK = ("resumed: Sam asks to tidy the old thing\nhd-old in notes-site on hub (Claude Code, opus).\n"
          "remote control: " + FAKE_RC + "\nattach: ssh -t hub /usr/local/bin/tmux attach -t hd-old\n")

    def stub(self, code=0, out=OK, raise_=None, revive_meta=True, gate=None):
        calls = []

        def run(argv, **kw):
            calls.append((argv, kw))
            if gate:
                gate.wait(5)
            if raise_:
                raise raise_
            if code == 0 and revive_meta:
                # what dispatch leaves behind: a current record under the same handle, the ended one kept
                self.session("hd-old", DAY.timestamp(), task="Sam asks to tidy the old thing")
            return Done(code, out)
        self.app.run = run
        return calls

    def test_revive_runs_dispatch_revive(self):
        calls = self.stub()
        code, _, b = self.call("/api/sessions/revive", {"name": "hd-old"})
        d = json.loads(b)
        self.assertEqual((code, d["ok"], d["message"]), (200, True, "resumed: Sam asks to tidy the old thing"))
        self.assertEqual(d["url"], FAKE_RC)  # read back from the new record, never built here
        argv, kw = calls[0]
        # no --yes and no --prompt: the dispatch's own permission flow stands, and nothing is replayed
        self.assertEqual(argv, [self.cmd, "--quiet", "revive", "hd-old"])
        self.assertEqual(kw["timeout"], S.REVIVE_SECONDS)
        self.assertNotIn("shell", kw)
        log = (self.tmp / "data" / "requests.log").read_text()
        self.assertIn('"action": "revive"', log)
        self.assertNotIn("http", log)
        self.assertNotIn("attach", log)
        for s in SECRETS:
            self.assertNotIn(s, b.decode() + log)
        ag = self.state()["modules"]["agent"]
        self.assertEqual([s["name"] for s in ag["finished"]], [])
        self.assertIn("hd-old", [s["name"] for s in ag["running"]])
        self.assertEqual(self.call("/api/sessions/revive", {"name": "hd-old"})[0], 409)
        self.assertEqual(len(calls), 1)

    def test_revive_refuses_bad_missing_and_live(self):
        calls = self.stub()
        for name in ("hd-OLD", "../hd-old", "hd-old; rm -rf ~", "hd-old\n", "", None, 7, ["hd-old"], "x-old"):
            self.assertEqual(self.call("/api/sessions/revive", {"name": name})[0], 400, name)
        self.assertEqual(self.call("/api/sessions/revive", {"name": "hd-nowhere"})[0], 404)
        code, _, b = self.call("/api/sessions/revive", {"name": "hd-run"})  # live, not archived
        self.assertEqual((code, json.loads(b)["error"]), (409, "hd-run is running, not archived"))
        (self.dispatch / "ended" / "hd-broken.json").write_text("{not json")
        self.assertEqual(self.call("/api/sessions/revive", {"name": "hd-broken"})[0], 404)
        (self.dispatch / "ended" / "hd-alias.json").write_text(json.dumps({"name": "hd-run", "cwd": "/tmp"}))
        self.assertEqual(self.call("/api/sessions/revive", {"name": "hd-alias"})[0], 404)
        self.assertEqual(calls, [])

    def test_revive_keeps_write_protections(self):
        calls = self.stub()
        body = {"name": "hd-old"}
        self.assertEqual(self.call("/api/sessions/revive", body, {"X-Daybook-Token": None})[0], 403)
        self.assertEqual(self.call("/api/sessions/revive", body, {"X-Daybook-Token": "from-an-old-start"})[0], 403)
        self.assertEqual(self.call("/api/sessions/revive", body, {"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.call("/api/sessions/revive", body, {"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.call("/api/sessions/revive", body, {"Host": "evil.example.com"})[0], 421)
        self.assertEqual(self.call("/api/sessions/revive", None, method="GET")[0], 404)
        self.assertEqual(calls, [])

    def test_revive_failures_are_reported(self):
        sid = "0123abcd-4567-89ab-cdef-0123456789ab"
        cases = [
            (1, f"no transcript for claude session {sid} on hub, so hd-old cannot be resumed.\n", 502),
            (2, "hd-old is still running. send it a message instead.\n", 409),
            (2, "needs Sam's yes first: start outside the roots. ask, then rerun with --yes.\n", 409),
            (1, "needs your yes first: start outside the roots.\n", 409),
            (1, "at the 10-session cap on hub. running: hd-a, hd-b. stop one first.\n", 409),
            (1, "hd-run (Claude Code) is already writing in that tree. Give this one a worktree.\n", 409),
            (2, f"native Codex threads are resumed elsewhere, see {sid}, not by dispatch.\n", 409),
            (0, "could not revive it: tmux gone\n", 502),
        ]
        for code, out, want in cases:
            self.stub(code, out, revive_meta=False)
            status, _, b = self.call("/api/sessions/revive", {"name": "hd-old"})
            d = json.loads(b)
            self.assertEqual((status, d["ok"]), (want, False), out)
            self.assertNotIn(sid, b.decode())
            self.assertEqual(d["url"], "")
        self.assertNotIn(sid, (self.tmp / "data" / "requests.log").read_text())
        self.stub(raise_=subprocess.TimeoutExpired("x", S.REVIVE_SECONDS))
        status, _, b = self.call("/api/sessions/revive", {"name": "hd-old"})
        self.assertEqual(status, 502)
        self.assertIn("did not answer", json.loads(b)["message"])
        self.stub(raise_=FileNotFoundError("no-dispatch"))
        status, _, b = self.call("/api/sessions/revive", {"name": "hd-old"})
        self.assertEqual((status, json.loads(b)["message"]), (502, "could not run the dispatch command: FileNotFoundError"))
        self.assertEqual(self.app.reviving, set())

    def test_repeated_revive_runs_dispatch_once(self):
        gate = threading.Event()
        calls = self.stub(revive_meta=False, gate=gate)
        first = {}
        t = threading.Thread(target=lambda: first.update(r=self.call("/api/sessions/revive", {"name": "hd-old"})))
        t.start()
        for _ in range(200):
            if calls:
                break
            threading.Event().wait(0.01)
        code, _, b = self.call("/api/sessions/revive", {"name": "hd-old"})
        self.assertEqual((code, json.loads(b)["error"]), (409, "hd-old is already being revived"))
        gate.set()
        t.join(5)
        self.assertEqual(first["r"][0], 200)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.app.reviving, set())

    def test_archive_still_works_beside_revive(self):
        calls = self.stub(0, "stopped hd-run.\n", revive_meta=False)
        self.assertEqual(self.call("/api/sessions/archive", {"name": "hd-run"})[0], 200)
        self.assertEqual(calls[0][0][-2:], ["stop", "hd-run"])
        self.assertEqual(self.call("/api/sessions/archive", {"name": "hd-old"})[0], 404)
