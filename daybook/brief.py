"""the morning brief: gather -> claude (read-only, subscription) -> html (+ pdf when chrome is around) -> a link.

  daybook brief generate [--date D] [--force]   build <briefs>/D/ (brief.html, morning-brief-D.pdf)
  daybook brief render   [--date D]             rebuild the page from an existing brief.json + context.json
  daybook brief deliver  [--date D] [--force]   print the hand-off once per date: caption + link, or MEDIA: pdf
  daybook brief serve    [--host H] [--port P]  serve <briefs>/D/ pages
  daybook brief status   [--date D]             show what exists for a date
"""
import argparse
import base64
import datetime as dt
import fcntl
import hashlib
import html
import ipaddress
import json
import math
import os
import platform
import random
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import config
from .common import norm, read_json, safe_url, scrub_dashes, scrub_private, split_frontmatter
from .day import (WAKE, SHAPE, booked_minutes, clock, conflicts, day_class, duration, fmt_clock, free_blocks, hm,
                  merge_day, pretty, ribbon, sun_times)

ROOT = config.ROOT
PROMPT = ROOT / "prompt"
TEMPLATES = ROOT / "templates"

CLAUDE_TIMEOUT = 12 * 60
CLAUDE_ATTEMPTS = 2
LOCK_WAIT = 20 * 60

WEATHER_DOMAINS = ["api.weather.gov", "forecast.weather.gov", "api.open-meteo.com", "wttr.in"]
TODOIST_READ = ["mcp__todoist__todoist_task_get", "mcp__todoist__todoist_project_get",
                "mcp__todoist__todoist_section_get"]
BASE_READ = [
    "mcp__claude_ai_Google_Calendar__list_events",
    "mcp__claude_ai_Google_Calendar__get_event",
    "mcp__claude_ai_Google_Calendar__list_calendars",
    "mcp__claude_ai_Gmail__search_threads",
    "mcp__claude_ai_Gmail__get_thread",
    "mcp__claude_ai_Gmail__get_message",
    *TODOIST_READ,
]
# dontAsk already refuses anything not allowed; these deny rules are a second wall
TODOIST_ALL = """activity_by_date_range activity_by_project activity_get archived_projects_get backup_download backups_get
collaborators_get comment_create comment_delete comment_get comment_update completed_tasks_get duplicates_find
duplicates_merge filter_create filter_delete filter_get filter_update invitation_accept invitation_delete
invitation_reject invitations_get label_create label_delete label_get label_stats label_update
notification_mark_read notifications_get notifications_mark_all_read productivity_stats_get project_archive
project_collaborators_get project_create project_delete project_get project_invite project_move_to_parent
project_note_create project_note_delete project_note_update project_notes_get project_update projects_reorder
reminder_create reminder_delete reminder_get reminder_update section_archive section_create section_delete
section_get section_move section_unarchive section_update sections_reorder shared_label_remove
shared_label_rename shared_labels_get subtask_create subtask_promote subtasks_bulk_create task_close task_complete
task_convert_to_subtask task_create task_day_order_update task_delete task_get task_hierarchy_get task_move
task_quick_add task_reopen task_reorder task_update tasks_bulk_complete tasks_bulk_create tasks_bulk_delete
tasks_bulk_update tasks_reorder_bulk test_all_features test_connection test_performance user_get
user_settings_get workspaces_get""".split()
DENY_SERVERS = ["mcp__granola", "mcp__claude-in-chrome", "mcp__claude_ai_Notion", "mcp__claude_ai_Google_Drive",
                "mcp__claude_ai_Claude_Docs", "mcp__claude_ai_Granola", "mcp__claude_ai_Hugging_Face",
                "mcp__claude_ai_Cloudflare_Developer_Platform", "mcp__claude_ai_Consensus", "mcp__claude_ai_Scite"]
WRITE_TOOLS = DENY_SERVERS + [f"mcp__todoist__todoist_{t}" for t in TODOIST_ALL
                              if f"mcp__todoist__todoist_{t}" not in TODOIST_READ] + [
    "mcp__claude_ai_Gmail__send_message", "mcp__claude_ai_Gmail__reply", "mcp__claude_ai_Gmail__forward",
    "mcp__claude_ai_Gmail__create_draft", "mcp__claude_ai_Gmail__update_draft", "mcp__claude_ai_Gmail__delete_draft",
    "mcp__claude_ai_Gmail__trash_message", "mcp__claude_ai_Gmail__trash_thread",
    "mcp__claude_ai_Gmail__update_message_labels", "mcp__claude_ai_Gmail__label_message",
    "mcp__claude_ai_Gmail__label_thread", "mcp__claude_ai_Gmail__unlabel_message",
    "mcp__claude_ai_Gmail__unlabel_thread",
    "mcp__claude_ai_Google_Calendar__create_event", "mcp__claude_ai_Google_Calendar__update_event",
    "mcp__claude_ai_Google_Calendar__delete_event", "mcp__claude_ai_Google_Calendar__respond_to_event",
    "mcp__claude_ai_Gmail__mark_message_spam", "mcp__claude_ai_Gmail__mark_thread_spam",
    "mcp__claude_ai_Gmail__unmark_message_spam", "mcp__claude_ai_Gmail__unmark_thread_spam",
    "mcp__claude_ai_Gmail__untrash_message", "mcp__claude_ai_Gmail__untrash_thread",
    "mcp__claude_ai_Gmail__create_label", "mcp__claude_ai_Gmail__update_label", "mcp__claude_ai_Gmail__delete_label",
    "mcp__claude_ai_Gmail__apply_sensitive_message_label", "mcp__claude_ai_Gmail__apply_sensitive_thread_label",
    "mcp__claude_ai_Google_Calendar__suggest_time",
    "Bash", "Write", "Edit", "NotebookEdit",
]
# an extra read tool may never be a write tool, a whole server, a wildcard or a shell
WRITE_WORDS = re.compile(r"(?i)(send|reply|forward|draft|create|update|delete|trash|label|move|close|complete|"
                         r"archive|invite|accept|reject|respond|mark|reopen|reorder|merge|promote|convert|write|edit|"
                         r"upload|share|post|comment|apply)")
# never let a stray key in the cron env turn this into api billing
STRIP_ENV = ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL",
             "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_OAUTH_TOKEN"]


def briefs():
    return config.path("DAYBOOK_BRIEFS")


def state():
    return config.path("DAYBOOK_DATA") / "state"


def news_domains():
    f = PROMPT / "news-domains.txt"
    return f.read_text().split() if f.exists() else []


# extra tools pass only when their name starts with a read verb (get_x, list_x, search_x, x_get, ...)
READ_NAME = re.compile(r"^(?:[a-z0-9]+_)*?(get|list|search|read|fetch|query|find|view|lookup|describe)(?:_|$)|"
                       r"_(get|list|search|read|query|find|view)$", re.I)


def extra_read_tools():
    out = []
    for t in (x.strip() for x in config.setting("DAYBOOK_EXTRA_READ_TOOLS").split(",")):
        if not re.fullmatch(r"mcp__[A-Za-z0-9_-]+__[A-Za-z0-9_-]+", t or ""):
            continue  # whole servers, wildcards and built-ins are refused
        if t in WRITE_TOOLS or any(t.startswith(s + "__") for s in DENY_SERVERS) or WRITE_WORDS.search(t.split("__")[-1]):
            continue
        if not READ_NAME.match(t.split("__")[-1]):
            continue  # the tool's own name has to say it only reads
        out.append(t)
    return out


def read_tools():
    return ["WebSearch", *[f"WebFetch(domain:{d})" for d in WEATHER_DOMAINS + news_domains()], *BASE_READ,
            *extra_read_tools()]


def log(day_dir, msg):
    line = f"{dt.datetime.now(config.tz()).isoformat(timespec='seconds')} {msg}"
    print(line, file=sys.stderr)
    day_dir.mkdir(parents=True, exist_ok=True)
    with open(day_dir / "run.log", "a") as f:
        f.write(line + "\n")


def today():
    return config.now().date()


def pdf_path(day):
    return briefs() / day.isoformat() / f"morning-brief-{day.isoformat()}.pdf"


# ---------- the school folder ----------

def parse_due(raw):
    tz = config.tz()
    if not raw:
        return None, False
    try:
        if "T" in raw or " " in raw.strip():
            return dt.datetime.fromisoformat(raw.replace(" ", "T")).replace(tzinfo=tz), True
        return dt.datetime.combine(dt.date.fromisoformat(raw), dt.time(23, 59), tz), False
    except ValueError:
        return None, False


DAYS = {"M": 0, "T": 1, "W": 2, "R": 3, "F": 4, "S": 5, "U": 6}
SCHOOL_OFF = {"class_meetings": [], "due_soon": [], "to_grade": [], "decisions_owed": [], "office_hours": [],
              "recent_lectures": [], "todoist_task_ids": [], "problems": [], "workdirs": {}}


def school_context(day, root=None):
    """everything the school section and class meetings need, read straight from the school folder."""
    root = root or config.path("DAYBOOK_SCHOOL")
    if root is None:
        return dict(SCHOOL_OFF, off=True)
    if not any((root / "classes").glob("*/class.md")):
        raise OSError("no class.md files under the school folder's classes/")
    tz = config.tz()
    meetings, due, grade, ids, problems, office = [], [], [], [], [], []
    ta_done, ta_closed = [], []  # evidence only: finished grading jobs, past student cutoffs
    workdirs = {}  # class code -> the folder its coursework lives in, for the hand-off defaults
    start_of_day = dt.datetime.combine(day, dt.time(0, 0), tz)
    horizon = day + dt.timedelta(days=14)
    for cdir in sorted((root / "classes").glob("*")):
        cfile = cdir / "class.md"
        if cdir.name.startswith("_") or not cfile.exists():
            continue
        c, cbody = split_frontmatter(cfile)
        code, role = c.get("code", cdir.name.upper()), c.get("role", "student")
        if c.get("workdir"):
            # relative workdirs resolve against the school folder
            workdirs[code] = os.path.normpath(root / os.path.expanduser(c["workdir"]))
        oh = re.search(r"^## Office hours\n+(.*?)(?=\n## |\Z)", cbody, re.S | re.M)
        if role == "ta" and oh:
            office.append({"class": code, "text": re.sub(r"\s+", " ", oh.group(1)).strip()[:400]})
        try:
            starts, ends = dt.date.fromisoformat(c.get("starts", "")), dt.date.fromisoformat(c.get("ends", ""))
        except ValueError:
            starts, ends = None, None
        m = re.match(r"([MTWRFSU]+)\s+(\d{1,2}:\d{2})-(\d{1,2}:\d{2})", c.get("schedule", ""))
        for d in (day, day + dt.timedelta(days=1)):
            in_term = starts is None or starts <= d <= ends
            if m and in_term and d.weekday() in [DAYS[x] for x in m.group(1)]:
                meetings.append({"day": "today" if d == day else "tomorrow", "class": code,
                                 "name": c.get("name", ""), "role": role,
                                 "time": f"{fmt_clock(m.group(2).zfill(5))} - {fmt_clock(m.group(3).zfill(5))}",
                                 "start": m.group(2).zfill(5), "end": m.group(3).zfill(5)})
        for a in sorted((cdir / "assignments").glob("*.md")):
            if a.name.startswith("_"):
                continue
            f, _ = split_frontmatter(a)
            if f.get("todoist_task_id"):
                ids.append(f["todoist_task_id"])
            grading = f.get("grading", "").lower() == "true"
            status = f.get("status", "open")
            when, has_time = parse_due(f.get("due", ""))
            if status != "open":
                if role == "ta" and grading:
                    ta_done.append({"class": code, "title": f.get("title", a.stem), "status": status,
                                    "due": f.get("due", ""), "file": f"{cdir.name}/{a.name}"})
                continue
            if when is None:
                problems.append(f"{cdir.name}/{a.name}: no parseable due date")
                continue
            # overdue counts only inside this term; older dates are stale template data
            if starts and when.date() < starts:
                problems.append(f"{cdir.name}/{a.name}: open but due {when.date()}, before this term")
                continue
            if when.date() > horizon:
                continue
            item = {"class": code, "title": f.get("title", a.stem), "overdue": when < start_of_day,
                    "sort": when.isoformat(),
                    "due": when.strftime("%a %b %-d, %-I:%M %p").replace(":00 ", " ") if has_time
                    else when.strftime("%a %b %-d")}
            if role != "ta":
                due.append(item)
            elif grading:
                # the reader's own grading job; it closes when the file flips to graded
                grade.append(dict(item, kind="grading"))
            elif item["overdue"]:
                # a student cutoff that passed is not owed work. student files stay "open"
                # forever, so only grading: true records can say grading is outstanding
                ta_closed.append(dict(item, file=f"{cdir.name}/{a.name}"))
            else:
                grade.append(dict(item, kind="students_due"))
    for lst in (due, grade):
        lst.sort(key=lambda x: (not x["overdue"], x["sort"]))
    # optional: one "## " heading per decision owed
    review = root / "inbox" / "decisions.md"
    decisions = [l[3:].strip() for l in review.read_text(errors="replace").splitlines() if l.startswith("## ")] \
        if review.exists() else []
    lectures = []
    for lf in sorted((root / "classes").glob("*/lectures/*.md")):
        mm = re.match(r"(\d{4}-\d{2}-\d{2})", lf.name)
        try:
            ldate = dt.date.fromisoformat(mm.group(1)) if mm else None
        except ValueError:
            ldate = None
        if not ldate or not (day - dt.timedelta(days=2) <= ldate <= day):
            continue
        f, body = split_frontmatter(lf)
        # never past the transcript heading; html comments are notes to people, not lecture content
        summary = re.sub(r"<!--.*?-->", "", body.split("## Transcript")[0], flags=re.S).strip()
        lectures.append({"class": f.get("class", lf.parent.parent.name.upper()), "date": mm.group(1),
                         "title": f.get("title", ""), "topics": f.get("topics", ""), "summary": summary[:1500]})
    return {"date": day.isoformat(), "class_meetings": meetings, "due_soon": due, "to_grade": grade,
            "ta_grading_done": ta_done, "ta_cutoffs_closed": ta_closed,
            "decisions_owed": decisions, "recent_lectures": lectures, "todoist_task_ids": ids,
            "office_hours": office, "workdirs": workdirs, "problems": problems}


