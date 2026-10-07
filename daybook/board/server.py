# the server: one json api, a page that is only a client of it, server-sent events for sync
import datetime as dt
import hmac
import html
import ipaddress
import json
import re
import secrets
import shlex
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .. import config
from ..common import item_id, one_line, plain
from . import agent as A
from . import digest, iso
from . import models as M
from . import todoist as T
from .modules import MODULES, layout
from .store import Store, tomorrow_morning

WEB = config.ROOT / "web"
BODY_MAX = 16 * 1024
TICK_SECONDS = 15
DIGEST_SECONDS = 300
HEARTBEAT = 25
STOP_SECONDS = 60
# a dispatch can wait a while for a remote link on a start, plus its own ssh checks
REVIVE_SECONDS = 150
UUID = re.compile(r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
# dispatch refusals that are about the machine's state, not a broken revive
CONFLICT = re.compile(r"(?i)session cap|launch cap|already writing|still running|needs [\w' ]{0,30}\byes\b|halted")
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
       "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; object-src 'none'")
STATIC = {"/app.css": ("app.css", "text/css; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/fonts/fraunces.woff2": ("fonts/fraunces-latin-600-normal.woff2", "font/woff2"),
          "/icon.svg": ("icon.svg", "image/svg+xml")}
OFF = (403, {"ok": False, "error": "actions are off"})


def default_host():
    return config.setting("DAYBOOK_HOST")


def default_port():
    try:
        return int(config.setting("DAYBOOK_BOARD_PORT"))
    except ValueError:
        return 8740


def dispatch_argv():
    """the dispatch command as argv, or None when archive and revive are off."""
    cmd = config.setting("DAYBOOK_DISPATCH_CMD").strip()
    try:
        return shlex.split(cmd) or None if cmd else None
    except ValueError:  # unbalanced quotes: treat as off
        return None


def page_config():
    """what the page needs to draw: names, the zone, the frozen clock, which actions exist."""
    return {"title": config.setting("DAYBOOK_TITLE"), "user": config.setting("DAYBOOK_USER_NAME"), "agent": A.agent_name(),
            "tz": config.tz().key, "location": config.setting("DAYBOOK_LOCATION"),
            "now": iso(config.now()) if config.frozen() else "", "brief_web": config.brief_web(),
            "prefix": A.prefix(), "transport": A.transport(), "actions": {"dispatch": bool(dispatch_argv())}}


class App:
    def __init__(self, data_dir=None):
        self.data = Path(data_dir or config.path("DAYBOOK_DATA"))
        self.store = Store(self.data)
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.mods, self.blobs, self.mseq = {}, {}, {}
        self.digest_due, self.last_digest = True, float("-inf")
        self.stop = threading.Event()
        self.reviving = set()
        self.run = subprocess.run  # tests stub this; a real stop ends a real session

    def refresh(self, names=None):
        t = config.now()
        for m in MODULES:
            if names and m["name"] not in names:
                continue
            try:
                data = m["collect"]({"store": self.store, "now": t})
            except Exception as e:
                data = {"error": f"unavailable: {str(e)[:200] or type(e).__name__}"}
            blob = json.dumps(data, sort_keys=True, default=str)
            with self.lock:
                if self.blobs.get(m["name"]) == blob:
                    continue
                self.blobs[m["name"]], self.mods[m["name"]] = blob, data
                self.mseq[m["name"]] = self.store.bump()
                self.digest_due = True

    def state(self, since=None):
        seq = self.store.seq()
        with self.lock:
            mods = {n: d for n, d in self.mods.items() if since is None or self.mseq.get(n, 0) > since}
        marks = [{"id": m["item_id"], "title": m["title"], "state": m["state"], "until": m["until"], "at": m["at"],
                  "by": m["by"]} for m in self.store.marks()]
        reqs = [{k: r[k] for k in ("id", "item_id", "title", "runner", "model", "reach", "status", "session_name", "at",
                                   "error", "via")} for r in self.store.requests()]
        return {"seq": seq, "layout": layout(), "modules": mods, "marks": marks, "requests": reqs, "models": M.catalog(),
                "config": page_config()}

    def match_requests(self):
        reqs = self.store.requests()
        metas = A.sessions()
        by = {s["name"]: s for s in metas}
        links = A.match(reqs, metas)
        for rid, status in A.expire(reqs).items():
            if rid not in links:
                self.store.update_request(rid, status=status)
        for r in reqs:
            name = r["session_name"] or links.get(r["id"])
            if not name or name not in by:
                continue
            status = A.session_status(by[name])
            if name != r["session_name"] or status != r["status"]:
                self.store.update_request(r["id"], session_name=name, status=status)

    def tick(self):
        self.match_requests()
        self.refresh()
        if self.digest_due and time.monotonic() - self.last_digest >= DIGEST_SECONDS:
            self.write_digest()

    def write_digest(self):
        with self.lock:
            mods = dict(self.mods)
        digest.write(self.data, mods)
        self.digest_due, self.last_digest = False, time.monotonic()

    def loop(self):
        while not self.stop.is_set():
            try:
                self.tick()
            except Exception as e:
                print(f"{iso(config.now())} tick failed: {type(e).__name__}: {e}", file=sys.stderr)
            self.stop.wait(TICK_SECONDS)

    # ---------- writes ----------

    def mark(self, body, by):
        state = body.get("state")
        if state not in ("done", "snoozed", "dismissed", "open"):
            raise ValueError("state must be done, snoozed, dismissed or open")
        title = str(body.get("title") or "").strip()[:300]
        if not title:
            raise ValueError("title is required")
        iid = item_id(title)
        if body.get("item_id") and body["item_id"] != iid:
            raise ValueError("item_id does not match the title")
        until = ""
        if state == "snoozed":
            if body.get("until"):
                u = dt.datetime.fromisoformat(str(body["until"]))
                until = iso(u if u.tzinfo else u.replace(tzinfo=config.tz()))
            else:
                until = iso(tomorrow_morning())
        before = self.store.mark(iid)
        item = self.find_item(iid) or {"id": iid, "title": title, "source": str(body.get("source") or ""),
                                       "ref": str(body.get("ref") or "")}
        seq = self.store.set_mark({"id": iid, "title": title, "source": str(body.get("source") or "")[:200],
                                   "ref": str(body.get("ref") or "")[:300]}, state, until, by=by)
        # the local mark always stands; todoist follows done and its undo, and never fails the mark
        sync = None
        if state == "done" and T.is_todoist(item):
            sync = T.close(item)
            self.store.set_sync(iid, sync["id"], sync)
        elif state == "open" and before and before["state"] == "done" and before.get("todoist_id"):
            old = json.loads(before.get("todoist_sync") or "{}")
            if old.get("ok"):
                sync = T.reopen(before["todoist_id"], old.get("recurring", False))
        if sync:
            A.log_request(self.data, {"at": iso(config.now()), "action": "todoist", "state": state, "title": title,
                                      "ok": sync["ok"], "message": sync["message"]})
        self.refresh(["today"])
        return {"ok": True, "seq": self.store.seq(), "mark_seq": seq, "id": iid,
                "todoist": {k: sync[k] for k in ("ok", "recurring", "message")} if sync else None}

    def find_item(self, iid):
        with self.lock:
            t = self.mods.get("today") or {}
        for i in [t.get("focus")] + (t.get("items") or []) + (t.get("hidden") or []):
            if i and i.get("id") == iid:
                return i
        return None

    def dispatch(self, verb, name, timeout):
        """run "<dispatch cmd> <verb> <name>" as an argv list. returns (code, output)."""
        try:
            p = self.run(dispatch_argv() + [verb, name], capture_output=True, text=True, timeout=timeout)
            return p.returncode, (p.stdout or "") + "\n" + (p.stderr or "")
        except subprocess.TimeoutExpired:
            return -1, f"the dispatch command did not answer in {timeout} s"
        except OSError as e:
            return -1, f"could not run the dispatch command: {type(e).__name__}"

    def archive(self, body):
        """stop a dispatch session through the dispatch command. its report is kept."""
        if not dispatch_argv():
            return OFF
        name = body.get("name")
        if not isinstance(name, str) or not A.handle_re().fullmatch(name):
            raise ValueError("bad session name")
        root = config.path("DAYBOOK_SESSIONS")
        if not root or not (root / "sessions" / f"{name}.json").is_file():
            return 404, {"ok": False, "error": f"{name} is not a current session"}
        code, out = self.dispatch("stop", name, STOP_SECONDS)
        first = plain(next((line.strip() for line in out.splitlines() if line.strip()), ""))[:300]
        # exit 0 with "could not stop it: ..." is a failure too
        ok = code == 0 and first.lower().startswith("stopped")
        A.log_request(self.data, {"at": iso(config.now()), "action": "archive", "name": name, "ok": ok, "code": code,
                                  "output": first})
        self.refresh(["agent", "fleet"])
        return (200 if ok else 502), {"ok": ok, "name": name, "message": first or f"the dispatch command exited {code}",
                                      "code": code}

    def revive(self, body):
        """reopen an archived session in its own conversation, same handle and folder, through "<cmd> revive".
        no prompt and no --yes, so the dispatch's own permission, cap and writer checks all still apply."""
        if not dispatch_argv():
            return OFF
        name = body.get("name")
        if not isinstance(name, str) or not A.handle_re().fullmatch(name):
            raise ValueError("bad session name")
        root = config.path("DAYBOOK_SESSIONS")
        if not root:
            return 404, {"ok": False, "error": f"{name} is not an archived session"}
        if (root / "sessions" / f"{name}.json").is_file():
            return 409, {"ok": False, "error": f"{name} is running, not archived"}
        rec = A._meta(root / "ended" / f"{name}.json")
        if not isinstance(rec, dict) or str(rec.get("name") or name) != name:
            return 404, {"ok": False, "error": f"{name} is not an archived session"}
        with self.lock:
            if name in self.reviving:
                return 409, {"ok": False, "error": f"{name} is already being revived"}
            self.reviving.add(name)
        try:
            code, out = self.dispatch("revive", name, REVIVE_SECONDS)
        finally:
            with self.lock:
                self.reviving.discard(name)
        # only the first line leaves: the rest holds the attach command, and an error can name the agent's own id
        first = next((line.strip() for line in out.splitlines() if line.strip()), "")
        first = plain(UUID.sub("its id", first))[:300]
        ok = code == 0 and first.lower().startswith("resumed")
        A.log_request(self.data, {"at": iso(config.now()), "action": "revive", "name": name, "ok": ok, "code": code,
                                  "output": first})
        self.refresh(["agent", "fleet"])
        url = ""
        if ok:
            url = next((s["url"] for s in A.sessions() if s["name"] == name and not s["ended_flag"]), "")
        status = 200 if ok else 409 if code == 2 or CONFLICT.search(first) else 502
        return status, {"ok": ok, "name": name, "message": first or f"the dispatch command exited {code}", "code": code,
                        "url": url}

    def confirm(self, body):
        """you say whether you sent the text. only a sent request is ever matched to a session."""
        try:
            rid = int(body.get("id"))
        except (TypeError, ValueError):
            raise ValueError("id is required")
        r = self.store.request(rid)
        if not r:
            raise ValueError("no such request")
        if r["status"] not in ("prefilled", "copy", "not_sent", "no_session"):
            return 409, {"error": f"request is {r['status']}"}
        status = "sent" if body.get("sent") is True else "not_sent"
        # a resend after no_session starts the match window again from now
        via = r["via"] if r["via"] in ("sms", "copy") else "copy"
        fields = {"status": status, "via": via}
        if status == "sent" and r["status"] == "no_session":
            fields["at"] = iso(config.now())
        self.store.update_request(rid, **fields)
        A.log_request(self.data, {"at": iso(config.now()), "id": rid, "status": status, "via": via})
        self.refresh(["agent"])
        return 200, {"ok": True, "id": rid, "status": status}

    def request(self, body, by):
        name = A.agent_name()
        try:
            r = A.check(body)
        except A.Outside:
            # outside the roots a click cannot start it; you send the text yourself
            r = A.check(dict(body, where=""))
            r["where"] = one_line(body.get("where"), 500)
            text = A.request_text(r)
            A.log_request(self.data, {"at": iso(config.now()), "title": r["title"], "runner": r["runner"],
                                      "status": "outside", "where": r["where"]})
            return 400, {"error": "outside", "text": text, "sms_url": A.sms_url(text),
                         "message": f"That folder is outside the allowed roots, so a click cannot start it. "
                                    f"Send it to {name} yourself."}
        text = A.request_text(r)
        rid = self.store.add_request(dict(r, text=text, status="prefilled"), by=by)
        status, url, err, via = A.send(text, rid)
        self.store.update_request(rid, status=status, error=err, via=via)
        A.log_request(self.data, {"at": iso(config.now()), "id": rid, "item_id": r["item_id"], "title": r["title"],
                                  "runner": r["runner"], "model": r["model"], "where": r["where"], "reach": r["reach"],
                                  "changed": r["changed"], "status": status, "via": via, "error": err, "by": by,
                                  "text": text})
        self.refresh(["agent"])
        msg = {"sent": f"Sent to {name}." if r["runner"] != "agent" else f"Sent to {name} to handle directly.",
               "prefilled": "Messages opened with the request; tap send.",
               "copy": f"Nothing was sent. Copy the request and send it to {name} yourself.",
               "failed": f"Could not reach {name}. Copy the request and send it yourself."}[status]
        return (200 if status != "failed" else 502), {"ok": status != "failed", "id": rid, "status": status, "text": text,
                                                      "sms_url": url, "message": msg, "error": err}


def allowed_hosts():
    return [h.strip().lower() for h in config.setting("DAYBOOK_ALLOWED_HOSTS").split(",") if h.strip()]


def host_ok(host):
    """an ip, localhost, a bare machine name, or a name listed in DAYBOOK_ALLOWED_HOSTS (".example.net" allows
    every name under it). anything else smells like dns rebinding."""
    h = (host or "").strip().lower()
    h = h[1:h.index("]")] if h.startswith("[") and "]" in h else h.rsplit(":", 1)[0] if h.count(":") == 1 else h
    if not h:
        return False
    try:
        ipaddress.ip_address(h)
        return True
    except ValueError:
        pass
    if h == "localhost" or "." not in h:
        return True
    for a in allowed_hosts():
        if h == a.lstrip(".") or (a.startswith(".") and h.endswith(a)):
            return True
    return False


def client(ua):
    return "phone" if re.search(r"iPhone|iPad|Android|Mobile", ua or "") else "laptop"


def index_html(app):
    page = (WEB / "index.html").read_text()
    tags = "".join(f'<script src="/modules/{m["name"]}.js" defer></script>' for m in MODULES
                   if (WEB / "modules" / f'{m["name"]}.js').is_file())
    return (page.replace("{{token}}", app.token).replace("<!--modules-->", tags)
            .replace("{{title}}", html.escape(config.setting("DAYBOOK_TITLE")))
            .replace("{{agent}}", html.escape(A.agent_name())))


def make_server(app, host=None, port=None, quiet=False):
    host = host or default_host()
    port = default_port() if port is None else port

    class Handler(BaseHTTPRequestHandler):
        server_version = "daybook"
        sys_version = ""

        def head(self, code, ctype, length=None, extra=None):
            self.send_response(code)
            hdrs = {"Content-Type": ctype, "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                    "Referrer-Policy": "no-referrer", "Content-Security-Policy": CSP, "X-Frame-Options": "DENY",
                    "Cross-Origin-Resource-Policy": "same-origin", **(extra or {})}
            if length is not None:
                hdrs["Content-Length"] = str(length)
            for k, v in hdrs.items():
                self.send_header(k, v)
            self.end_headers()

        def send(self, code, body=b"", ctype="text/plain; charset=utf-8"):
            if isinstance(body, (dict, list)):
                body, ctype = json.dumps(body).encode(), "application/json"
            elif isinstance(body, str):
                body = body.encode()
            self.head(code, ctype, len(body))
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_GET(self):
            if not host_ok(self.headers.get("Host")):
                return self.send(421, b"wrong host")
            u = urllib.parse.urlsplit(self.path)
            p, q = u.path, urllib.parse.parse_qs(u.query)
            if p == "/health":
                return self.send(200, {"ok": True, "seq": app.store.seq()})
            if p == "/":
                return self.send(200, index_html(app), "text/html; charset=utf-8")
            if p in STATIC:
                f, ctype = STATIC[p]
                if (WEB / f).is_file():
                    return self.send(200, (WEB / f).read_bytes(), ctype)
            m = re.fullmatch(r"/modules/([a-z0-9_]+)\.js", p)
            if m and m.group(1) in {x["name"] for x in MODULES} and (WEB / "modules" / f"{m.group(1)}.js").is_file():
                return self.send(200, (WEB / "modules" / f"{m.group(1)}.js").read_bytes(), "text/javascript; charset=utf-8")
            if p == "/api/state":
                since = q.get("since", [""])[0]
                return self.send(200, app.state(int(since) if since.isdigit() else None))
            if p == "/api/events":
                return self.events(q)
            if p == "/api/token":
                return self.fresh_token()
            self.send(404, b"not found")

        do_HEAD = do_GET

        def events(self, q):
            since = q.get("since", [""])[0]
            since = int(since) if since.isdigit() else app.store.seq()
            self.head(200, "text/event-stream; charset=utf-8", extra={"X-Accel-Buffering": "no"})
            if self.command == "HEAD":
                return
            try:
                self.wfile.write(f"retry: 3000\nevent: seq\ndata: {app.store.seq()}\n\n".encode())
                self.wfile.flush()
                while not app.stop.is_set():
                    s = app.store.wait(since, HEARTBEAT)
                    self.wfile.write(f"event: seq\ndata: {s}\n\n".encode() if s > since else b": ping\n\n")
                    self.wfile.flush()
                    since = max(since, s)
            except (BrokenPipeError, ConnectionResetError, OSError):
                return

        def fresh_token(self):
            """a page that outlived a restart asks for the new token. same origin only; the host check ran already."""
            site = self.headers.get("Sec-Fetch-Site")
            origin = self.headers.get("Origin")
            if site not in (None, "same-origin") or (origin is not None and urllib.parse.urlsplit(origin).netloc.lower()
                                                       != (self.headers.get("Host") or "").lower()):
                return self.send(403, {"error": "cross origin"})
            return self.send(200, {"token": app.token})

        def guard(self):
            """writes need json, the page's token, and a same-origin origin when one is sent."""
            if not host_ok(self.headers.get("Host")):
                return 421, "wrong host"
            if not (self.headers.get("Content-Type") or "").lower().startswith("application/json"):
                return 415, "json only"
            origin = self.headers.get("Origin")
            if origin is not None and urllib.parse.urlsplit(origin).netloc.lower() != (self.headers.get("Host") or "").lower():
                return 403, "cross origin"
            # compare bytes: a non-ascii header must be a plain 403, not a TypeError
            raw = self.headers.get("X-Daybook-Token") or ""
            if not raw:
                return 403, "bad token"
            if not hmac.compare_digest(raw.encode("utf-8", "surrogateescape"), app.token.encode()):
                # most often a page that outlived a restart; it fetches /api/token and tries once more
                return 403, "stale token"
            raw = self.headers.get("Content-Length")
            if raw is None:
                return 411, "length required"
            if not raw.strip().isdigit():
                return 400, "bad length"
            n = int(raw)
            if n > BODY_MAX:
                return 413, "too big"
            return None, n

        def do_POST(self):
            code, n = self.guard()
            if code:
                return self.send(code, {"error": n})
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("expected an object")
            except ValueError as e:
                return self.send(400, {"error": f"bad json: {e}"})
            by = client(self.headers.get("User-Agent"))
            p = urllib.parse.urlsplit(self.path).path
            try:
                if p == "/api/marks":
                    return self.send(200, app.mark(body, by))
                if p == "/api/requests":
                    code, out = app.request(body, by)
                    return self.send(code, out)
                if p == "/api/requests/sent":
                    code, out = app.confirm(body)
                    return self.send(code, out)
                if p == "/api/sessions/archive":
                    code, out = app.archive(body)
                    return self.send(code, out)
                if p == "/api/sessions/revive":
                    code, out = app.revive(body)
                    return self.send(code, out)
            except ValueError as e:
                return self.send(400, {"error": str(e)})
            self.send(404, {"error": "not found"})

        def log_message(self, fmt, *args):
            if not quiet:
                print(f"{iso(config.now())} {self.address_string()} {fmt % args}", file=sys.stderr)

    srv = ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True
    return srv


def serve(host=None, port=None, data_dir=None):
    app = App(data_dir)
    app.refresh()
    app.write_digest()
    threading.Thread(target=app.loop, daemon=True, name="tick").start()
    srv = make_server(app, host, port)
    h = srv.server_address[0]
    print(f"board on http://{h}:{srv.server_address[1]} data {app.data}", file=sys.stderr)
    try:
        srv.serve_forever()
    finally:
        app.stop.set()
