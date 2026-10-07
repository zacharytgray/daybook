# <data>/today.md: the day in a few plain lines, for your agent and every session that wants it.
# no urls, no ids, no money, no grades, no em-dashes
import re
from pathlib import Path

from .. import config
from ..common import atomic_write, plain
from . import agent as A


def task(s):
    """a task line without session names; those are ids to anyone reading the day."""
    pat = r"\b" + re.escape(A.prefix()) + r"[a-z0-9][a-z0-9-]*"
    text = re.sub(r"\s+", " ", re.sub(pat, "a session", s.get("task") or "")).strip()
    return text or "(task hidden)"


def render(modules, t=None):
    t = t or config.now()
    today, ag = modules.get("today") or {}, modules.get("agent") or {}
    out = [f'# Today, {t.strftime("%A %B %-d, %Y")}', ""]
    if not today or today.get("error"):
        out.append("The brief is not available right now.")
    else:
        if today.get("stale"):
            out.append(f'No brief yet today; this is from {today["date"]}.')
        timed = [e for e in today.get("events") or [] if not e.get("all_day")]
        out.append(f'{today.get("shape", "")}. {len(timed)} on the calendar, {today.get("booked", "0")} booked, '
                   f'{today.get("open", "0")} open.')
        later = [e for e in timed if e["start"] >= t.strftime("%H:%M")] if not today.get("stale") else []
        if later:
            out.append(f'Next: {later[0]["title"]} at {later[0]["start_label"]}.')
        if today.get("focus"):
            out.append(f'Focus: {today["focus"]["title"]}.')
        out += ["", "## Open to-dos"]
        rows = [i for i in [today.get("focus")] + (today.get("items") or []) if i]
        for i in rows:
            when = f' ({i["when"]})' if i.get("when") else ""
            out.append(f'- {i["title"]}{when}')
        if not rows:
            out.append("- nothing open")
        marked = today.get("hidden") or []
        if marked:
            out += ["", "## Marked on the board"]
            for h in marked:
                m = h["mark"]
                out.append(f'- {h["title"]}: ' + ("snoozed till tomorrow" if m["state"] == "snoozed" else m["state"]))
    if ag and not ag.get("error"):
        busy = ag.get("running") or []
        wait = ag.get("waiting") or []
        done = [s for s in ag.get("finished") or [] if s.get("ended", "")[:10] == t.date().isoformat()]
        out += ["", f"## {A.agent_name()}"]
        out += [f'- running: {task(s)}' for s in busy] or ["- nothing running"]
        out += [f'- waiting on you: {task(s)}' for s in wait]
        out += [f'- finished today: {task(s)}' for s in done]
    out += ["", f'Written by {A.board_name()} at {t.strftime("%-I:%M %p")}.']
    return plain("\n".join(out)) + "\n"


def write(data_dir, modules, t=None):
    """rewrite today.md if the text changed. returns True when it wrote."""
    f = Path(data_dir) / "today.md"
    text = render(modules, t)
    try:
        old = f.read_text()
    except OSError:
        old = ""
    # the time stamp alone is not a change
    if old.rsplit("\nWritten by", 1)[0] == text.rsplit("\nWritten by", 1)[0]:
        return False
    atomic_write(f, text)
    return True