def open_prs():
    """open prs authored by the gh user, with review and check state. None means gh failed."""
    gh = config.setting("DAYBOOK_GH")
    deadline = time.monotonic() + 120
    try:
        r = subprocess.run([gh, "search", "prs", "--author", "@me", "--state", "open", "--limit", "30",
                            "--json", "repository,number,title,url,isDraft,updatedAt"],
                           capture_output=True, text=True, timeout=60)
        if r.returncode:
            return None
        prs = json.loads(r.stdout)
        for p in prs:
            if time.monotonic() > deadline:
                break
            v = subprocess.run([gh, "pr", "view", str(p["number"]), "-R", p["repository"]["nameWithOwner"],
                                "--json", "reviewDecision,statusCheckRollup,mergeable"],
                               capture_output=True, text=True, timeout=30)
            if v.returncode == 0:
                d = json.loads(v.stdout)
                checks = [c.get("conclusion") or c.get("state") or c.get("status") for c in d.get("statusCheckRollup") or []]
                p.update(reviewDecision=d.get("reviewDecision") or "", mergeable=d.get("mergeable") or "",
                         checks="failing" if any(c in ("FAILURE", "ERROR", "TIMED_OUT") for c in checks)
                         else "pending" if any(c in ("PENDING", "IN_PROGRESS", "QUEUED") for c in checks)
                         else "passing" if checks else "none")
        return prs
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


# ---------- projects: session reports, sessions, git ----------

LOOKBACK_HOURS = 36


