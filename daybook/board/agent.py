# the agent path: request text, transport (webhook, prefilled sms, or copy by hand), the log, matching to sessions
import datetime as dt
import hashlib
import hmac
import json
import re
import shlex
import time
import tomllib
import urllib.parse
import urllib.request
from pathlib import Path

from .. import config
from ..common import CTRL, has_money, norm, one_line, plain, safe_url, scrub_private, short_path
from . import iso
from . import models as M
from .items import REACH, RUNNERS, allowed

RUNNER_NAME = {"claude": "Claude Code", "codex": "Codex"}
REACH_TEXT = {"draft": "draft (write files only; never submit, send or push)",
              "branch": "branch (commit on a branch; never push)",
              "ship": "ship (may push and deploy their own app)"}
MATCH_BEFORE, MATCH_WINDOW = 10, 30 * 60
PREFILL_EXPIRES, WEBHOOK_EXPECT = 30 * 60, 10 * 60
# words that say nothing about which task it is: stopwords, generic verbs, dispatch boilerplate.
# the configured user and agent names join these at run time
GENERIC = {"the", "a", "an", "and", "or", "for", "with", "on", "my", "to", "of", "in", "at", "by", "from", "into", "then",
           "that", "this", "your", "his", "her", "their", "you", "it", "is", "be", "fix", "check", "review", "update", "add",
           "finish", "start", "do", "make", "write", "read", "get", "set", "run", "new", "asks", "asked", "wants",
           "requests", "request", "please", "session", "claude", "codex", "code", "explicitly", "fresh", "user"}
# grading sessions can quote students and scores; none of it reaches the page
GRADING = re.compile(r"(?i)\bgrad(e|es|ed|ing|er|ers)\b|autograd|\bscor(e|es|ed|ing)\b|rubric|\bstudents?\b|"
                     r"\bpoints? (off|deducted|earned|lost)\b|\bpartial credit\b")
# dispatch's usual tmux homes; a device file may name its own with tmux = "/path"
TMUX = ("/usr/local/bin/tmux", "/opt/homebrew/bin/tmux", "/usr/bin/tmux")
SAFE_PATH = re.compile(r"/[A-Za-z0-9._/-]+")


def agent_name():
    return one_line(config.setting("DAYBOOK_AGENT_NAME"), 40) or "Agent"


def user_name():
    """how request texts name the reader. the default "you" reads as "the user" in a text to the agent."""
    u = one_line(config.setting("DAYBOOK_USER_NAME"), 40)
    return u if u and u.lower() != "you" else "the user"


def board_name():
    return one_line(config.setting("DAYBOOK_TITLE"), 40) or "the board"


def prefix():
    # a letter first and a dash last, so a handle can never be a path or a flag
    p = config.setting("DAYBOOK_SESSION_PREFIX")
    return p if re.fullmatch(r"[a-z][a-z0-9]{0,15}-", p) else "hd-"


# a session's url becomes the Open button, so only remote control links on these two hosts pass
RC_LINK = re.compile(r"https://(claude\.ai|chatgpt\.com)/")


def handle_re():
    return re.compile("^" + re.escape(prefix()) + r"[a-z0-9-]+$")


class Outside(ValueError):
    """the chosen place is outside the allowed roots"""


def check(r):
    """validate a request body from the page. returns a clean dict or raises ValueError."""
    title = one_line(r.get("title"), 300)
    runner = r.get("runner")
    if not title or runner not in RUNNERS:
        raise ValueError("title and runner are required")
    model = one_line(r.get("model"), 80)
    if runner == "agent":
        model = ""
    elif model and not M.find(runner, model):
        raise ValueError("the models list does not offer that model")
    reach = r.get("reach") if r.get("reach") in REACH else None
    if not reach:
        raise ValueError("unknown reach")
    where = one_line(r.get("where"), 500)
    changed = [c for c in (r.get("changed") or []) if c in ("runner", "model", "where", "reach")]
    out = {"item_id": str(r.get("item_id") or "")[:40], "title": title, "runner": runner, "model": model,
           "where": where, "reach": reach, "note": note_text(r.get("note")),
           "source": one_line(r.get("source"), 200), "ref": one_line(r.get("ref"), 300),
           "changed": changed, "suggested_by": "the brief" if r.get("suggested_by") == "brief" else "the board"}
    if where and not allowed(where):
        raise Outside(where)
    return out


