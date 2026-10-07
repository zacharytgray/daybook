# items: built fresh from the latest brief each time, never stored. marks hide or annotate them
import datetime as dt
import json
import os
import re
from pathlib import Path

from .. import config
from ..common import item_id, safe_url, short_path, split_frontmatter
from . import models as M
from .store import mark_hides

RUNNERS = ("claude", "codex", "agent")
REACH = ("draft", "branch", "ship")
CLASS_CODE = re.compile(r"(?i)\b([A-Z]{2,5})[- ]?(\d{3,4})\b")
SCHOOL_DAYS = 7  # school items due within a week, plus anything overdue


def brief_dir(t=None):
    """today's brief in the configured zone, else the newest one on disk."""
    root = config.path("DAYBOOK_BRIEFS")
    if not root:
        return None
    d = root / (t or config.now()).date().isoformat()
    if (d / "brief.json").is_file():
        return d
    days = sorted(p for p in root.glob("????-??-??") if (p / "brief.json").is_file())
    return days[-1] if days else None


def load_brief(d):
    brief = json.loads((d / "brief.json").read_text())
    ctx_file = d / "context.json"
    ctx = json.loads(ctx_file.read_text()) if ctx_file.is_file() else {}
    return brief, ctx


def classes():
    """code -> {code, name, dir, workdir} from the school folder's class.md frontmatter.
    a relative workdir resolves against the school folder."""
    school = config.path("DAYBOOK_SCHOOL")
    out = {}
    if not school:
        return out
    for f in sorted((school / "classes").glob("*/class.md")):
        if f.parent.name.startswith("_"):
            continue
        try:
            c, _ = split_frontmatter(f)
        except OSError:
            continue
        code = c.get("code", f.parent.name).upper()
        wd = os.path.expanduser(c.get("workdir", ""))
        if wd and not os.path.isabs(wd):
            wd = str((school / wd).resolve())
        out[code] = {"code": code, "name": c.get("name", ""), "dir": f.parent.name, "workdir": wd}
    return out


def repos():
    root = config.path("DAYBOOK_PROJECTS")
    try:
        return sorted(p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))
    except (OSError, AttributeError):
        return []


def allowed_roots():
    """where a click may start work: the projects folder and the work roots. anything else goes to the agent by hand"""
    p = config.path("DAYBOOK_PROJECTS")
    return ([p] if p else []) + config.paths("DAYBOOK_WORK_ROOTS")


def allowed(p, roots=None):
    """an absolute path at or under one of the allowed roots, after symlinks and dots resolve."""
    roots = allowed_roots() if roots is None else roots
    if not p or not os.path.isabs(os.path.expanduser(str(p))):
        return False
    rp = Path(os.path.realpath(os.path.expanduser(str(p))))
    for r in roots:
        rr = Path(os.path.realpath(r))
        if rp == rr or rr in rp.parents:
            return True
    return False


def where_choices(cls=None, names=None):
    """the where picker: projects, the work roots themselves, and class workdirs inside the roots."""
    cls = classes() if cls is None else cls
    names = repos() if names is None else names
    proj = config.path("DAYBOOK_PROJECTS")
    out = [{"path": str(proj / n), "label": n, "group": "Projects"} for n in names] if proj else []
    out += [{"path": str(r), "label": short_path(r), "group": "Work roots"} for r in config.paths("DAYBOOK_WORK_ROOTS")]
    out += [{"path": c["workdir"], "label": c["name"] or c["code"], "group": "Classes"}
            for c in cls.values() if c["workdir"] and allowed(c["workdir"])]
    return out


def class_of(*texts):
    for t in texts:
        m = CLASS_CODE.search(str(t or ""))
        if m:
            return f"{m.group(1).upper()}-{m.group(2)}"
    return ""


def repo_of(names, *texts):
    """a project named in a forge url or in the words of the item."""
    for t in texts:
        m = re.search(r"https://[^/\s]+/[^/\s]+/([^/\s#?]+)/(?:pull|merge_requests|issues)/", str(t or ""))
        if m and m.group(1) in names:
            return m.group(1)
    for t in texts:
        words = set(re.findall(r"[A-Za-z0-9][A-Za-z0-9._-]+", str(t or "")))
        for n in sorted(names, key=len, reverse=True):
            if len(n) > 3 and n in words:
                return n
    return ""