def session_reports(now, root=None, hours=LOOKBACK_HOURS, limit=8):
    """latest section of each dispatch report touched in the lookback window."""
    out = []
    if root is None:
        s = config.path("DAYBOOK_SESSIONS")
        if s is None:
            return out
        root = s / "reports"
    try:
        files = sorted(root.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
    except OSError:
        return out
    for f in files[:limit * 2]:
        mtime = dt.datetime.fromtimestamp(f.stat().st_mtime, config.tz())
        if now - mtime > dt.timedelta(hours=hours):
            break
        text = f.read_text(errors="replace")
        parts = re.split(r"(?m)^(?=## )", text)
        last = parts[-1].strip() if parts else text
        out.append({"name": f.stem, "updated": mtime.isoformat(timespec="minutes"),
                    "text": head_tail(scrub_private(last))})
        if len(out) >= limit:
            break
    return out


def head_tail(text, head=650, tail=550):
    """the opening and the closing of a report; asks and approvals sit at the end."""
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    return text if len(text) <= head + tail + 20 else text[:head].rstrip() + "\n[...]\n" + text[-tail:].lstrip()


def session_list(root=None):
    """names and states of dispatch sessions, nothing else."""
    out = []
    if root is None:
        s = config.path("DAYBOOK_SESSIONS")
        if s is None:
            return out
        root = s / "sessions"
    for f in sorted(root.glob(f'{config.setting("DAYBOOK_SESSION_PREFIX")}*.json')):
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        out.append({"name": str(d.get("name", f.stem)), "status": str(d.get("status", ""))})
    return out


# bookkeeping the brief never reports: automated syncs, merges, wip
GIT_NOISE = re.compile(r"(?i)^(sync: automated|auto[- ]?sync|merge (branch|pull)|wip\b)")


def git_activity(now, root=None, hours=LOOKBACK_HOURS):
    """commit subjects from the lookback window, per repo, newest first."""
    root = root or config.path("DAYBOOK_PROJECTS")
    if root is None:
        return []
    since = (now - dt.timedelta(hours=hours)).isoformat()
    out = []
    for repo in sorted(root.glob("*/.git")):
        if repo.parent.resolve() == ROOT:
            continue
        try:
            r = subprocess.run(["git", "-C", str(repo.parent), "log", "--all", f"--since={since}",
                                "--no-merges", "--format=%s", "-n", "6"],
                               capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            continue
        subjects = [scrub_private(x)[:140] for x in r.stdout.splitlines() if x.strip() and not GIT_NOISE.match(x)][:4]
        if subjects:
            out.append({"repo": repo.parent.name, "commits": subjects})
    return out


# ---------- news feeds ----------

NEWS_HOURS = 40
NEWS_MAX_CANDIDATES = 20
# status-page incidents and the like: real, but never a story
NEWS_SKIP = re.compile(r"(?i)^(elevated errors|degraded performance|investigating|resolved:|partial outage)")
# release candidates, alphas, canaries, and per-commit b1234 builds
PRERELEASE = re.compile(r"(?i)(\brc\d*\b|-rc|alpha|beta|canary|nightly|preview build|-pre\b|\bdev\d|^b\d{4,}\b)")


def feed_date(raw):
    from email.utils import parsedate_to_datetime
    raw = (raw or "").strip()
    try:
        d = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            d = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def parse_feed(text, source, now, hours=NEWS_HOURS, release=False):
    """recent, non-prerelease items from an rss or atom document. dates are the feed's own."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    out = []
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag not in ("item", "entry"):
            continue
        kids = {c.tag.rsplit("}", 1)[-1]: c for c in node}
        title = html.unescape((kids["title"].text or "").strip()) if "title" in kids else ""
        link = kids.get("link")
        url = ""
        if link is not None:
            url = (link.get("href") or link.text or "").strip()
        when = None
        for k in ("published", "updated", "pubDate", "date"):
            if k in kids and (when := feed_date(kids[k].text)):
                break
        if not title or not url.startswith("https://") or when is None or PRERELEASE.search(title):
            continue
        if when > now + dt.timedelta(hours=2) or now - when > dt.timedelta(hours=hours):
            continue
        body = next((kids[k].text for k in ("summary", "description", "content") if k in kids and kids[k].text), "")
        body = html.unescape(re.sub(r"<[^>]+>", " ", html.unescape(body or "")))
        item = {"source": source, "title": title[:160], "url": url,
                "published": when.astimezone(config.tz()).date().isoformat(),
                "summary": re.sub(r"\s+", " ", body).strip()[:600 if release else 220]}
        if release:  # the release notes are the primary source; no fetch needed to describe them
            item["kind"] = "release"
        out.append(item)
    return out[:2 if release else 3]


def read_feeds(path):
    try:
        lines = Path(path).read_text().splitlines()
    except OSError:
        return []
    return [l.split("\t", 1) for l in lines if l.strip() and not l.startswith("#") and "\t" in l]


def news_candidates(now):
    """read every feed in the feeds file in parallel. a dead feed just contributes nothing."""
    path = config.path("DAYBOOK_NEWS_FEEDS")
    if path is None:
        return {"status": "off", "items": [], "feeds_ok": 0, "feeds": 0}
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor
    feeds = read_feeds(path)

    def one(f):
        name, url = f
        try:
            req = urllib.request.Request(url.strip(), headers={"User-Agent": "daybook/1 (personal feed reader)"})
            with urllib.request.urlopen(req, timeout=10) as r:
                return name, parse_feed(r.read(2_000_000).decode("utf-8", "replace"), name, now,
                                        release=url.strip().endswith("/releases.atom")), True
        except (OSError, ValueError):
            return name, [], False

    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(one, feeds))
    items = [i for _, got, _ in results for i in got if not NEWS_SKIP.search(i["title"])]
    return {"status": "ok", "items": items[:NEWS_MAX_CANDIDATES], "feeds_ok": sum(ok for *_, ok in results),
            "feeds": len(feeds)}


# ---------- weather ----------

def parse_nws(forecast, hourly, day):
    """one line, the day's and night's forecast, and a few hours, from nws gridpoint json."""
    per = forecast["properties"]["periods"]
    on = lambda p: dt.datetime.fromisoformat(p["startTime"]).date() == day
    d = next((p for p in per if on(p) and p["isDaytime"]), None)
    n = next((p for p in per if on(p) and not p["isDaytime"] and dt.datetime.fromisoformat(p["startTime"]).hour >= 12), None)
    if not d and not n:
        raise ValueError("forecast has no period for this date")
    nxt = next((p for p in per if p["isDaytime"] and dt.datetime.fromisoformat(p["startTime"]).date() == day + dt.timedelta(days=1)), None)
    line = f'{(d or n)["shortForecast"]}, {d["temperature"]} / {n["temperature"]}' if d and n else \
        f'{(d or n)["shortForecast"]}, {(d or n)["temperature"]}'
    hours = []
    for h in (hourly or {}).get("properties", {}).get("periods", []):
        t = dt.datetime.fromisoformat(h["startTime"])
        if t.date() == day and 6 <= t.hour <= 21:
            hours.append({"h": t.hour, "t": h["temperature"], "pop": (h.get("probabilityOfPrecipitation") or {}).get("value") or 0,
                          "sky": h.get("shortForecast", "")})
    return {"status": "ok", "line": line, "today": d["detailedForecast"] if d else "",
            "tonight": n["detailedForecast"] if n else "",
            "tomorrow": f'{nxt["shortForecast"]}, high {nxt["temperature"]}' if nxt else "", "hourly": hours,
            "note": "NWS forecast, read by code"}


def weather_context(day):
    where = config.latlon()
    if config.setting("DAYBOOK_WEATHER").lower() != "nws" or not where:
        return {"status": "off", "note": "no forecast source set"}
    import urllib.request

    def get(url):
        req = urllib.request.Request(url, headers={"User-Agent": "daybook/1 (personal)", "Accept": "application/geo+json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read(3_000_000))
    try:
        pt = get(f"https://api.weather.gov/points/{where[0]:.4f},{where[1]:.4f}")["properties"]
        fc = get(pt["forecast"])
        try:
            hr = get(pt["forecastHourly"])
        except (OSError, ValueError):
            hr = {}
        return parse_nws(fc, hr, day)
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as e:
        return {"status": "unavailable", "note": f"NWS read failed ({type(e).__name__})"}


def weather_prompt(wx):
    """compact weather for the model; hours as '7a 58F 0%'."""
    if wx.get("status") != "ok":
        place = config.setting("DAYBOOK_LOCATION")
        return f"unavailable: fetch today's forecast for {place} yourself" if place else \
            "unavailable: no location is set, so leave weather out"
    hrs = ", ".join(f'{h["h"] % 12 or 12}{"a" if h["h"] < 12 else "p"} {h["t"]}F {h["pop"]}%' for h in wx["hourly"][1::2])
    return json.dumps({"line": wx["line"], "today": wx["today"], "tonight": wx["tonight"], "tomorrow": wx["tomorrow"],
                       "hours": hrs}, ensure_ascii=False, separators=(",", ":"))


# ---------- a second mailbox through an approved connector (optional) ----------

MAIL_FIELDS = ("kind", "title", "from", "received", "due", "summary", "source")
MAIL_MAX_ITEMS = 12


def mail_context(handoff=None):
    """mailbox items through an approved connector command, minimized. never logs in itself."""
    handoff = handoff or config.path("DAYBOOK_MAIL_HANDOFF")
    if handoff is None:
        return {"status": "off", "items": [], "note": "no second mailbox set"}
    off = {"status": "not_connected", "items": [],
           "note": "the mail connector is not approved yet"}
    try:
        h = json.loads(Path(handoff).read_text())
    except (OSError, ValueError):
        return off
    if not isinstance(h, dict) or h.get("approved") is not True or not h.get("command"):
        return off
    try:
        r = subprocess.run(h["command"], capture_output=True, text=True, timeout=90)
        data = json.loads(r.stdout) if r.returncode == 0 else None
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
        data = None
    if not isinstance(data, dict):
        return {"status": "unavailable", "items": [], "note": "the mail connector failed this morning"}
    items = []
    for it in (data.get("items") or [])[:MAIL_MAX_ITEMS]:
        if isinstance(it, dict):
            items.append({k: scrub_private(str(it.get(k, "")))[:300 if k == "summary" else 160]
                          for k in MAIL_FIELDS})
    # mail goes to a cloud model only with explicit approval; otherwise code lists it
    return {"status": "ok", "items": items, "fetched_at": str(data.get("fetched_at", "")),
            "send_to_model": h.get("send_to_model") is True,
            "note": f"{len(items)} items from the approved connector"}


# ---------- marks from the board ----------

MARK_DAYS = 14
MARKS_MAX, MARKS_KEEP, MARK_TITLE, MARKS_MAX_BYTES = 40, 2000, 120, 1_000_000


def mark_active(m, day):
    """done or dismissed in the last two weeks, or snoozed past this date."""
    tz = config.tz()
    try:
        if m.get("state") == "snoozed":
            return dt.date.fromisoformat(str(m.get("until") or "")[:10]) > day
        if m.get("state") in ("done", "dismissed"):
            at = dt.datetime.fromisoformat(str(m.get("at") or "").replace("Z", "+00:00"))
            at = at if at.tzinfo else at.replace(tzinfo=tz)
            return (day - at.astimezone(tz).date()).days <= MARK_DAYS
    except ValueError:
        pass
    return False


def mark_time(m):
    try:
        at = dt.datetime.fromisoformat(str(m.get("at") or "").replace("Z", "+00:00"))
        return (at if at.tzinfo else at.replace(tzinfo=config.tz())).timestamp()
    except Exception:
        return 0.0


def load_marks(day, path=None):
    """active marks, minimized. nothing in the file can fail the run: bad marks are skipped."""
    path = Path(path or config.marks_file())
    try:
        if path.stat().st_size > MARKS_MAX_BYTES:
            return {"status": "unavailable", "items": [], "note": "marks file too large"}
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return {"status": "none", "items": [], "note": "no marks file"}
    except Exception as e:  # unreadable, bad json, too deep: never fatal
        return {"status": "unavailable", "items": [], "note": f"marks file unreadable ({type(e).__name__})"}
    if not isinstance(data, dict) or not isinstance(data.get("marks"), list):
        return {"status": "unavailable", "items": [], "note": "marks file malformed"}
    items = []
    for m in data["marks"]:
        try:
            if not isinstance(m, dict) or not mark_active(m, day):
                continue
            it = {k: str(m.get(k) or "")[:200] for k in ("source", "ref", "state", "until")}
            it["title"] = str(m.get("title") or "")[:MARK_TITLE]
            it["norm"] = norm(m.get("norm") or m.get("title") or "")
            if it["norm"] or it["ref"]:
                items.append((mark_time(m), it))
        except Exception:  # one odd mark costs only itself
            continue
    # newest first; code drops against all of them, the prompt sees the first MARKS_MAX
    items = [it for _, it in sorted(items, key=lambda x: x[0], reverse=True)][:MARKS_KEEP]
    return {"status": "ok", "items": items, "note": f"{len(items)} active mark{'' if len(items) == 1 else 's'} from the board"}


def drop_marked(b, marks):
    """to-dos marked on the board never come back: matched by normalized title or todoist id."""
    names = {m["norm"] for m in marks if m.get("norm")}
    refs = {m["ref"] for m in marks if m.get("ref")}
    kept, gone = [], []
    for t in b.get("todoist_schedule") or []:
        if norm(t.get("title")) in names or str(t.get("id", "")) in refs:
            gone.append(t.get("title"))
        else:
            kept.append(t)
    names |= {norm(x) for x in gone}
    acts = []
    for a in b.get("next_actions") or []:
        if norm(a.get("title")) in names:
            gone.append(a.get("title"))
        else:
            acts.append(a)
    return dict(b, todoist_schedule=kept, next_actions=acts), gone


# ---------- day shape ----------

def school_buckets(items, day):
    """overdue, due today or tomorrow, rest of the week, later."""
    b = {"overdue": [], "now": [], "week": [], "later": []}
    for i in items:
        when = dt.datetime.fromisoformat(i["sort"]).date()
        key = ("overdue" if i.get("overdue") or when < day else "now" if when <= day + dt.timedelta(days=1)
               else "week" if when <= day + dt.timedelta(days=6) else "later")
        b[key].append(i)
    return b


# ---------- model output hygiene ----------

NEWS_STATUS = {"available", "announced", "research", "rumor", "update"}
NEWS_MAX_AGE = 3


def clean_news(items, day, candidates=()):
    """dated, linked, recent, deduped. a stale story never reads as today's. feed dates beat the model's."""
    fed = {c["url"].rstrip("/"): c["published"] for c in candidates}
    out, seen = [], set()
    for n in items or []:
        if str(n.get("url", "")).rstrip("/") in fed:
            n = dict(n, published=fed[str(n["url"]).rstrip("/")])
        try:
            pub = dt.date.fromisoformat(str(n.get("published", ""))[:10])
        except ValueError:
            continue
        url = safe_url(n.get("url"))
        if not url or pub > day or (day - pub).days > NEWS_MAX_AGE or n.get("status") not in NEWS_STATUS:
            continue
        key = url.split("#")[0].rstrip("/")
        if key in seen or norm(n.get("headline")) in seen:
            continue
        seen |= {key, norm(n.get("headline"))}
        out.append(dict(n, url=url))
    return out[:5]


def clean_actions(items):
    today, week, seen = [], [], set()
    for a in items or []:
        k = norm(a.get("title"))
        if not k or k in seen:
            continue
        seen.add(k)
        a = dict(a, url=safe_url(a.get("url")))
        (week if a.get("horizon") == "this_week" else today).append(a)
    return today[:5], week[:4]


RUNNERS, REACH = ("agent", "claude", "codex"), ("draft", "branch", "ship")
MODEL_ID = re.compile(r"^[a-z0-9][a-z0-9.:_-]{0,39}$")


def where_roots():
    """folders a handed-off task may run in: the projects folder and any extra work roots."""
    roots = [config.path("DAYBOOK_PROJECTS"), *config.paths("DAYBOOK_WORK_ROOTS")]
    return [Path(os.path.normpath(r)) for r in roots if r and r.is_absolute()]


def safe_where(p, roots=None):
    """'' or an absolute path inside an allowed root."""
    if not isinstance(p, str) or not p.startswith("/") or ".." in Path(p).parts:
        return ""
    q = Path(os.path.normpath(p))
    return str(q) if any(q.is_relative_to(r) for r in (where_roots() if roots is None else roots)) else ""


def clean_handoff(r):
    """suggested defaults for handing an action off; anything unknown is the agent itself, draft."""
    r = r if isinstance(r, dict) else {}
    model = r.get("model")
    return {"runner": r.get("runner") if r.get("runner") in RUNNERS else "agent",
            "model": model if isinstance(model, str) and MODEL_ID.match(model) else "default",
            "where": safe_where(r.get("where")),
            "reach": r.get("reach") if r.get("reach") in REACH else "draft",
            "prompt": re.sub(r"\s+", " ", str(r.get("prompt") or "")).strip()[:400]}


# ---------- claude ----------

def about_text():
    f = PROMPT / "about.md"
    try:
        t = re.sub(r"<!--.*?-->", "", f.read_text(), flags=re.S).strip()
    except OSError:
        t = ""
    return t or f'The reader is {config.setting("DAYBOOK_USER_NAME")}. Nothing more is known; keep it general.'


def build_prompt(day, ctx, weekly=None):
    t = (PROMPT / "brief.md").read_text()
    t = re.sub(r"^<!--.*?-->\n", "", t, flags=re.S)
    # code already filters todoist mirrors, past cutoffs and stale files, so those lists stay out
    sc = ctx["school"]
    if sc.get("off"):
        school = "off: no school folder is set"
    else:
        school = {"due_soon": [{k: i.get(k) for k in ("class", "title", "due", "overdue")} for i in sc.get("due_soon", [])],
                  "to_grade": [{k: i.get(k) for k in ("class", "title", "due", "kind")} for i in sc.get("to_grade", [])],
                  "decisions_owed": sc.get("decisions_owed", [])[-5:], "decisions_owed_total": len(sc.get("decisions_owed", [])),
                  "office_hours": sc.get("office_hours", []), "workdirs": sc.get("workdirs", {})}
    lectures = [dict(l, summary=l.get("summary", "")[:700]) for l in sc.get("recent_lectures", [])]
    meetings = [{k: m.get(k) for k in ("day", "class", "name", "role", "time")} for m in sc.get("class_meetings", [])]
    pj = ctx.get("projects") or {}
    mail = dict(ctx.get("mail") or {"status": "off", "items": []})
    if not mail.get("send_to_model"):
        mail["items"] = f'{len(mail.get("items", []))} items, listed by code; not shared with you'

    def j(x):
        return json.dumps(x, ensure_ascii=False, separators=(",", ":"))
    marked = [m["title"] for m in (ctx.get("marks") or {}).get("items", []) if m.get("title")][:MARKS_MAX]
    prs = ctx["prs"]
    if prs is not None:
        prs = [{"repo": x["repository"]["nameWithOwner"], **{k: x.get(k) for k in ("number", "title", "url", "isDraft",
                                                                                     "reviewDecision", "checks", "mergeable")}}
               for x in prs]
    off = set(ctx.get("off") or [])
    todoist = config.setting("DAYBOOK_TODOIST_PROJECT")
    roots = [str(r) for r in where_roots()]
    subs = {
        "{{USER}}": config.setting("DAYBOOK_USER_NAME"),
        "{{AGENT}}": config.setting("DAYBOOK_AGENT_NAME"),
        "{{TZ}}": config.setting("DAYBOOK_TZ"),
        "{{LOCATION}}": config.setting("DAYBOOK_LOCATION") or "not set",
        "{{CALENDAR_ID}}": config.setting("DAYBOOK_CALENDAR_ID"),
        "{{TODOIST_PROJECT}}": f"the project with id {todoist}" if todoist else "the Inbox project",
        "{{ABOUT}}": about_text(),
        "{{WHERE_ROOTS}}": j(roots) if roots else "none (always use \"\")",
        "{{DAY_LONG}}": day.strftime("%A, %B %-d, %Y"),
        "{{DATE_ISO}}": day.isoformat(),
        "{{CLASS_MEETINGS}}": j(meetings),
        "{{SCHOOL}}": school if isinstance(school, str) else j(school),
        "{{LECTURES}}": j(lectures),
        "{{PRS}}": "off (not set up)" if "prs" in off else j(prs) if prs is not None else "unavailable (gh failed)",
        "{{REPORTS}}": "\n\n".join(f'### {r["name"]} ({r["updated"]})\n{head_tail(r["text"])}'
                                   for r in pj.get("reports", [])) or "none",
        "{{GIT}}": "\n".join(f'{g["repo"]}: ' + " | ".join(g["commits"][:4]) for g in pj.get("git", [])) or "none",
        "{{MAIL}}": j(mail),
        "{{WEATHER}}": weather_prompt(ctx.get("weather") or {}),
        "{{NEWS}}": "\n".join(j(n) for n in (ctx.get("news") or {}).get("items", [])[:NEWS_MAX_CANDIDATES]) or "none",
        "{{WEEKEND}}": "yes" if day.weekday() >= 5 else "no",
        "{{MARKS}}": j(marked) if marked else "none",
        "{{WEEKLY}}": "\n".join(f'{e["answer"]} {e["enum"]}' for e in weekly) if weekly else "none",
    }
    # one pass, so text from the context can never be read as another placeholder
    return re.sub(r"\{\{[A-Z_]+\}\}", lambda m: subs.get(m.group(0), m.group(0)), t)


def claude_bin():
    c = config.setting("DAYBOOK_CLAUDE")
    return shutil.which(c) or c


def run_claude(day_dir, prompt, attempt):
    env = {k: v for k, v in os.environ.items() if k not in STRIP_ENV}
    claude = claude_bin()
    env["PATH"] = f"{Path(claude).parent}:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"
    schema = (PROMPT / "schema.json").read_text()
    cmd = [claude, "-p", "--model", config.setting("DAYBOOK_CLAUDE_MODEL"), "--output-format", "stream-json", "--verbose",
           "--no-session-persistence", "--permission-mode", "dontAsk",
           "--tools", "WebSearch,WebFetch",
           "--allowedTools", ",".join(read_tools()),
           "--disallowedTools", ",".join(WRITE_TOOLS),
           "--settings", json.dumps({"disableAllHooks": True}),
           "--json-schema", schema]
    raw = day_dir / f"claude-attempt{attempt}.jsonl"
    with open(raw, "w") as out, tempfile.TemporaryDirectory() as cwd:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=out, stderr=subprocess.STDOUT,
                                cwd=cwd, env=env, start_new_session=True, text=True)
        try:
            proc.communicate(prompt, timeout=CLAUDE_TIMEOUT)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            raise RuntimeError(f"claude timed out after {CLAUDE_TIMEOUT}s")
    init, result, servers = None, None, {}
    for line in raw.read_text().splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") == "system" and e.get("subtype") == "init":
            init = e
            servers = {s["name"]: s["status"] for s in e.get("mcp_servers", [])}
        if e.get("type") == "result":
            result = e
    if init is None:
        raise RuntimeError(f"claude exited {proc.returncode} without starting; see {raw.name}")
    if config.flag("DAYBOOK_REQUIRE_SUBSCRIPTION") and init.get("apiKeySource") != "none":
        raise RuntimeError(f"refusing: claude used apiKeySource={init.get('apiKeySource')}, not the subscription")
    log(day_dir, f"claude model={init.get('model')} auth={init.get('apiKeySource')} "
                 f"gmail={servers.get('claude.ai Gmail')} gcal={servers.get('claude.ai Google Calendar')} "
                 f"todoist={servers.get('todoist')}")
    if not result or result.get("is_error") or not result.get("structured_output"):
        raise RuntimeError(f"claude returned no brief (subtype={result and result.get('subtype')})")
    log(day_dir, f"claude ok turns={result.get('num_turns')} secs={round(result.get('duration_ms', 0) / 1000)}")
    return result["structured_output"], servers


SOURCES = {"Google Calendar": "claude.ai Google Calendar", "Gmail": "claude.ai Gmail",
           "Todoist": "todoist", "Weather": None, "AI news": None}


def enforce_sources(brief, servers, weather=None):
    """gap flags must not depend on the model remembering to report them."""
    have = {s["source"]: s for s in brief.get("source_status", [])}
    weather = weather or {}
    if weather.get("status") == "ok":
        have["Weather"] = {"source": "Weather", "status": "ok", "note": weather["note"]}
        brief["weather_line"] = weather["line"]
    elif weather.get("status") == "off" and not config.setting("DAYBOOK_LOCATION") \
            and (have.get("Weather") or {}).get("status") != "ok":
        have["Weather"] = {"source": "Weather", "status": "off", "note": "no location or forecast source set"}
    for name, server in SOURCES.items():
        state_ = servers.get(server, "missing") if server else None
        if server and state_ == "missing" and name == "Todoist":
            # not every setup has a todoist connector; that is a choice, not a gap
            have[name] = {"source": name, "status": "off", "note": "no Todoist connector"}
        # "pending" at init often connects a moment later, so only hard failures override the model
        elif server and state_ not in ("connected", "pending"):
            have[name] = {"source": name, "status": "unavailable", "note": f"connector {state_}"}
        elif name not in have:
            have[name] = {"source": name, "status": "unavailable", "note": "not reported by the run"}
    brief["source_status"] = [have[n] for n in SOURCES] + [v for k, v in have.items() if k not in SOURCES]
    return brief


# ---------- render ----------

SYNODIC = 29.530588853


def moon_phase(day):
    """age in days, a name, and the lit fraction, at 8 AM local."""
    ref = dt.datetime(2000, 1, 6, 18, 14, tzinfo=dt.timezone.utc)  # a known new moon
    age = ((dt.datetime.combine(day, dt.time(8), config.tz()) - ref).total_seconds() / 86400) % SYNODIC
    names = ["new moon", "waxing crescent", "first quarter", "waxing gibbous", "full moon",
             "waning gibbous", "last quarter", "waning crescent"]
    return age, names[int(age / SYNODIC * 8 + .5) % 8], (1 - math.cos(2 * math.pi * age / SYNODIC)) / 2


def sky_kind(text):
    t = (text or "").lower()
    for kind, pat in (("storm", r"thunder|storm"), ("snow", r"snow|flurr|sleet|\bice\b"),
                      ("rain", r"rain|shower|drizzle"), ("fog", r"fog|haze|smoke|mist"),
                      ("partly", r"partly|mostly sunny|mostly clear|few clouds"),
                      ("cloudy", r"cloud|overcast|gr[ae]y")):
        if re.search(pat, t):
            return kind
    return "clear"


def temps(text):
    m = re.search(r"(-?\d+)\s*°?\s*F?\s*/\s*(-?\d+)", text or "")
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def mix(a, b, t):
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(rgb(a), rgb(b)))


SEASON = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring",
          6: "summer", 7: "summer", 8: "summer", 9: "autumn", 10: "autumn", 11: "autumn"}
# inks per plate: sky top, sky middle, horizon; the sun; hills back to front
PLATES = {
    "autumn": [("persimmon", ["#232d45", "#b0644a", "#f0c88e"], "#fde6b6",
                ["#a07468", "#7b544f", "#583b3c", "#382528", "#1d1315"]),
               ("ochre", ["#272a40", "#a36f40", "#eecf8f"], "#fde9b9",
                ["#98805f", "#745f47", "#544332", "#362b21", "#1c1611"]),
               ("plum", ["#1f1b31", "#7a4566", "#e8a98a"], "#fbe2c4",
                ["#896377", "#664558", "#472f3e", "#2c1d28", "#170f16"])],
    "winter": [("frost", ["#1a2437", "#6c7e9d", "#e6d9cf"], "#fff3e2",
                ["#8c96aa", "#6a7388", "#4a5267", "#2f3549", "#191d2b"]),
               ("rose", ["#21233a", "#897291", "#efccbe"], "#fff0e6",
                ["#94899f", "#70657e", "#4f465f", "#322c41", "#1b1726"])],
    "spring": [("sage", ["#21374a", "#7ea49a", "#f1e2c1"], "#fff4d6",
                ["#86a189", "#658069", "#465f4c", "#2d4133", "#19261d"]),
               ("blossom", ["#29304f", "#c48d9b", "#f5e0c7"], "#fff1dc",
                ["#929f89", "#6e7f68", "#4d5d4a", "#323f30", "#1b231a"])],
    "summer": [("cobalt", ["#153455", "#4e8eb7", "#f4e1a5"], "#fff6cf",
                ["#6e8f76", "#517258", "#395440", "#25382b", "#131f18"]),
               ("wheat", ["#1e344f", "#799eb3", "#f2d69a"], "#fff3c8",
                ["#af985e", "#897648", "#645534", "#423822", "#231d12"])],
}
WEATHER_TINT = {"cloudy": ("#4b5159", "#8e949b", .45), "rain": ("#3f4751", "#69737d", .58),
                "storm": ("#2c323b", "#525a64", .68), "snow": ("#8d97a3", "#cfd5dc", .45),
                "fog": ("#7b7f84", "#d6d2ca", .42)}
X0, X1 = 6 * 60, 22 * 60  # the plate's time axis


def seeded(day, salt):
    return random.Random(int(hashlib.sha256(f"{day.isoformat()}:{salt}".encode()).hexdigest()[:16], 16))


def x_of(minutes, width=1200):
    return (minutes - X0) / (X1 - X0) * width


def plate_inks(day, weather):
    rng = seeded(day, "inks")
    name, sky, sun, hills = rng.choice(PLATES[SEASON[day.month]])
    kind = sky_kind(weather)
    if kind in WEATHER_TINT:
        top, low, t = WEATHER_TINT[kind]
        sky = [mix(sky[0], top, t), mix(sky[1], low, t), mix(sky[2], low, t * .7)]
        hills = [mix(h, low, t * .35) for h in hills]
    hi, _ = temps(weather)
    if hi is not None and hi >= 90:
        sky[2] = mix(sky[2], "#f6ad66", .25)
    elif hi is not None and hi <= 40:
        sky[2] = mix(sky[2], "#d3dce8", .3)
    return name, kind, sky, sun, hills


def hero_svg(day, events, weather="", variant="wide"):
    """the cover plate, a seeded print of the day. the season and forecast pick the inks, the configured
    place's sun times set the sun and its arc, and the near hills rise with each calendar event (x runs 6 AM to 10 PM)."""
    rng = seeded(day, "hero")
    W, H = (1200, 500) if variant == "wide" else (800, 920)
    k = H / 560
    pid = f"p{variant[0]}{day:%y%m%d}"  # unique per plate, even with several on one page
    name, kind, sky, sun_c, hills = plate_inks(day, weather)
    horizon = H * (.64 if variant == "wide" else .6)
    rise, sset = sun_times(day)
    timed = [e for e in events if not e.get("all_day") and hm(e.get("start")) is not None and hm(e.get("end")) is not None]

    def sky_at(t):  # t: 0 top .. 1 horizon
        return mix(sky[0], sky[1], t / .6) if t < .6 else mix(sky[1], sky[2], (t - .6) / .4)

    p = [f'<svg class="plate-art {variant}" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid slice" '
         f'xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Plate for {day.strftime("%A")}: a generated '
         f'{SEASON[day.month]} landscape under a {kind} sky. The near hills rise with today\'s '
         f'{len(timed)} calendar event{"s" if len(timed) != 1 else ""}; the dotted arc is the sun\'s path.">',
         f'<defs><filter id="{pid}g" x="0" y="0" width="100%" height="100%">'
         f'<feTurbulence type="fractalNoise" baseFrequency=".8" numOctaves="3" seed="{rng.randrange(999)}" stitchTiles="stitch"/>'
         '<feColorMatrix type="matrix" values="0 0 0 0 .13  0 0 0 0 .1  0 0 0 0 .08  0 0 0 -1.5 1.05"/></filter>'
         f'<radialGradient id="{pid}v" cx=".5" cy=".42" r=".75"><stop offset=".55" stop-color="#000" stop-opacity="0"/>'
         '<stop offset="1" stop-color="#000" stop-opacity=".38"/></radialGradient>'
         f'<radialGradient id="{pid}s"><stop offset="0" stop-color="{sun_c}" stop-opacity=".75"/>'
         f'<stop offset=".35" stop-color="{sun_c}" stop-opacity=".22"/><stop offset="1" stop-color="{sun_c}" stop-opacity="0"/></radialGradient>']
    for i, c in enumerate(hills):
        p.append(f'<linearGradient id="{pid}h{i}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{mix(c, sky[2], .32 - i * .06)}"/>'
                 f'<stop offset=".55" stop-color="{c}"/><stop offset="1" stop-color="{mix(c, "#000000", .25)}"/></linearGradient>')
    p.append(f'<linearGradient id="{pid}m" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{sky[2]}" stop-opacity="0"/>'
             f'<stop offset="1" stop-color="{sky[2]}" stop-opacity=".42"/></linearGradient></defs>')

    # posterized sky: flat bands of ink with soft wavy edges, like a few passes of a print
    bands = 9
    p.append(f'<rect width="{W}" height="{H}" fill="{sky_at(0)}"/>')
    for i in range(1, bands):
        y0 = horizon * 1.08 * (i / bands) ** .9
        amp, f, ph = rng.uniform(3, 8) * k, rng.uniform(1.2, 2.8), rng.uniform(0, 6.28)
        pts = " L".join(f"{x:.0f},{y0 + amp * math.sin(ph + f * x / W * 6.28):.1f}" for x in [*range(0, W, W // 24), W])
        p.append(f'<path d="M{pts} L{W},{H} L0,{H} Z" fill="{sky_at(i / (bands - 1))}"/>')

    # stars while the top of the sky is still dark
    if sum(rgb(sky[0])) < 190 and kind in ("clear", "partly"):
        for _ in range(int(46 * W / 1200)):
            y = rng.uniform(0, horizon * .42)
            p.append(f'<circle cx="{rng.uniform(0, W):.0f}" cy="{y:.0f}" r="{rng.uniform(.6, 1.7) * k:.1f}" fill="#fff8e8" '
                     f'opacity="{(1 - y / (horizon * .42)) * rng.uniform(.3, .8):.2f}"/>')

    # the moon is up in the western morning sky from full through waning crescent
    age, _, lit = moon_phase(day)
    if 13 <= age <= 26 and kind in ("clear", "partly"):
        mx, my, mr = W * .84, H * .15, 17 * k
        rx = mr * abs(math.cos(2 * math.pi * age / SYNODIC))
        outer, inner = (0, 0 if lit > .5 else 1) if age > SYNODIC / 2 else (1, 1 if lit > .5 else 0)
        p.append(f'<circle cx="{mx:.0f}" cy="{my:.0f}" r="{mr:.1f}" fill="#fff8e8" opacity=".12"/>'
                 f'<path d="M{mx:.1f},{my - mr:.1f} A{mr:.1f},{mr:.1f} 0 0 {outer} {mx:.1f},{my + mr:.1f} '
                 f'A{rx:.1f},{mr:.1f} 0 0 {inner} {mx:.1f},{my - mr:.1f} Z" fill="#fbf3df" opacity=".92"/>')

    # ridge lines first, so the sun can sit behind the far hills
    ridges = []
    for i, c in enumerate(hills):
        base = horizon + (H - horizon) * (i * .2 - .06)
        amp = H * .12 * (1 - i * .16)
        ph, f1, f2 = rng.uniform(0, 6.28), rng.uniform(1.1, 2.4), rng.uniform(3.5, 6.5)
        ys = []
        for j in range(97):
            x = j * W / 96
            y = base - amp * (.6 * math.sin(ph + f1 * j / 96 * 6.28) + .25 * math.sin(ph * 1.7 + f2 * j / 96 * 6.28)
                              + .08 * math.sin(f2 * 3.1 * j / 96 * 6.28) + rng.uniform(-.03, .03))
            if i == len(hills) - 1:
                # each event swells the near hill, longer meetings more; a cluster grows broad, not spiky
                lifts = []
                for e in timed:
                    s, f_ = hm(e["start"]), hm(e["end"])
                    cx, width = x_of((s + f_) / 2, W), max(50 * k, x_of(f_, W) - x_of(s, W))
                    lifts.append((H * .045 + (f_ - s) * H * .0011) * math.exp(-((x - cx) / (width * .78)) ** 2))
                lift = max(lifts) + .22 * (sum(lifts) - max(lifts)) if lifts else 0
                y = base + amp * (.2 + .22 * math.sin(ph + f1 * j / 96 * 6.28)) - min(H * .2, lift)
            ys.append(y)
        ridges.append((base, amp, ys))

    def ridge_y(i, x):
        ys = ridges[i][2]
        j = min(95, max(0, int(x / W * 96)))
        t = x / W * 96 - j
        return ys[j] * (1 - t) + ys[j + 1] * t

    # sun: where it stands at 8 AM, when the brief is read, held just above the far hills
    def arc_y(m):
        return horizon - math.sin(math.pi * (m - rise) / (sset - rise)) * (horizon - H * .17)
    sx = x_of(8 * 60, W)
    sr = 30 * k
    sy = min(arc_y(8 * 60) if rise < 8 * 60 < sset else horizon, ridge_y(0, sx) - sr * .45)
    arc = " L".join(f"{x_of(m, W):.0f},{arc_y(m):.0f}" for m in range(rise, sset + 1, 10))
    if kind not in ("rain", "storm"):
        p.append(f'<path d="M{arc}" fill="none" stroke="#fff6e2" stroke-width="{2.6 * k:.1f}" stroke-linecap="round" '
                 f'stroke-dasharray="0 {11 * k:.0f}" opacity="{.42 if kind in ("clear", "partly") else .25}"/>')
    veil = {"clear": 1, "partly": .9, "fog": .55, "snow": .5, "cloudy": .4}.get(kind, 0)
    if veil:
        p.append(f'<g class="sun" opacity="{veil}"><circle cx="{sx:.0f}" cy="{sy:.0f}" r="{sr * 6:.0f}" fill="url(#{pid}s)"/>')
        for ring in range(1, 8):  # halftone halo
            rr = sr + ring * sr * .42
            n = int(2 * math.pi * rr / (sr * .3))
            dot = sr * .085 * (1 - ring / 9)
            dots = "".join(f'<circle cx="{sx + rr * math.cos(a * 2 * math.pi / n):.1f}" cy="{sy + rr * math.sin(a * 2 * math.pi / n):.1f}" '
                           f'r="{dot:.1f}"/>' for a in range(n))
            p.append(f'<g fill="{sun_c}" opacity="{.5 * (1 - ring / 8):.2f}">{dots}</g>')
        p.append(f'<circle cx="{sx + 3 * k:.0f}" cy="{sy + 2 * k:.0f}" r="{sr:.0f}" fill="#e9774a" opacity=".55"/>'
                 f'<circle cx="{sx:.0f}" cy="{sy:.0f}" r="{sr:.0f}" fill="{sun_c}"/></g>')

    # clouds: flat-bottomed, two inks
    n_clouds = {"partly": 3, "cloudy": 6, "rain": 6, "storm": 7, "snow": 5, "fog": 2}.get(kind, 0)
    for _ in range(n_clouds):
        cx, cy, cw = rng.uniform(-.05, 1.05) * W, rng.uniform(.12, .5) * horizon, rng.uniform(.14, .26) * W
        tone = mix(sky_at(cy / horizon), "#ffffff", .32 if kind in ("partly", "fog", "snow") else .14)
        puffs = "".join(f'<ellipse cx="{cx + (q - 2) * cw * .19:.0f}" cy="{cy - rng.uniform(.2, 1) * cw * .1:.0f}" '
                        f'rx="{cw * rng.uniform(.13, .2):.0f}" ry="{cw * rng.uniform(.08, .13):.0f}"/>' for q in range(5))
        p.append(f'<g fill="{mix(tone, "#000000", .12)}" transform="translate(0 {5 * k:.0f})">{puffs}</g>'
                 f'<g fill="{tone}">{puffs}<rect x="{cx - cw * .5:.0f}" y="{cy - cw * .02:.0f}" width="{cw:.0f}" height="{cw * .06:.0f}" rx="{cw * .03:.0f}"/></g>')

    # hills with mist in each valley and woodcut contour lines under each crest
    for i, (c, (base, amp, ys)) in enumerate(zip(hills, ridges)):
        top = " L".join(f"{j * W / 96:.0f},{y:.1f}" for j, y in enumerate(ys))
        p.append(f'<path d="M0,{H} L{top} L{W},{H} Z" fill="url(#{pid}h{i})"/>')
        for n, dy in enumerate((7, 15, 25) if i else ()):
            line = " L".join(f"{j * W / 96:.0f},{y + dy * k:.1f}" for j, y in enumerate(ys))
            dash = f' stroke-dasharray="{2 * k:.0f} {5 * k:.0f}"' if n == 2 else ""
            p.append(f'<path d="M{line}" fill="none" stroke="{mix(c, sky[2], .35)}" stroke-width="{1.1 * k:.1f}" '
                     f'opacity="{.3 - n * .08:.2f}"{dash}/>')
        if i < len(hills) - 1:
            mist_top = base - amp * .1
            p.append(f'<rect class="mist" x="0" y="{mist_top:.0f}" width="{W}" height="{H - mist_top:.0f}" fill="url(#{pid}m)" '
                     f'opacity="{1.25 if kind == "fog" else .8}"/>')
    # a lamp on the near hill for each event
    for e in timed:
        cx = x_of((hm(e["start"]) + hm(e["end"])) / 2, W)
        if 0 < cx < W:
            ly = ridge_y(len(hills) - 1, cx) + 16 * k
            p.append(f'<circle cx="{cx:.0f}" cy="{ly:.0f}" r="{8 * k:.0f}" fill="{sun_c}" opacity=".14"/>'
                     f'<circle cx="{cx:.0f}" cy="{ly:.0f}" r="{2.2 * k:.1f}" fill="{sun_c}" opacity=".9"/>')

    if kind in ("rain", "storm"):
        p.append(f'<g stroke="#e6edf2" stroke-width="{1.2 * k:.1f}" stroke-linecap="round" opacity=".28">' + "".join(
            f'<path d="M{x:.0f},{y:.0f} l{-6 * k:.0f},{22 * k:.0f}"/>'
            for x, y in ((rng.uniform(0, W * 1.05), rng.uniform(0, H)) for _ in range(int(170 * W / 1200)))) + "</g>")
    if kind == "snow":
        p.append('<g fill="#ffffff" opacity=".6">' + "".join(
            f'<circle cx="{rng.uniform(0, W):.0f}" cy="{rng.uniform(0, H):.0f}" r="{rng.uniform(1, 2.6) * k:.1f}"/>'
            for _ in range(int(150 * W / 1200))) + "</g>")

    # hour marks along the foot of the plate, like a printer's scale
    ticks = []
    for hour in range(7, 22):
        x = x_of(hour * 60, W)
        major = hour % 3 == 0
        ticks.append(f'<path d="M{x:.0f},{H - (16 if major else 10) * k:.0f} V{H - 4 * k:.0f}"/>')
        if major:
            ticks.append(f'<text x="{x:.0f}" y="{H - 21 * k:.0f}" stroke="none">{hour % 12 or 12}</text>')
    p.append(f'<g stroke="#fff6e2" stroke-width="{1.2 * k:.1f}" fill="#fff6e2" opacity=".5" font-family="ui-monospace, Menlo, monospace" '
             f'font-size="{(15 if variant == "wide" else 19) * k / (1 if variant == "wide" else 1.6):.0f}" text-anchor="middle">{"".join(ticks)}</g>')

    # grain and vignette, then the day's name printed crisp on top
    p.append(f'<rect width="{W}" height="{H}" fill="url(#{pid}v)"/>'
             f'<rect width="{W}" height="{H}" filter="url(#{pid}g)" opacity=".55"/>')
    title = day.strftime("%A")
    fs = min(150 if variant == "wide" else 196, W * (.6 if variant == "wide" else .86) / (len(title) * .6))
    ty = H * (.36 if variant == "wide" else .3)
    p.append(f'<text x="{W / 2:.0f}" y="{ty:.0f}" text-anchor="middle" font-family="Fraunces, \'Iowan Old Style\', Georgia, serif" '
             f'font-weight="600" font-size="{fs:.0f}" letter-spacing="{-fs * .012:.1f}" fill="#fbf3e2" class="plate-day">{title}</text></svg>')
    return "".join(p)


def drop_school_tasks(b, ids):
    """todoist tasks that mirror a school folder file never show; the school folder is the source of truth."""
    ids = {str(i) for i in ids or []}
    kept, gone = [], set()
    for t in b.get("todoist_schedule") or []:
        if str(t.get("id", "")) in ids:
            gone.add(norm(t.get("title")))
        else:
            kept.append(t)
    acts = [a for a in b.get("next_actions") or [] if not (a.get("kind") == "task" and norm(a.get("title")) in gone)]
    return dict(b, todoist_schedule=kept, next_actions=acts)


def esc(s):
    return html.escape(str(s or ""))


def esc_code(s):
    # the model sometimes writes `commands`; show them as code instead of literal backticks
    return re.sub(r"`([^`<>]{1,80})`", r"<code>\1</code>", esc(s))


def link(text, url):
    url = safe_url(url)
    return f'<a href="{esc(url)}">{esc(text)}</a>' if url else esc(text)


def linked_sentence(item):
    sentence, phrase, url = item.get("sentence", ""), item.get("link_phrase", ""), safe_url(item.get("url", ""))
    if url and phrase and phrase in sentence:
        a, b = sentence.split(phrase, 1)
        return f'{esc(a)}<a href="{esc(url)}">{esc(phrase)}</a>{esc(b)}'
    return esc(sentence)


def item_list(items, cls=""):
    rows = []
    for it in items:
        rows.append(f'<li class="note"><p class="n-title">{link(it["title"], it.get("url", ""))}</p>'
                    f'<p class="n-body">{linked_sentence(it)}</p></li>')
    return f'<ul class="notes {cls}">{"".join(rows)}</ul>'


def section(title, body, cls="", sid="", fold=None, aside=""):
    """fold=None: always open. "keep" or "phone": a fold button (js); "phone" starts shut on phones. print ignores folds."""
    if not body:
        return ""
    sid = sid or re.sub(r"[^a-z]+", "-", title.lower()).strip("-")
    head = f'<h2>{esc(title)}</h2>' + (f'<span class="sec-aside">{aside}</span>' if aside else "")
    if not fold:
        return f'<section class="sec {cls}" id="{sid}"><div class="sec-head">{head}</div>{body}</section>'
    # a details element would be simpler, but chrome will not split one across printed pages
    return (f'<section class="sec {cls}" id="{sid}" data-fold="{sid}"{" data-fold-phone" if fold == "phone" else ""}>'
            f'<div class="sec-head">{head}<button type="button" class="chev" aria-expanded="true" aria-controls="{sid}-body" '
            f'aria-label="Fold {esc(title)}" hidden></button></div><div class="sec-body" id="{sid}-body">{body}</div></section>')


KIND_LABEL = {"school": "school", "ta": "TA", "research": "research", "project": "project", "pr": "PR",
              "email": "email", "task": "Todoist", "personal": "personal"}
CHECK = '<svg class="ck" viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 8.4l3 3 6-6.6"/></svg>'


def action_rows(items, start=1, day=None):
    rows = []
    for n, a in enumerate(items, start):
        kind = KIND_LABEL.get(a.get("kind"), "")
        meta = [x for x in (a.get("when"), kind if norm(kind) != norm(a.get("source")) else "", a.get("source")) if x]
        key = f'{day.isoformat() if day else ""}:{norm(a.get("title"))[:48]}'
        rows.append(f'<li class="act"><label class="tick"><input type="checkbox" class="done-box" data-key="{esc(key)}" '
                    f'aria-label="Done: {esc(a.get("title"))}"><span class="box" aria-hidden="true"><span class="num">{n}</span>{CHECK}</span></label>'
                    f'<div class="act-body"><p class="act-title">{link(a.get("title"), a.get("url"))}</p>'
                    f'<p class="act-why">{esc(a.get("why"))}</p>'
                    f'<p class="meta">{" &middot; ".join(esc(x) for x in meta)}</p></div></li>')
    return f'<ol class="acts">{"".join(rows)}</ol>'


def ribbon_html(rb, day):
    hours = (rb["hi"] - rb["lo"]) // 60
    track = []
    if rb["daylight"]:
        a, z = rb["daylight"]
        track.append(f'<span class="rb-light" style="left:{a}%;width:{max(0, z - a):.2f}%"></span>')
    for f in rb["free"]:
        label = duration(f["minutes"]) if f["width"] >= 9 else ""
        track.append(f'<span class="rb-free" style="left:{f["left"]}%;width:{f["width"]}%"><i>{label}</i></span>')
    for e in rb["events"]:
        track.append(f'<span class="rb-ev k-{esc(e["kind"])}" style="left:{e["left"]}%;width:{e["width"]}%;--lane:{e["lane"]}" '
                     f'title="{esc(e["title"])}, {pretty(e["start"])} to {pretty(e["end"])}"></span>')
    scale = []
    for t in rb["ticks"]:
        lab = (f"<i>{t['hour'] % 12 or 12}{'a' if t['hour'] < 12 else 'p'}</i>"
               if t["hour"] % (2 if hours <= 14 else 3) == 0 else "")
        edge = " first" if t["left"] == 0 else " last" if t["left"] == 100 else ""
        scale.append(f'<span class="rb-tick{edge}" style="left:{t["left"]}%">{lab}</span>')
    n = len(rb["events"])
    label = (f'Day ribbon from {pretty(clock(rb["lo"]))} to {pretty(clock(rb["hi"] % (24 * 60)))}: {n} event{"s" if n != 1 else ""}, '
             f'{len(rb["free"])} open block{"s" if len(rb["free"]) != 1 else ""}'
             + (f', {rb["lanes"]} lanes where events overlap' if rb["lanes"] > 1 else ""))
    # the page's "now" line reads the zone (and a frozen clock) from here
    frozen = config.now().isoformat(timespec="minutes") if config.frozen() else ""
    return (f'<div class="ribbon" role="img" aria-label="{esc(label)}" style="--lanes:{rb["lanes"]}" '
            f'data-date="{day.isoformat()}" data-lo="{rb["lo"]}" data-hi="{rb["hi"]}" '
            f'data-tz="{esc(config.setting("DAYBOOK_TZ"))}"{f" data-now={chr(34)}{esc(frozen)}{chr(34)}" if frozen else ""}>'
            f'<div class="rb-track">{"".join(track)}<span class="rb-now" hidden></span></div>'
            f'<div class="rb-scale">{"".join(scale)}</div></div>')


def day_rows(events, blocks, clashes):
    rows = []
    timed = [("e", e["start"], e) for e in events if not e["all_day"]] + [("f", f["start"], f) for f in blocks]
    for e in [e for e in events if e["all_day"]]:
        rows.append(f'<li class="slot allday"><span class="t">all day</span><span class="what">{esc(e["title"])}</span></li>')
    clash_at = {c["a"] for c in clashes} | {c["b"] for c in clashes}
    for kind, _, x in sorted(timed, key=lambda r: (r[1], r[0] == "e")):
        if kind == "f":
            rows.append(f'<li class="slot free"><span class="t">{pretty(x["start"])}</span>'
                        f'<span class="what">Open until {pretty(x["end"])} <span class="dur">{duration(x["minutes"])}</span></span></li>')
            continue
        tag = {"ta": "TA", "class": "class", "deadline": "deadline"}.get(x["kind"], "")
        bits = [esc(x["where"])] if x["where"] else []
        if x["source"] == "school":
            bits.append("from the school folder")
        rows.append(f'<li class="slot{" clash" if x["title"] in clash_at else ""}"><span class="t">{pretty(x["start"])}</span>'
                    f'<span class="what"><span class="kd k-{esc(x["kind"] or "other")}" aria-hidden="true"></span>{link(x["title"], x.get("url"))}'
                    f'{f" <em class=tag>{tag}</em>" if tag else ""}'
                    f'<span class="sub">until {pretty(x["end"])}{"; " + "; ".join(bits) if bits else ""}</span></span></li>')
    return f'<ol class="day">{"".join(rows)}</ol>'


def due_line(i, verb="due"):
    late = '<b class="late">overdue</b> ' if i.get("overdue") else ""
    return f'<li><span class="cls">{esc(i["class"])}</span><span class="ttl">{late}{esc(i["title"])}</span><span class="when">{verb} {esc(i["due"])}</span></li>'


def first_sentence(text, cap=150):
    m = re.match(r"(.+?[.!?])(\s|$)", text)
    out = m.group(1) if m else text
    return out if len(out) <= cap else out[:cap].rsplit(" ", 1)[0] + "..."


def school_html(b, school, day):
    if school.get("off"):
        return ""
    if school.get("unreachable"):
        return "<p>The school folder could not be read this morning, so nothing here is checked.</p>"
    parts = []
    ta = [i for i in school["to_grade"] if i.get("kind") == "grading"]
    students = [i for i in school["to_grade"] if i.get("kind") == "students_due"]
    if ta or students or school.get("office_hours"):
        rows = "".join(due_line(i, "grade by") for i in ta)
        rows += "".join(due_line(dict(i, overdue=False), "students submit") for i in students)
        oh = "".join(f'<li><span class="cls">{esc(o["class"])}</span><span class="ttl">Office hours: {esc(first_sentence(o["text"]))}</span></li>'
                     for o in school.get("office_hours", []))
        parts.append(f'<h3>TA duties</h3><ul class="dues">{rows}{oh}</ul>')
    bk = school_buckets(school["due_soon"], day)
    for key, label in (("overdue", "Overdue"), ("now", "Due today or tomorrow"), ("week", "Later this week"),
                       ("later", "Next week")):
        if bk[key]:
            parts.append(f'<h3>{label}</h3><ul class="dues">{"".join(due_line(i) for i in bk[key])}</ul>')
    if not school["due_soon"]:
        parts.append("<p>Nothing due in the next two weeks.</p>")
    if b.get("in_lecture"):
        parts.append('<h3>In lecture</h3><ul class="dues lect">' + "".join(
            f'<li><span class="cls">{esc(l["class"])}</span><span class="ttl">{esc(l["line"])}</span></li>' for l in b["in_lecture"]) + "</ul>")
    dec = school.get("decisions_owed", [])
    if dec:
        newest = dec[-1].split(": ", 1)[-1] if ": " in dec[-1] else dec[-1]
        parts.append(f'<p class="decisions"><b>{len(dec)} decision{"s" if len(dec) > 1 else ""} owed</b> '
                     f'in inbox/decisions.md. Newest: {esc(newest)}.</p>')
    return "".join(parts)


def pr_html(prs):
    if prs is None:
        return "<p>Pull request status could not be checked today (gh failed).</p>"
    rows = []
    for pr in prs:
        bits = [pr["repository"]["nameWithOwner"]]
        if pr.get("isDraft"):
            bits.append("draft")
        if pr.get("reviewDecision"):
            bits.append(pr["reviewDecision"].replace("_", " ").lower())
        if pr.get("checks") and pr["checks"] != "none":
            bits.append(f'checks {pr["checks"]}')
        if pr.get("mergeable") == "CONFLICTING":
            bits.append("merge conflict")
        rows.append({"title": f'#{pr["number"]} {pr["title"]}', "url": pr["url"], "sentence": ", ".join(bits) + "."})
    return item_list(rows) if rows else '<p class="quiet">No open pull requests.</p>'


NEWS_LABEL = {"available": "available now", "announced": "announced", "research": "research",
              "rumor": "unconfirmed", "update": "update"}


def news_html(b, ctx, day):
    items = clean_news(b.get("news"), day, (ctx.get("news") or {}).get("items", []))
    if not items:
        note = b.get("news_note") or ""
        return f'<p class="quiet">No AI news from the last day cleared the bar for this brief.{" " + esc(note) if note else ""}</p>'
    rows = []
    for n in items:
        pub = dt.date.fromisoformat(n["published"][:10])
        rows.append(f'<li class="story"><p class="s-kick"><span class="badge b-{esc(n["status"])}">{NEWS_LABEL[n["status"]]}</span>'
                    f'<span class="s-src">{link(n.get("source_name") or "source", n["url"])} &middot; {pub.strftime("%b %-d")}</span></p>'
                    f'<p class="s-head">{link(n.get("headline"), n["url"])}</p>'
                    f'<p class="s-body">{esc_code(n.get("summary"))}</p>'
                    + (f'<p class="s-why">{esc(n["why"])}</p>' if n.get("why") else "") + "</li>")
    return f'<ol class="stories">{"".join(rows)}</ol>'


def projects_html(b):
    rows = []
    for p in b.get("projects") or []:
        owed = f'<p class="n-owed"><b>Waiting on you</b> {esc(p["owed"])}</p>' if p.get("owed") else ""
        rows.append(f'<li class="note"><p class="n-title">{esc(p.get("title"))}</p>'
                    f'<p class="n-body">{esc(p.get("outcome"))}</p>{owed}'
                    + (f'<p class="meta">{esc(p["source"])}</p>' if p.get("source") else "") + "</li>")
    return f'<ul class="notes">{"".join(rows)}</ul>' if rows else ""


def load_puzzles():
    from . import puzzles
    return puzzles


GAME_TABS = {"ladder": "Rungs", "crossword": "Mini", "word": "Hunch", "crowns": "Crowns", "sunmoon": "Day & Night",
             "weekly": "Weekly"}


def weekly_file(pz, day):
    return briefs() / pz.week_friday(day).isoformat() / "weekly.json"


def weekly_clues(pz, day):
    """the week's model clues, saved on its friday. missing or odd means bank clues"""
    try:
        clues = json.loads(weekly_file(pz, day).read_text()).get("clues")
        return clues if isinstance(clues, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def weekly_ask(day):
    """the week's answers when its clues are not saved yet (fridays, or a later day if friday failed)"""
    try:
        pz = load_puzzles()
        return None if weekly_file(pz, day).exists() else pz.weekly_entries(day)
    except Exception:  # a puzzle bug must never cost the brief
        return None


def weekly_save(day, entries, got, day_dir):
    """keep only clean model clues; save them for the week if at least half came through"""
    if not entries:
        return
    pz = load_puzzles()
    clues = {x.get("answer"): x.get("clue") for x in (got or []) if isinstance(x, dict)}
    clean = pz.clean_weekly_clues(entries, clues)
    log(day_dir, f"weekly clues: {len(clean)} of {len(entries)} clean")
    if len(clean) * 2 < len(entries):
        return
    f = weekly_file(pz, day)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"week": pz.week_friday(day).isoformat(), "written": day.isoformat(),
                             "clues": clean, "entries": len(entries)}, indent=1, ensure_ascii=False))


def play_html(day, web_url, fit="full"):
    """fit: "full" prints the weekly in full on fridays, "short" prints it as one line,
    "none" keeps every puzzle off paper (a pointer instead). render steps down only to fit the page cap"""
    root = briefs()
    try:
        pz = load_puzzles()
        today_p = pz.all_for_day(day)
        wk = pz.weekly_for(day, weekly_clues(pz, day))
        friday = day.weekday() == 4
        full = friday and fit == "full"
        panels = [(p["kind"], pz.render(p)) for p in today_p] + [("weekly", pz.render_weekly(wk, print_full=full))]
    except Exception as e:  # a puzzle bug must never cost the brief
        return f'<p class="quiet">Puzzles could not be built today ({esc(type(e).__name__)}).</p>', []
    where = (f'<p class="play-link print-only">Play these with hints and checking at {link(web_url, web_url)}.</p>'
             if web_url else "")
    picks = "".join(f'<button type="button" class="pz-pick" data-game="{k}" aria-pressed="false">{esc(GAME_TABS[k])}</button>'
                    for k, _ in panels)
    body = "".join(f'<div class="puzzle puzzle-{k}{"" if k != "weekly" or full else " wk-short"}" data-game="{k}">{html_}</div>'
                   for k, html_ in panels)
    if fit == "none":
        where += '<p class="print-only">Today\'s puzzles did not fit on paper; they are on the page.</p>'
    ans = ""
    try:  # answers only for puzzles that were actually given, as saved that day
        prev = json.loads((root / (day - dt.timedelta(days=1)).isoformat() / "puzzles.json").read_text())
        ans = ('<h3>Yesterday\'s answers</h3><ul>' + "".join(
            f'<li><b>{esc(a["title"])}:</b> {esc(a["answer_text"])}</li>' for a in prev) + "</ul>")
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        shown = any('data-game="weekly"' in (root / (day - dt.timedelta(days=i)).isoformat() / "brief.html")
                    .read_text(errors="replace") for i in range(1, 8)
                    if (root / (day - dt.timedelta(days=i)).isoformat() / "brief.html").exists())
        if friday and shown:  # last week's crossword ends today, if it was ever shown
            last = pz.weekly_answers_for(day)
            ans += f'<h3>Last week\'s crossword</h3><p class="wk-ans">{esc(last["answer_text"])}</p>'
    except Exception:  # a puzzle bug must never cost the brief
        pass
    ans_html = f'<div class="answers">{ans}</div>' if ans else ""
    return (where + f'<div class="pz-games{" print-skip" if fit == "none" else ""}"><div class="pz-picker" role="group" aria-label="Pick a game">{picks}</div>'
            f'<div class="puzzles pz-set" data-puzzles="ok">{body}</div></div>' + ans_html,
            [p["title"] for p in today_p] + [wk["title"]])


def source_rows(b, ctx):
    """(name, status, note, as of). an adapter that is not set up says "off", never "unavailable"."""
    gathered = ctx.get("gathered_at", "")
    asof = gathered[11:16] if len(gathered) > 15 else ""
    off = set(ctx.get("off") or [])
    rows = []
    school = ctx["school"]
    if school.get("off") or "school" in off:
        rows.append(("School folder", "off", "no school folder set", ""))
    else:
        rows.append(("School folder", "unavailable" if school.get("unreachable") else "ok",
                     f'{len(school.get("due_soon", []))} due soon, {len(school.get("to_grade", []))} TA items', asof))
    if "prs" in off:
        rows.append(("GitHub", "off", "gh is not set up", ""))
    else:
        rows.append(("GitHub", "unavailable" if ctx.get("prs") is None else "ok",
                     "gh failed" if ctx.get("prs") is None else f'{len(ctx["prs"])} open PRs', asof))
    pj = ctx.get("projects") or {}
    if "reports" in off:
        rows.append(("Session reports", "off", "no sessions folder set", ""))
    else:
        rows.append(("Session reports", "ok", f'{len(pj.get("reports", []))} updated in the last {LOOKBACK_HOURS}h', asof))
    if "git" in off:
        rows.append(("Git activity", "off", "no projects folder set", ""))
    nw = ctx.get("news")
    if "news" in off or (nw or {}).get("status") == "off":
        rows.append(("News feeds", "off", "no feeds file set", ""))
    elif nw:
        rows.append(("News feeds", "ok" if nw["feeds_ok"] else "unavailable",
                     f'{nw["feeds_ok"]} of {nw["feeds"]} feeds read, {len(nw["items"])} recent items', asof))
    mk = ctx.get("marks") or {}
    if mk.get("status") in ("ok", "unavailable"):  # no file yet means the board is not running, not a gap
        rows.append(("Board marks", mk["status"], mk.get("note", ""), asof))
    for s in b.get("source_status", []):
        rows.append((s["source"], s["status"], s.get("note", ""), s.get("as_of", "") or asof))
    o = ctx.get("mail") or {"status": "off", "note": "no second mailbox set"}
    rows.append(("Second mailbox", o["status"].replace("_", " "), o.get("note", ""), o.get("fetched_at", "")[11:16]))
    return rows


def hourly_html(wx):
    """a few forecast hours under movement, from the code-read forecast."""
    hours = [h for h in (wx or {}).get("hourly", []) if h["h"] in (7, 10, 13, 16, 19)]
    if not hours:
        return ""
    cells = "".join(f'<li><span class="hh">{h["h"] % 12 or 12} {"AM" if h["h"] < 12 else "PM"}</span>'
                    f'<span class="ht">{h["t"]}&deg;</span><span class="hp">{(str(h["pop"]) + "% rain") if h.get("pop", 0) >= 20 else esc(h.get("sky", ""))}</span></li>'
                    for h in hours)
    return f'<ul class="hours" aria-label="Hourly forecast">{cells}</ul>'


DEFAULT_COLOPHON = ("Written by a read-only model run from your calendar, mail, tasks and the folders you set up. "
                    "Nothing was sent or changed.")


def edition(day):
    first = config.first_edition()
    return (day - first).days + 1 if first and day >= first else None


def render_html(b, ctx, day, web_url="", fit="full", pdf=True):
    ctx = scrub_dashes(ctx)
    ctx.setdefault("mail", ctx.get("outlook"))  # older contexts
    school, prs = ctx["school"], ctx["prs"]
    off = set(ctx.get("off") or [])
    b = drop_school_tasks(b, school.get("todoist_task_ids"))
    font = base64.b64encode((ROOT / "assets" / "fonts" / "fraunces-latin-600-normal.woff2").read_bytes()).decode()
    events = merge_day(b.get("events"), school.get("class_meetings"))
    blocks, clashes = free_blocks(events), conflicts(events)
    no = edition(day)
    today_acts, week_acts = clean_actions(b.get("next_actions"))
    wx = ctx.get("weather") or {}
    weather = wx.get("line") if wx.get("status") == "ok" else b.get("weather_line", "")
    rise, sset = sun_times(day)
    _, moon, _ = moon_phase(day)
    timed = [e for e in events if not e["all_day"]]
    shape = day_class(events)
    title = config.setting("DAYBOOK_BRIEF_TITLE")
    place = config.setting("DAYBOOK_LOCATION")

    alm = [f'<time datetime="{day.isoformat()}"><em>{day.strftime("%A")}</em>, {day.strftime("%B %-d, %Y")}</time>']
    if place:
        alm.append(esc(place))
    if weather:
        alm.append(esc(weather))
    alm += [f"Sunrise {pretty(clock(rise))}", f"Sunset {pretty(clock(sset))}", moon.capitalize()]
    p = ['<div class="progress" aria-hidden="true"></div>',
         '<header class="mast"><div class="mast-in">'
         f'<p class="mast-top"><span class="brand">{esc(title)}</span>{f"<span class=no>No. {no}</span>" if no else ""}</p>'
         f'<p class="almanac">{"<span class=dot aria-hidden=true></span>".join(f"<span>{x}</span>" for x in alm)}</p></div></header>',
         '<main class="page">',
         f'<figure class="plate">{hero_svg(day, events, weather, "wide")}{hero_svg(day, events, weather, "tall")}'
         f'<figcaption>Plate{f" {no}" if no else ""}, {SEASON[day.month]}. Hours run 6 AM to 10 PM across the foot; each meeting '
         f'raises the near hill and lights a lamp. The sun stands where it will at 8 AM.</figcaption></figure>',
         f'<div class="cover"><h1 class="deck">{esc(b.get("headline"))}</h1>']
    if b.get("opening"):
        p.append(f'<p class="lede">{esc(b["opening"])}</p>')
    play, titles = play_html(day, web_url, fit)
    due_week = len([i for i in school.get("due_soon", []) if not i.get("overdue")
                    and dt.datetime.fromisoformat(i["sort"]).date() <= day + dt.timedelta(days=6)])
    stats = [(duration(booked_minutes(events)) if timed else "0", "booked"),
             (duration(sum(x["minutes"] for x in blocks)), "open"),
             (str(due_week), "due this week"),
             (str(len(clashes)), "overlap" if len(clashes) == 1 else "overlaps")]
    p.append("</div>")
    # stats and the section list share a rail: under the cover on a phone, a sticky side column on desktop
    stats_html = (f'<div class="stats" role="group" aria-label="The day in numbers"><p class="shape">'
                  f'{SHAPE[shape]}</p><dl>'
                  + "".join(f'<div><dt>{esc(l)}</dt><dd>{esc(v)}</dd></div>' for v, l in stats) + "</dl></div>")

    secs = []
    f = b.get("focus") or {}
    if f.get("title"):
        meta = " &middot; ".join(esc(x) for x in (f.get("source"),) if x)
        when = f'<p class="f-when"><span aria-hidden="true">&#9702;</span> {esc(f["when"])}</p>' if f.get("when") else ""
        secs.append(("focus", "The one thing",
                     f'<section class="sec focus" id="focus"><h2>The one thing</h2><p class="f-title">{esc(f["title"])}</p>'
                     f'<p class="f-why">{esc(f.get("why"))}</p>{when}{f"<p class=meta>{meta}</p>" if meta else ""}</section>'))

    nxt = ""
    if today_acts:
        nxt += f'<h3>Today</h3>{action_rows(today_acts, 1, day)}'
    if week_acts:
        nxt += f'<h3>Coming up</h3>{action_rows(week_acts, len(today_acts) + 1, day)}'
    secs.append(("next", "Next up", section("Next up", nxt, "next", "next",
                                             aside=f"{len(today_acts) + len(week_acts)} actions" if nxt else "")))

    day_body = ribbon_html(ribbon(events, blocks, day), day) if timed else ""
    day_body += day_rows(events, blocks, clashes) if events or blocks else ""
    if clashes:
        day_body += "".join(f'<p class="clash-note">{esc(c["a"])} and {esc(c["b"])} overlap by {c["minutes"]} minutes '
                            f'at {pretty(c["at"])}.</p>' for c in clashes)
    for e in [e for e in events if e.get("detail")][:2]:
        when = f'{pretty(e["start"])} to {pretty(e["end"])}' if not e["all_day"] else "all day"
        day_body += (f'<div class="detail"><p class="d-kick">Before it starts</p><p class="d-title">{esc(e["title"])}<span>{when}</span></p>'
                     f'<p>{esc(e["detail"])}</p></div>')
    if b.get("tomorrow"):
        day_body += f'<p class="tomorrow"><em>Tomorrow</em> {esc(b["tomorrow"])}</p>'
    if not events:
        day_body = '<p class="quiet">Nothing on the calendar today.</p>' + day_body
    secs.append(("your-day", "Your day", section("Your day", day_body, "yourday", "your-day",
                                                 aside=f"{len(timed)} on the calendar")))

    inbox = ""
    for name, key in (("Needs attention", "needs_attention"), ("Resolved", "resolved")):
        if b.get(key):
            inbox += f"<h3>{name}</h3>{item_list(b[key], 'attn' if key == 'needs_attention' else 'closed')}"
    o = ctx.get("mail") or {}
    # when the model reads the second mailbox it files it like gmail; otherwise code lists it
    if o.get("status") == "ok" and o.get("items") and not o.get("send_to_model"):
        inbox += "<h3>Other mail</h3>" + item_list(
            [{"title": i["title"] or "(no subject)", "url": "",
              "sentence": "; ".join(x for x in (i["from"], i["due"] and f"due {i['due']}", i["summary"]) if x)}
             for i in o["items"]])
    secs.append(("inbox", "Inbox", section("Inbox", inbox or '<p class="quiet">Nothing in email needs you this morning.</p>',
                                           "inbox", "inbox", "keep")))
    if not school.get("off"):
        secs.append(("school", "School", section("School", school_html(b, school, day), "school", "school", "keep")))
    secs.append(("projects", "Projects", section("Projects and sessions", projects_html(b), "projects", "projects", "keep")))
    if "prs" not in off:
        secs.append(("prs", "PRs", section("Open PRs", pr_html(prs), "prs", "prs", "keep")))
    if b.get("todoist_schedule"):
        secs.append(("todoist", "Todoist", section("Todoist & Schedule", item_list(
            [dict(t, url="", link_phrase="") for t in b["todoist_schedule"]]), "todoist", "todoist", "keep")))
    if b.get("movement"):
        secs.append(("movement", "Movement", section("Movement", f'<p class="move">{esc(b["movement"])}</p>{hourly_html(wx)}',
                                                     "movement", "movement", "keep")))
    secs.append(("news", "AI news", section("AI news", news_html(b, ctx, day), "news", "news", "keep")))
    secs.append(("play", "Play", section("Play", play, "play", "play", "keep",
                                         aside=f"{len(titles) - 1} daily games and the Weekly" if titles else "")))

    srcs = "".join(f'<li><span class="src-n">{esc(n)}</span><span class="st st-{esc(s.split()[0])}">{esc(s)}</span>'
                   f'<span class="src-note">{esc(t)}{(" <span class=asof>" + esc(a) + "</span>") if a else ""}</span></li>'
                   for n, s, t, a in source_rows(b, ctx))
    pdf_link = f' <a class="screen-only" href="morning-brief-{day.isoformat()}.pdf">PDF version</a>' if pdf else ""
    colophon = f'<p class="colophon">{esc(config.setting("DAYBOOK_COLOPHON") or DEFAULT_COLOPHON)}{pdf_link}</p>'
    secs.append(("sources", "Sources", section("Sources", f'<ul class="srcs">{srcs}</ul>{colophon}', "sources", "sources", "phone")))

    secs = [(sid, label, html_) for sid, label, html_ in secs if html_]
    nav = "".join(f'<li><a href="#{sid}">{esc(label)}</a></li>' for sid, label, _ in secs if sid != "focus")
    p.append(f'<aside class="rail">{stats_html}<nav class="contents" aria-label="Sections"><ol>{nav}</ol></nav></aside>')
    p += [h for _, _, h in secs]
    p.append("</main>")

    css = (TEMPLATES / "brief.css").read_text()
    js = (TEMPLATES / "brief.js").read_text() if (TEMPLATES / "brief.js").exists() else ""
    play_css = (TEMPLATES / "play.css").read_text() if (TEMPLATES / "play.css").exists() else ""
    play_js = (TEMPLATES / "play.js").read_text() if (TEMPLATES / "play.js").exists() else ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
            f'<meta name="color-scheme" content="light dark">'
            f'<title>{esc(title)}, {day.strftime("%A %B %-d")}</title>'
            f'<style>@font-face{{font-family:"Fraunces";font-weight:600;src:url(data:font/woff2;base64,{font}) format("woff2");}}'
            f"{play_css}{css}</style></head><body>{''.join(p)}"
            + (f"<script>{play_js}</script>" if play_js else "") + (f"<script>{js}</script>" if js else "") + "</body></html>")


# ---------- pdf: only when chrome is around ----------

CHROME_PATHS = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Chromium.app/Contents/MacOS/Chromium",
                "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium",
                "/usr/bin/chromium-browser", "/snap/bin/chromium"]


def find_chrome():
    c = config.setting("DAYBOOK_CHROME")
    if c:
        return shutil.which(c) or (c if Path(c).is_file() else None)
    return next((p for p in CHROME_PATHS if Path(p).is_file()), None)


def html_to_pdf(html_file, pdf_file, chrome=None):
    chrome = chrome or find_chrome()
    # headless chrome on macos writes the pdf and then often never exits, so watch its log
    with tempfile.TemporaryDirectory() as prof:
        out = Path(prof) / "chrome.log"
        cmd = [str(chrome), "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
               f"--user-data-dir={prof}/profile", "--no-pdf-header-footer", f"--print-to-pdf={pdf_file}",
               html_file.as_uri()]
        with open(out, "w") as fh:
            proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, start_new_session=True)
        done = False
        end = time.monotonic() + 120
        while time.monotonic() < end:
            if "bytes written to file" in out.read_text(errors="replace") or proc.poll() is not None:
                done = True
                break
            time.sleep(0.5)
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
    if not done:
        raise RuntimeError("chrome pdf render timed out")
    if not pdf_file.exists() or pdf_file.stat().st_size < 2000:
        raise RuntimeError("chrome produced no pdf")