def note_text(s):
    """the note keeps its line breaks and nothing else; request_text indents them under "Note:"."""
    s = str(s or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"\s+", " ", CTRL.sub(" ", line)).strip() for line in s.split("\n")]
    return "\n".join(line for line in lines if line)[:2000]


def request_text(r):
    """the plain text the agent reads, the same shape as a text from the user."""
    ch = set(r.get("changed") or [])
    who, board = user_name(), board_name()
    ref = f' ({r["ref"]})' if r.get("ref") and norm(r["ref"]) != norm(r["title"]) else ""
    if r["runner"] == "agent":
        lines = [f'From {board}, {who} asks you to handle this yourself: "{r["title"]}"{ref}.']
    else:
        model = f'model {r["model"]}' if r["model"] else "model: your pick"
        lines = [f'From {board}, {who} asks: start a {RUNNER_NAME[r["runner"]]} session ({model}) for "{r["title"]}"{ref}.']
    lines.append(f"Runner: chosen by {who}." if ch & {"runner", "model"} else "Runner: suggested; route it as you see fit.")
    if r["where"]:
        how = f"chosen by {who}" if "where" in ch else f'suggested by {r.get("suggested_by", "the board")}; change it if wrong'
        lines.append(f'Where: {r["where"]} ({how}).')
    elif r["runner"] != "agent":
        lines.append("Where: not set; pick the right place.")
    lines.append(f'Reach: {REACH_TEXT[r["reach"]]}. ' + (f"Chosen by {who}." if "reach" in ch else "Suggested."))
    note = (r["note"] or "none").replace("\n", "\n    ")
    lines.append(f"Note: {note}" + ("" if note.endswith((".", "!", "?")) else "."))
    return "\n".join(lines)


# ---------- transport ----------

def sign(secret, ts, body):
    """generic webhook v2: hex hmac-sha256 of "<ts>.<body>"."""
    return hmac.new(secret.encode(), str(ts).encode() + b"." + body, hashlib.sha256).hexdigest()


def post_webhook(text, rid, url=None, secret=None, timeout=6):
    url, secret = url or config.setting("DAYBOOK_WEBHOOK_URL"), secret or config.setting("DAYBOOK_WEBHOOK_SECRET")
    body = json.dumps({"text": text, "request_id": rid}).encode()
    ts = int(time.time())
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json", "X-Webhook-Timestamp": str(ts),
        "X-Webhook-Signature-V2": sign(secret, ts, body)})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if not 200 <= resp.status < 300:
            raise OSError(f"webhook answered {resp.status}")


def sms_url(text, to=None):
    """sms:<addr>&body=... is what apple's messages reads; the page swaps in ?body= elsewhere."""
    to = to if to is not None else config.setting("DAYBOOK_AGENT_SMS")
    if not to:
        return ""
    return f"sms:{urllib.parse.quote(to, safe='@+.')}&body={urllib.parse.quote(text, safe='')}"


def transport():
    if config.setting("DAYBOOK_WEBHOOK_URL") and config.setting("DAYBOOK_WEBHOOK_SECRET"):
        return "webhook"
    return "sms" if config.setting("DAYBOOK_AGENT_SMS") else "copy"


def send(text, rid):
    """webhook when configured, else a prefilled sms link, else the text to copy by hand.
    returns (status, sms_url, error, via). no transport is never an error."""
    err = ""
    if transport() == "webhook":
        try:
            post_webhook(text, rid)
            return "sent", "", "", "webhook"
        except Exception as e:
            err = f"webhook failed: {type(e).__name__}"
    url = sms_url(text)
    if url:
        return "prefilled", url, err, "sms"
    return "copy", "", err, "copy"


def log_request(data_dir, entry):
    line = {k: plain(v) if isinstance(v, str) else v for k, v in entry.items()}
    with open(Path(data_dir) / "requests.log", "a") as f:
        f.write(json.dumps(line) + "\n")


# ---------- dispatch sessions ----------

_cache = {}


def _meta(f):
    try:
        m = f.stat().st_mtime
    except OSError:
        return None
    hit = _cache.get(f)
    if hit and hit[0] == m:
        return hit[1]
    try:
        d = json.loads(f.read_text())
    except (OSError, ValueError):
        return None
    _cache[f] = (m, d)
    return d