def suggest(item, cls, names):
    """panel defaults: the brief's handoff field when present, else a guess from what the item is."""
    r = item.get("handoff") if isinstance(item.get("handoff"), dict) else None
    if r and r.get("runner") in RUNNERS:
        runner = r["runner"]
        model = M.pick(runner, str(r.get("model") or ""))
        where = os.path.expanduser(str(r.get("where") or ""))
        return {"runner": runner, "model": model, "where": where,
                "reach": r.get("reach") if r.get("reach") in REACH else "draft",
                "prompt": str(r.get("prompt") or ""), "from": "brief"}
    kind = item.get("kind", "")
    texts = (item.get("title"), item.get("class"), item.get("source"), item.get("why"))
    if kind in ("school", "ta"):
        c = cls.get(class_of(*texts))
        where = c["workdir"] if c and c["workdir"] and allowed(c["workdir"]) else ""
        return {"runner": "claude", "model": M.pick("claude"), "where": where, "reach": "draft", "prompt": "", "from": "board"}
    if kind == "pr":
        repo = repo_of(names, item.get("url"), *texts)
        proj = config.path("DAYBOOK_PROJECTS")
        return {"runner": "claude", "model": M.pick("claude"), "where": str(proj / repo) if repo and proj else "",
                "reach": "branch", "prompt": "", "from": "board"}
    return {"runner": "agent", "model": "", "where": "", "reach": "draft", "prompt": "", "from": "board"}


def assignment_ref(cls, code, title):
    """the school file behind a due item, matched by its title."""
    c, school = cls.get(code), config.path("DAYBOOK_SCHOOL")
    if not c or not school:
        return ""
    for f in sorted((school / "classes" / c["dir"] / "assignments").glob("*.md")):
        if f.name.startswith("_"):
            continue
        try:
            fm, _ = split_frontmatter(f)
        except OSError:
            continue
        if fm.get("title", "").strip() == title.strip():
            return f"classes/{c['dir']}/assignments/{f.name}"
    return ""


def tokens(s):
    return {w for w in re.findall(r"[a-z]{3,}|\d+", str(s).lower()) if w not in ("the", "and", "for", "assignment")}


def covers(action, due):
    """a next action already about this assignment: same class, two shared words."""
    if class_of(action.get("title"), action.get("why")) != str(due.get("class", "")).upper():
        return False
    return len(tokens(action.get("title")) & (tokens(due.get("title")) - tokens(due.get("class")))) >= 2


def raw_items(brief, ctx, t=None):
    """focus, next actions, todoist rows, school due soon. same order the page ranks them."""
    t = t or config.now()
    school = (ctx or {}).get("school") or {}
    out = []
    f = brief.get("focus") or {}
    if f.get("title"):
        out.append(dict(f, origin="focus", kind=f.get("kind", ""), horizon="today"))
    acts = brief.get("next_actions") or []
    for h in ("today", "this_week"):
        out += [dict(a, origin="next") for a in acts if (a.get("horizon") or "today") == h]
    # todoist rows that mirror a school file never show; the school folder is the source of truth
    mirrored = {str(i) for i in school.get("todoist_task_ids") or []}
    for r in brief.get("todoist_schedule") or []:
        if str(r.get("id", "")) in mirrored:
            continue
        out.append({"title": r.get("title", ""), "why": r.get("sentence", ""), "when": "", "kind": "task",
                    "source": "Todoist", "ref": str(r.get("id", "")), "origin": "todoist", "horizon": "today",
                    "handoff": r.get("handoff")})
    horizon = t.date().toordinal() + SCHOOL_DAYS
    covered = [a for a in acts if a.get("kind") in ("school", "ta")]
    # due_soon only: to_grade and grades never become items
    for d in school.get("due_soon") or []:
        if any(covers(a, d) for a in covered):
            continue
        try:
            when = dt.datetime.fromisoformat(d["sort"]).date().toordinal()
        except (KeyError, ValueError):
            continue
        if not d.get("overdue") and when > horizon:
            continue
        out.append({"title": f'{d.get("class", "")} {d.get("title", "")}'.strip(), "why": "", "kind": "school",
                    "when": ("overdue, was due " if d.get("overdue") else "due ") + d.get("due", ""),
                    "source": "school", "class": d.get("class", ""), "origin": "school", "horizon": "this_week",
                    "overdue": bool(d.get("overdue")), "assignment": d.get("title", "")})
    return out