def can_validate():
    """the pdf text check needs macOS pdfkit and swiftc."""
    return platform.system() == "Darwin" and bool(shutil.which("swiftc"))


def pdfcheck_bin():
    src = ROOT / "tools" / "pdfcheck.swift"
    out = state() / "pdfcheck"
    if not out.exists() or out.stat().st_mtime < src.stat().st_mtime:
        state().mkdir(parents=True, exist_ok=True)
        subprocess.run([shutil.which("swiftc"), "-O", str(src), "-o", str(out)], check=True,
                       capture_output=True, timeout=300)
    return out


class PageCount(RuntimeError):
    pass


def validate_pdf(pdf_file, brief, day, school=True):
    r = subprocess.run([str(pdfcheck_bin()), str(pdf_file)], capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise RuntimeError(f"pdf unreadable: {r.stderr.strip()}")
    info = json.loads(r.stdout)
    text = re.sub(r"\s+", " ", info["text"])
    # pdfkit splits italic glyph runs ("Y our day"), so compare without whitespace
    flat = re.sub(r"\s+", "", text).upper()
    want = [day.strftime("%B %-d, %Y").upper(), "YOUR DAY", "PLAY", "SOURCES"]
    want += ["SCHOOL"] if school else []
    want += ["NEEDS ATTENTION"] if brief.get("needs_attention") else []
    want += ["MOVEMENT"] if brief.get("movement") else []
    missing = [w for w in want if re.sub(r"\s+", "", w) not in flat]
    headline_start = re.sub(r"\s+", "", brief.get("headline") or "")[:20].upper()
    if headline_start not in flat:
        missing.append("headline")
    if "\u2014" in text:
        missing.append("no em-dash rule")
    if not 1 <= info["pages"] <= 7:
        raise PageCount(f"pdf has {info['pages']} pages")
    if missing:
        raise RuntimeError(f"pdf text check failed: {', '.join(missing)}")
    return info["pages"], len(text)


# ---------- commands ----------

class Lock:
    def __init__(self, day):
        state().mkdir(parents=True, exist_ok=True)
        self.f = open(state() / f"generate-{day.isoformat()}.lock", "w")

    def acquire(self, wait):
        end = time.monotonic() + wait
        while True:
            try:
                fcntl.flock(self.f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except BlockingIOError:
                if time.monotonic() >= end:
                    return False
                time.sleep(10)


def gather(day, day_dir):
    """what code reads before the model runs. each adapter is off when its setting is empty."""
    off = []
    try:
        school = school_context(day)
    except OSError as e:
        log(day_dir, f"school folder unreadable: {e}")
        school = dict(SCHOOL_OFF, unreachable=True)
    if school.get("off"):
        off.append("school")
    now = config.now()
    if not config.setting("DAYBOOK_SESSIONS"):
        off.append("reports")
    if not config.setting("DAYBOOK_PROJECTS"):
        off.append("git")
    prs = None
    if config.setting("DAYBOOK_GH"):
        prs = open_prs()
    else:
        off.append("prs")
    projects = {"reports": session_reports(now), "sessions": session_list(), "git": git_activity(now)}
    ctx = {"school": school, "prs": prs, "projects": projects, "mail": mail_context(),
           "news": news_candidates(now), "weather": weather_context(day), "marks": load_marks(day),
           "gathered_at": now.isoformat(timespec="seconds")}
    off += [k for k in ("news", "weather", "mail") if ctx[k].get("status") == "off"]
    ctx["off"] = off
    return scrub_dashes(ctx)


def generate(day, force=False, lock_wait=0):
    day_dir = briefs() / day.isoformat()
    lock = Lock(day)
    if not lock.acquire(lock_wait):
        raise RuntimeError("another generation for this date is still running")
    if (day_dir / "brief.html").exists() and (day_dir / "meta.json").exists() and not force:
        return day_dir / "brief.html"
    day_dir.mkdir(parents=True, exist_ok=True)
    log(day_dir, f"generate start date={day}")
    ctx = gather(day, day_dir)
    school = ctx["school"]
    log(day_dir, f"context: due={len(school['due_soon'])} grade={len(school['to_grade'])} "
                 f"lectures={len(school['recent_lectures'])} prs={'off' if 'prs' in ctx['off'] else 'gh failed' if ctx['prs'] is None else len(ctx['prs'])} "
                 f"reports={len(ctx['projects']['reports'])} repos={len(ctx['projects']['git'])} mail={ctx['mail']['status']} "
                 f"news={len(ctx['news']['items'])} from {ctx['news']['feeds_ok']}/{ctx['news']['feeds']} feeds "
                 f"weather={ctx['weather']['status']} marks={ctx['marks']['status']} off={','.join(ctx['off']) or 'none'}")
    (day_dir / "context.json").write_text(json.dumps(ctx, indent=1))
    weekly = weekly_ask(day)
    prompt = build_prompt(day, ctx, weekly)
    brief, err = None, None
    for attempt in range(1, CLAUDE_ATTEMPTS + 1):
        try:
            brief, servers = run_claude(day_dir, prompt, attempt)
            break
        except Exception as e:  # retry once, then give up
            err = e
            log(day_dir, f"attempt {attempt} failed: {e}")
            if "refusing" in str(e):
                break
            time.sleep(30)
    if brief is None:
        raise RuntimeError(f"brief generation failed: {err}")
    brief = scrub_dashes(enforce_sources(brief, servers, ctx.get("weather")))
    marks = ctx["marks"]["items"]
    brief, dropped = drop_marked(brief, marks)
    if dropped:
        log(day_dir, f"marks dropped {len(dropped)}: {' | '.join(map(str, dropped))[:300]}")
    if norm((brief.get("focus") or {}).get("title")) in {m["norm"] for m in marks if m["norm"]}:
        log(day_dir, "focus matches a board mark; left as is")
    brief["next_actions"] = [dict(a, handoff=clean_handoff(a.get("handoff"))) for a in brief.get("next_actions") or []]
    # code knows the day's shape better than the model: it sees the class meetings the model never adds
    brief["day_class"] = day_class(merge_day(brief.get("events"), school.get("class_meetings")))
    weekly_save(day, weekly, brief.pop("weekly_clues", None), day_dir)
    (day_dir / "brief.json").write_text(json.dumps(brief, indent=1, ensure_ascii=False))
    return render(day, brief, ctx)


def render(day, brief, ctx):
    """brief.html always; the pdf only when chrome is found. no chrome is never a failure."""
    day_dir = briefs() / day.isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)
    pdf = pdf_path(day)
    html_file = day_dir / "brief.html"
    url = web_url(day) if web_up() else ""
    chrome = find_chrome()
    school = not ctx["school"].get("off")
    pages, chars, made = None, None, False
    note = ""
    if not chrome:
        page = render_html(brief, ctx, day, url, "full", pdf=False)
        html_file.write_text(page)
        note = "pdf skipped: no Chrome or Chromium found (set DAYBOOK_CHROME)"
    else:
        check = can_validate()
        tmp = day_dir / "render.pdf"
        # puzzles step down on paper until the pdf fits; the screen page is the same in every mode
        for fit in ("full", "short", "none"):
            page = render_html(brief, ctx, day, url, fit)
            html_file.write_text(page)
            tmp.unlink(missing_ok=True)
            try:
                html_to_pdf(html_file, tmp, chrome)
            except RuntimeError as e:
                note = f"pdf failed: {e}"
                break
            if not check:
                made, note = True, "pdf not checked: the text check needs macOS and swiftc"
                break
            try:
                pages, chars = validate_pdf(tmp, brief, day, school)
                made = True
                break
            except PageCount as e:
                if fit == "none":
                    raise
                log(day_dir, f"{e} with puzzles printed {fit}; trying less")
        if made:
            tmp.replace(pdf)
        else:
            tmp.unlink(missing_ok=True)
            # the page still links a pdf that is not there; draw it again without the link
            page = render_html(brief, ctx, day, url, "full", pdf=False)
            html_file.write_text(page)
    if 'data-puzzles="ok"' in page:  # tomorrow prints these answers
        (day_dir / "puzzles.json").write_text(json.dumps(load_puzzles().answers_for(day), indent=1))
    # a thin news day is not a gap worth a caption; a dead news source is. "off" is never a gap
    gaps = [s["source"] for s in brief.get("source_status") or []
            if s["status"] == "unavailable" or (s["status"] == "partial" and s["source"] != "AI news")]
    off = set(ctx.get("off") or [])
    if ctx["prs"] is None and "prs" not in off:
        gaps.append("GitHub")
    if ctx["school"].get("unreachable"):
        gaps.append("School folder")
    meta = {"date": day.isoformat(), "html": str(html_file), "pdf": str(pdf) if made else "", "pages": pages,
            "text_chars": chars, "pdf_note": note, "source_gaps": gaps,
            "generated_at": dt.datetime.now(config.tz()).isoformat(timespec="seconds")}
    (day_dir / "meta.json").write_text(json.dumps(meta, indent=1))
    log(day_dir, f"render ok pdf={'yes' if made else 'no'} pages={pages} gaps={gaps or 'none'}"
                 + (f" ({note})" if note else ""))
    return pdf if made else html_file


# ---------- web: serve each date's page ----------

CSP = ("default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; "
       "font-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


def web_base():
    return config.brief_web().rstrip("/")


def web_url(day):
    return f"{web_base()}/{day.isoformat()}/"


def latest_date():
    root = briefs()
    days = sorted(d.name for d in root.glob("????-??-??") if (d / "brief.html").exists())
    return days[-1] if days else None


def host_ok(host):
    """the board's rule: an ip, localhost, a bare name, or a name in DAYBOOK_ALLOWED_HOSTS. anything else may be dns rebinding."""
    from .board.server import host_ok as board_host_ok
    return board_host_ok(host)


def make_server(host=None, port=None):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    host = host or config.setting("DAYBOOK_HOST")
    port = int(config.setting("DAYBOOK_BRIEF_PORT") if port is None else port)

    class Handler(BaseHTTPRequestHandler):
        def send(self, code, body=b"", ctype="text/plain; charset=utf-8", extra=None):
            self.send_response(code)
            for k, v in {"Content-Type": ctype, "Content-Length": str(len(body)), "Cache-Control": "no-cache",
                         "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                         "Content-Security-Policy": CSP, **(extra or {})}.items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_GET(self):
            if not host_ok(self.headers.get("Host")):
                return self.send(421, b"misdirected request")
            path = self.path.split("?", 1)[0]
            if path == "/health":
                return self.send(200, json.dumps({"ok": True, "latest": latest_date()}).encode(), "application/json")
            if path == "/":
                latest = latest_date()
                return self.send(302, extra={"Location": f"/{latest}/"}) if latest else self.send(404, b"no briefs yet")
            # only two shapes exist: /D/ and /D/morning-brief-D.pdf
            m = re.fullmatch(r"/(\d{4}-\d{2}-\d{2})/(morning-brief-\1\.pdf)?", path)
            if m:
                f = briefs() / m.group(1) / (m.group(2) or "brief.html")
                if f.is_file():
                    ctype = "application/pdf" if m.group(2) else "text/html; charset=utf-8"
                    return self.send(200, f.read_bytes(), ctype)
            self.send(404, b"not found")

        do_HEAD = do_GET

        def log_message(self, fmt, *args):
            print(f"{dt.datetime.now(config.tz()).isoformat(timespec='seconds')} {self.address_string()} {fmt % args}",
                  file=sys.stderr)

    return ThreadingHTTPServer((host, port), Handler)


def web_up():
    import urllib.request
    try:
        with urllib.request.urlopen(f"{web_base()}/health", timeout=3) as r:
            return r.status == 200
    except (OSError, ValueError):
        return False


def web_live(day):
    """the page for this date answers right now."""
    import urllib.request
    try:
        with urllib.request.urlopen(web_url(day), timeout=4) as r:
            return r.status == 200
    except (OSError, ValueError):
        return False


def deliver(day, force=False):
    """stdout is what a messenger sends. empty stdout = nothing sent. once per date unless --force."""
    day_dir = briefs() / day.isoformat()
    marker = day_dir / "delivered.json"
    if marker.exists() and not force:
        log(day_dir, "deliver skipped: already handed off for this date")
        return ""
    if not (day_dir / "meta.json").exists():
        # waits for a running generate job, else runs one itself
        generate(day, lock_wait=LOCK_WAIT)
    meta = json.loads((day_dir / "meta.json").read_text())
    pdf = pdf_path(day)
    marker.write_text(json.dumps({"handed_off_at": dt.datetime.now(config.tz()).isoformat(timespec="seconds"),
                                  "pdf": str(pdf) if pdf.exists() else ""}))
    caption = f"{config.setting('DAYBOOK_BRIEF_TITLE')} for {day.strftime('%A, %B %-d')}."
    if meta.get("source_gaps"):
        caption += " Not fully checked: " + ", ".join(meta["source_gaps"]) + "."
    # the hosted page when it is being served, else the pdf, else the local page
    if web_live(day):
        log(day_dir, f"deliver: link handed off ({web_url(day)})")
        return f"{caption}\n{web_url(day)}"
    if pdf.exists():
        log(day_dir, "deliver: web page not reachable, pdf handed off")
        return f"{caption}\nMEDIA:{pdf}"
    log(day_dir, "deliver: no web page and no pdf, local page handed off")
    return f"{caption}\n{(day_dir / 'brief.html').as_uri()}"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="daybook brief")
    ap.add_argument("cmd", choices=["generate", "render", "deliver", "status", "serve"])
    ap.add_argument("--host", default=None)
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--date", type=dt.date.fromisoformat, default=None)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    day = a.date or today()
    d = briefs() / day.isoformat()
    if a.cmd == "status":
        print(json.dumps({"date": day.isoformat(), "html": (d / "brief.html").exists(), "pdf": pdf_path(day).exists(),
                          "meta": read_json(d / "meta.json"), "delivered": (d / "delivered.json").exists()}, indent=1))
        return 0
    if a.cmd == "serve":
        srv = make_server(a.host, a.port)
        print(f"serving {briefs()} on http://{srv.server_address[0]}:{srv.server_address[1]}", file=sys.stderr)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
        return 0
    if a.cmd == "render":
        print(render(day, json.loads((d / "brief.json").read_text()), json.loads((d / "context.json").read_text())))
        return 0
    if a.cmd == "generate":
        print(generate(day, a.force))
        return 0
    out = deliver(day, a.force)
    if out:
        print(out)
    return 0