def ts(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def reports_dir():
    root = config.path("DAYBOOK_SESSIONS")
    return root / "reports" if root else None


def latest_section(name, root=None, hours=None, t=None):
    root = root or reports_dir()
    if not root:
        return ""
    f = root / f"{name}.md"
    try:
        if hours and (t or config.now()).timestamp() - f.stat().st_mtime > hours * 3600:
            return ""
        text = f.read_text(errors="replace")
    except OSError:
        return ""
    return re.split(r"(?m)^(?=## )", text)[-1]


def report_lines(name, root=None, n=2, hours=None, t=None):
    """first lines of the latest section of a session's report, scrubbed. lines with money or grading are dropped."""
    last = latest_section(name, root, hours, t)
    out = []
    for line in last.splitlines():
        line = line.strip()
        # skip headings and lead-ins; they say nothing on their own
        if not line or line.startswith(("#", "changed files", "|")) or re.fullmatch(r"\*\*[^*]+\*\*:?", line) \
                or (line.endswith(":") and len(line) < 60) or len(line) < 12:
            continue
        line = re.sub(r"\*\*|`", "", re.sub(r"^(?:[-*>]\s*)+", "", line))
        line = scrub_private(line)
        if has_money(line) or GRADING.search(line):
            continue
        out.append(line if len(line) <= 240 else line[:240].rsplit(" ", 1)[0] + "...")
        if len(out) >= n:
            break
    return out


def report_excerpt(s, hours=None, t=None):
    """(lines, hidden). the whole excerpt hides for any session near grading, by name, task, place or report."""
    if s.get("sensitive") or GRADING.search(s["name"]) or GRADING.search(s["task"]):
        return [], True
    if GRADING.search(latest_section(s["name"], hours=hours, t=t)):
        return [], True
    return report_lines(s["name"], hours=hours, t=t), False


def ssh_targets():
    """{role or hostname: (user@ip, tmux)} from the device registry. no ssh_user, no target."""
    reg = config.path("DAYBOOK_REGISTRY")
    out = {}
    if not reg:
        return out
    for f in sorted((reg / "devices").glob("*.toml")):
        try:
            d = tomllib.loads(f.read_text())
        except (OSError, tomllib.TOMLDecodeError):
            continue
        ip, user = str(d.get("ip") or d.get("tailscale_ip") or ""), str(d.get("ssh_user") or "")
        if not (re.fullmatch(r"[0-9a-fA-F.:]+", ip) and re.fullmatch(r"[a-z_][a-z0-9_-]*", user)):
            continue
        tmux = str(d.get("tmux") or "")
        if not SAFE_PATH.fullmatch(tmux):
            tmux = next((c for c in TMUX if Path(c).exists()), "tmux")
        for key in (d.get("role"), d.get("hostname")):
            if key:
                out.setdefault(str(key), (f"{user}@{ip}", tmux))
    return out


def attach_command(d, targets):
    """the one line that opens a live tmux session from any machine. native codex threads have no tmux."""
    name, host = str(d.get("name") or ""), str(d.get("host") or "hub")
    if not handle_re().fullmatch(name) or d.get("transport") == "codex-native" or host not in targets:
        return ""
    target, tmux = targets[host]
    return f"ssh -t {target} {tmux} attach -t {shlex.quote(name)}"


def sessions(root=None):
    """live and ended dispatch metas, whitelisted fields only. chat ids, session ids and friends never leave here."""
    root = root or config.path("DAYBOOK_SESSIONS")
    if not root:
        return []
    targets = ssh_targets()
    out = []
    for where, ended in ((root / "sessions", False), (root / "ended", True), (root / "sessions" / "ended", True)):
        for f in sorted(where.glob(f"{prefix()}*.json")):
            d = _meta(f)
            if not isinstance(d, dict):
                continue
            name = str(d.get("name") or f.stem)
            started, stopped = ts(d.get("started_at")), ts(d.get("ended_at"))
            cwd = str(d.get("cwd") or "")
            # a class workdir's grading folder, or any grading path
            sensitive = bool(re.search(r"(?i)/grad(ing|es?|er)(/|$)", cwd))
            task = scrub_private(str(d.get("task") or "").splitlines()[0] if d.get("task") else "")
            if has_money(task):
                task = ""
            if d.get("repo") and d.get("branch"):
                cwd = f'{Path(str(d["repo"])).name} on {d["branch"]}'
            out.append({"name": name, "task": task, "sensitive": sensitive,
                        "cwd": short_path(cwd), "host": str(d.get("host") or ""), "backend": str(d.get("backend") or ""),
                        "model": str(d.get("model") or ""), "status": "ended" if ended else str(d.get("status") or ""),
                        "waiting_for": str(d.get("waiting_for") or ""),
                        "started": iso(dt.datetime.fromtimestamp(started, config.tz())) if started else "",
                        "ended": iso(dt.datetime.fromtimestamp(stopped, config.tz())) if stopped else "",
                        "started_ts": started, "ended_ts": stopped, "ended_flag": ended,
                        "attach": "" if ended else attach_command(d, targets),
                        "url": safe_url(d.get("url")) if RC_LINK.match(str(d.get("url") or "")) else ""})
    return out


def title_of(name):
    """the dispatch name in words: hd-garden-sensor-calibration is "Garden sensor calibration"."""
    p = prefix()
    t = str(name or "")
    t = (t[len(p):] if p and t.startswith(p) else t).replace("-", " ").strip()
    return t[:1].upper() + t[1:]


def generic():
    return GENERIC | set(norm(user_name()).split()) | set(norm(agent_name()).split())


def words(s, stop=None):
    """the distinctive words: numbers, and words of three letters or more that are not generic."""
    stop = generic() if stop is None else stop
    return list(dict.fromkeys(w for w in norm(s).split() if (w.isdigit() or len(w) >= 3) and w not in stop))


def same_word(a, b):
    if a.isdigit() or b.isdigit() or min(len(a), len(b)) < 4:
        return a == b
    return a.startswith(b) or b.startswith(a)


def fuzzy(title, task):
    """at least two distinctive title words, and 60% of them, appear in the task line. else 0."""
    stop = generic()
    want, have = words(title, stop), words(task, stop)
    if len(want) < 2 or not have:
        return 0
    hits = sum(any(same_word(w, h) for h in have) for w in want)
    return hits if hits >= 2 and hits / len(want) >= 0.6 else 0


def session_status(s, root=None):
    if s["ended_flag"]:
        return "done"
    if s["status"] == "busy":
        return "started"
    if s["status"] == "waiting":
        return "waiting"
    if s["status"] == "idle":
        root = root or reports_dir()
        return "done" if root and (root / f'{s["name"]}.md').exists() else "started"
    return "started"


def match(requests, metas, t=None):
    """link sent requests to the session the agent started for them. returns {request_id: session_name}.
    only a request known to be sent is matched; the agent handling it directly starts no session."""
    t = (t or config.now()).timestamp()
    taken = {r["session_name"] for r in requests if r.get("session_name")}
    out = {}
    for r in sorted(requests, key=lambda r: r["id"]):
        if r.get("session_name") or r["status"] != "sent" or r["runner"] not in ("claude", "codex"):
            continue
        at = dt.datetime.fromisoformat(r["at"]).timestamp()
        if t - at > MATCH_WINDOW + 60:
            continue
        window = [s for s in metas if s["name"] not in taken and at - MATCH_BEFORE <= s["started_ts"] <= at + MATCH_WINDOW
                  and s["backend"] in ("", r["runner"])]
        scored = sorted(((fuzzy(r["title"], s["task"]), -s["started_ts"], s) for s in window),
                        key=lambda x: (x[0], x[1]), reverse=True)
        best = scored[0][2] if scored and scored[0][0] else None
        if best:
            out[r["id"]] = best["name"]
            taken.add(best["name"])
    return out


def expire(requests, t=None):
    """{request_id: status} for requests that waited too long: a prefilled or copy text never confirmed as sent,
    or a webhook request no session followed (a gateway can answer 202 before its own checks run)."""
    t = (t or config.now()).timestamp()
    out = {}
    for r in requests:
        age = t - dt.datetime.fromisoformat(r["at"]).timestamp()
        if r["status"] in ("prefilled", "copy") and age > PREFILL_EXPIRES:
            out[r["id"]] = "not_sent"
        elif (r["status"] == "sent" and r.get("via") == "webhook" and r["runner"] != "agent" and not r.get("session_name")
              and age > WEBHOOK_EXPECT):
            out[r["id"]] = "no_session"
    return out
