# agent: what dispatch sessions are doing, what finished, and the requests the board sent
from ... import config
from .. import agent as A

FINISHED_HOURS = 36
PUBLIC = ("name", "task", "cwd", "host", "backend", "model", "status", "waiting_for", "started", "ended", "url", "attach")
# the request text again, while it may still need sending by hand
RESEND = ("prefilled", "copy", "no_session")


def report(s, t):
    lines, hidden = A.report_excerpt(s, hours=FINISHED_HOURS + 12, t=t)
    return {"report": lines, "report_hidden": hidden}


def public(s):
    return dict({k: s[k] for k in PUBLIC}, title=A.title_of(s["name"]))


def collect(ctx):
    t = ctx.get("now") or config.now()
    metas = A.sessions()
    by_name = {s["name"]: s for s in metas}
    running, waiting, finished = [], [], []
    # a revived session keeps its old ended record; it shows as running, not finished
    live = {s["name"] for s in metas if not s["ended_flag"]}
    for s in sorted(metas, key=lambda s: -s["started_ts"]):
        if s["ended_flag"]:
            if s["name"] in live:
                continue
            if t.timestamp() - (s["ended_ts"] or s["started_ts"]) <= FINISHED_HOURS * 3600:
                finished.append(dict(public(s), **report(s, t)))
            continue
        row = dict(public(s), **report(s, t))
        if s["status"] in ("busy", "", "starting"):
            running.append(row)
        else:
            row["why"] = "needs permission" if s["status"] == "waiting" and s["waiting_for"] == "permission" else \
                "waiting on you" if s["status"] == "waiting" else "your turn"
            waiting.append(row)
    finished.sort(key=lambda s: s["ended"], reverse=True)
    reqs = []
    for r in ctx["store"].requests():
        s = by_name.get(r["session_name"] or "")
        again = r["status"] in RESEND
        reqs.append({"id": r["id"], "item_id": r["item_id"], "title": r["title"], "runner": r["runner"],
                     "model": r["model"], "reach": r["reach"], "status": r["status"], "at": r["at"],
                     "session": r["session_name"] or "", "url": s["url"] if s else "", "error": r["error"] or "",
                     "via": r.get("via") or "", "text": r["text"] if again else "",
                     "sms_url": A.sms_url(r["text"]) if again else ""})
    return {"running": running, "waiting": waiting, "finished": finished[:12], "requests": reqs,
            "sessions_on": bool(config.path("DAYBOOK_SESSIONS"))}