def build(brief, ctx, marks, t=None, cls=None, names=None):
    """items with ids, defaults and marks. returns (visible, hidden)."""
    t = t or config.now()
    cls = classes() if cls is None else cls
    names = repos() if names is None else names
    by_id = {m["item_id"]: m for m in marks}
    seen, shown, hidden = set(), [], []
    for it in raw_items(brief, ctx, t):
        iid = item_id(it.get("title", ""))
        if not it.get("title") or iid in seen:
            continue
        seen.add(iid)
        ref = it.get("ref") or ""
        if it["origin"] == "school":
            ref = assignment_ref(cls, it["class"], it["assignment"]) or f'school {it["class"]}'
        elif not ref:
            ref = it.get("source", "")
        d = suggest(it, cls, names)
        d["where_label"] = short_path(d["where"])
        mark = by_id.get(iid)
        row = {"id": iid, "title": it["title"], "why": it.get("why", ""), "when": it.get("when", ""),
               "kind": it.get("kind", ""), "source": it.get("source", ""), "ref": ref, "url": safe_url(it.get("url")),
               "origin": it["origin"], "horizon": it.get("horizon", "today"), "overdue": it.get("overdue", False),
               "defaults": d, "where_ok": allowed(d["where"]) if d["where"] else True,
               "mark": {k: mark[k] for k in ("state", "until", "at", "by")} if mark else None}
        (hidden if mark_hides(mark, t) else shown).append(row)
    return shown, hidden


# a to-do's time window today, read from its words: "1-2 PM", "3:15-3:45 PM", "11 AM-1 PM", "after 7 PM"
_AP = r"\s*([ap])\.?m\b\.?"
RANGE = re.compile(r"(?i)(?<![\w:])(\d{1,2})(?::(\d{2}))?(?:" + _AP + r")?\s*(?:-|\u2013|to)\s*(\d{1,2})(?::(\d{2}))?" + _AP)
AFTER = re.compile(r"(?i)\bafter\s+(\d{1,2})(?::(\d{2}))?" + _AP)
# a clause that names another day is not today
OTHER_DAY = re.compile(r"(?i)\b(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)(?:day)?\b|\btomorrow\b|\bdue\b|\bnext week\b|"
                       r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d|\b\d{1,2}/\d{1,2}\b")


def _hm(h, m, ap):
    h, m = int(h), int(m or 0)
    if not 1 <= h <= 12 or m > 59:
        return None
    return (h % 12 + (12 if ap.lower() == "p" else 0)) * 60 + m


def window_of(text, end="21:00"):
    """{"start", "end"} as HH:MM from the first time range in the first clause that stays on today, else None."""
    clause = re.split(r"[.;]\s", str(text or ""), maxsplit=1)[0]
    if OTHER_DAY.search(clause):
        return None
    m = RANGE.search(clause)
    if m:
        h1, m1, ap1, h2, m2, ap2 = m.groups()
        b = _hm(h2, m2, ap2)
        a = _hm(h1, m1, ap1 or ap2)
        if a is not None and b is not None and not ap1 and a >= b and ap2.lower() == "p":
            a = _hm(h1, m1, "a")  # "11-1 PM" starts in the morning
        if a is None or b is None or a >= b:
            return None
        return {"start": f"{a // 60:02d}:{a % 60:02d}", "end": f"{b // 60:02d}:{b % 60:02d}"}
    m = AFTER.search(clause)
    if m:
        a = _hm(*m.groups())
        e = int(end[:2]) * 60 + int(end[3:5])
        if a is None or a >= 23 * 60 + 59:
            return None
        e = e if e > a else 23 * 60 + 59
        return {"start": f"{a // 60:02d}:{a % 60:02d}", "end": f"{e // 60:02d}:{e % 60:02d}"}
    return None


def window(item, end="21:00"):
    """only today's items get a window; "when" first, then the first clause of "why"."""
    if item.get("horizon") != "today" or item.get("origin") == "school":
        return None
    return window_of(item.get("when"), end) or window_of(item.get("why"), end)


def find(items, iid):
    return next((i for i in items if i["id"] == iid), None)
