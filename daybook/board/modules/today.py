# today: the brief's day, live. items with defaults and marks, the ribbon, free blocks
import datetime as dt

from ... import config
from ... import day as D
from ...common import safe_url
from .. import items as I


def collect(ctx):
    t = ctx.get("now") or config.now()
    d = I.brief_dir(t)
    if not d:
        raise OSError("no brief on disk yet")
    brief, bctx = I.load_brief(d)
    day = dt.date.fromisoformat(d.name)
    school = (bctx or {}).get("school") or {}
    cls, names = I.classes(), I.repos()
    shown, hidden = I.build(brief, bctx, ctx["store"].marks(), t, cls, names)
    events = D.merge_day(brief.get("events"), school.get("class_meetings"))
    blocks, clashes = D.free_blocks(events), D.conflicts(events)
    timed = [e for e in events if not e["all_day"]]
    wx = (bctx or {}).get("weather") or {}
    rise, sset = D.sun_times(day)
    focus = next((i for i in shown if i["origin"] == "focus"), None)
    rb = D.ribbon(events, blocks, day) if timed else None
    end = D.clock(rb["hi"]) if rb else D.WAKE[1]
    for i in shown + hidden:
        i["window"] = None if day != t.date() else I.window(i, end)
    return {
        "date": day.isoformat(), "stale": day != t.date(), "headline": brief.get("headline", ""),
        "opening": brief.get("opening", ""),
        "weather_line": wx.get("line") if wx.get("status") == "ok" else brief.get("weather_line", ""),
        "sunrise": D.pretty(D.clock(rise)), "sunset": D.pretty(D.clock(sset)),
        "sun": {"rise": D.clock(rise), "set": D.clock(sset)},
        "shape": D.SHAPE[D.day_class(events)], "booked": D.duration(D.booked_minutes(events)) if timed else "0",
        "open": D.duration(sum(b["minutes"] for b in blocks)),
        "focus": focus, "items": [i for i in shown if i is not focus],
        "hidden": [{k: i[k] for k in ("id", "title", "source", "ref", "origin", "url", "mark")} for i in hidden],
        "done_count": sum(1 for i in hidden if i["mark"]["state"] == "done"),
        "events": [dict(e, url=safe_url(e.get("url")), start_label=D.pretty(e["start"]), end_label=D.pretty(e["end"]))
                   for e in events],
        "free": [dict(b, start_label=D.pretty(b["start"]), end_label=D.pretty(b["end"]), label=D.duration(b["minutes"]))
                 for b in blocks],
        "clashes": [dict(c, at_label=D.pretty(c["at"])) for c in clashes],
        "ribbon": rb,
        "tomorrow": brief.get("tomorrow", ""),
        "brief_url": f'{config.brief_web().rstrip("/")}/{day.isoformat()}/',
        "where_choices": I.where_choices(cls, names),
    }
