# todoist sync for marks: close on done, reopen on undo. server side only; the page makes no outside requests.
# off until TODOIST_API_TOKEN is set. api v1: GET /tasks/{id}, GET /tasks/filter?query=, POST /tasks/{id}/close and /reopen
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from ..common import norm
from ..config import setting

API = "https://api.todoist.com/api/v1"
TIMEOUT = 8
FILTER = "today | overdue"
MAX_PAGES = 5
URL_ID = re.compile(r"todoist\.com/[^\s\"']*?(?:task[s]?/(?:[a-z0-9-]*-)?|showTask\?id=|[?&]id=)([A-Za-z0-9]{6,})")


class Unsure(Exception):
    """no single todoist task to touch"""


def connected():
    return bool(setting("TODOIST_API_TOKEN"))


def call(method, path, query=None):
    url = f"{API}{path}" + (f"?{urllib.parse.urlencode(query)}" if query else "")
    req = urllib.request.Request(url, method=method, data=b"" if method == "POST" else None,
                                 headers={"Authorization": f"Bearer {setting('TODOIST_API_TOKEN')}"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        body = r.read()
    return json.loads(body) if body.strip() else {}


def is_todoist(item):
    return item.get("origin") == "todoist" or "todoist" in str(item.get("source", "")).lower() \
        or "todoist.com" in str(item.get("url", ""))


def task_id(item):
    """the id from a todoist row, from a todoist url, else by exact title among today's and overdue tasks."""
    if item.get("origin") == "todoist" and item.get("ref"):
        return str(item["ref"])
    m = URL_ID.search(str(item.get("url", "")))
    if m:
        return m.group(1)
    want, hits, cursor = norm(item.get("title", "")), [], None
    for _ in range(MAX_PAGES):
        q = {"query": FILTER, "limit": 200}
        if cursor:
            q["cursor"] = cursor
        page = call("GET", "/tasks/filter", q)
        hits += [t for t in page.get("results") or [] if norm(t.get("content", "")) == want]
        cursor = page.get("next_cursor")
        if not cursor:
            break
    if len(hits) != 1:
        raise Unsure("no single Todoist task has this title" if not hits else "more than one Todoist task has this title")
    return str(hits[0]["id"])


def recurring(task):
    return bool((task.get("due") or {}).get("is_recurring") or task.get("is_recurring"))


def why(e):
    if isinstance(e, urllib.error.HTTPError):
        return {401: "the token was refused", 403: "the token was refused", 404: "the task is gone"}.get(e.code, f"it answered {e.code}")
    if isinstance(e, Unsure):
        return str(e)
    if isinstance(e, (TimeoutError, urllib.error.URLError, OSError)):
        return "it did not answer"
    return type(e).__name__


def close(item):
    """{ok, id, recurring, message}. never raises."""
    if not connected():
        return {"ok": False, "id": "", "recurring": False, "message": "Todoist not connected; marked here only."}
    tid = ""
    try:
        tid = task_id(item)
        rec = recurring(call("GET", f"/tasks/{urllib.parse.quote(tid)}"))
        call("POST", f"/tasks/{urllib.parse.quote(tid)}/close")
    except Exception as e:
        return {"ok": False, "id": tid, "recurring": False, "message": f"Not closed in Todoist: {why(e)}. Marked here only."}
    msg = "Closed in Todoist."
    if rec:
        msg += " It repeats, so Todoist moved it to its next date; undo may not move it back."
    return {"ok": True, "id": tid, "recurring": rec, "message": msg}


def reopen(tid, was_recurring=False):
    if not connected():
        return {"ok": False, "id": tid, "recurring": was_recurring, "message": "Todoist not connected; back on the list here only."}
    try:
        call("POST", f"/tasks/{urllib.parse.quote(tid)}/reopen")
    except Exception as e:
        return {"ok": False, "id": tid, "recurring": was_recurring, "message": f"Not reopened in Todoist: {why(e)}."}
    msg = "Reopened in Todoist."
    if was_recurring:
        msg += " It repeats, so its date may still be the next one."
    return {"ok": True, "id": tid, "recurring": was_recurring, "message": msg}
