# the day's shape, shared by the brief and the board: merged events, open blocks, overlaps, the ribbon, sun times
import datetime as dt
import math
import re

from . import config

WAKE = ("08:00", "21:00")
NO_SKY = (6 * 60 + 30, 18 * 60 + 30)  # sunrise and sunset when no location is set
SHAPE = {"HEAVY": "A full day", "NORMAL": "A steady day", "OPEN": "An open day"}


def hm(s):
    m = re.match(r"^(\d{1,2}):(\d{2})(?::\d{2})?$", (s or "").strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


def clock(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def fmt_clock(hhmm):
    t = dt.datetime.strptime(hhmm, "%H:%M")
    return t.strftime("%-I:%M %p").replace(":00 ", " ")


def pretty(hhmm):
    return fmt_clock(hhmm) if hm(hhmm) is not None else hhmm


def duration(minutes):
    h, m = divmod(minutes, 60)
    return f"{h}h {m:02d}m" if h and m else f"{h}h" if h else f"{m}m"


def same_name(name, title):
    """'Stat Methods' is 'Statistical Methods': two words that prefix-match."""
    words = [w for w in re.findall(r"[a-z]{3,}", name.lower()) if w not in ("and", "the", "for", "intro")]
    have = re.findall(r"[a-z]{3,}", title.lower())
    hits = sum(any(w.startswith(h) or h.startswith(w) for h in have) for w in words)
    return hits >= min(2, len(words))


def merge_day(events, meetings):
    """calendar events plus today's class meetings from the school folder, deduped, time ordered."""
    out = []
    for e in events or []:
        s, f = hm(e.get("start")), hm(e.get("end"))
        base = {k: str(e.get(k) or "") for k in ("title", "where", "kind", "source", "detail", "url")}
        if not e.get("start") and not e.get("end"):
            out.append(dict(base, start="", end="", all_day=True))
        elif s is not None:
            # no end: half an hour. past midnight or backwards: the rest of today
            end = f if f is not None and f > s else (s + 30 if f is None else 23 * 60 + 59)
            out.append(dict(base, start=clock(s), end=clock(min(end, 23 * 60 + 59)), all_day=False))
    for m in meetings or []:
        if m.get("day") != "today" or hm(m.get("start")) is None:
            continue
        ms, mf = hm(m["start"]), hm(m["end"])
        digits = re.sub(r"\D", "", m["class"])
        same = None
        for e in out:
            if e["all_day"]:
                continue
            overlap = min(mf, hm(e["end"])) - max(ms, hm(e["start"]))
            t = e["title"].lower()
            if overlap >= (mf - ms) / 2 and ((digits and digits in t) or same_name(m["name"], t)):
                same = e
                break
        if same:
            same.update({"class": m["class"], "role": m["role"]})
            same["kind"] = "ta" if m["role"] == "ta" else same["kind"] or "class"
        else:
            out.append({"title": f'{m["class"]} {m["name"]}', "where": "", "kind": "ta" if m["role"] == "ta" else "class",
                        "source": "school", "detail": "", "url": "", "start": m["start"], "end": m["end"],
                        "all_day": False, "class": m["class"], "role": m["role"]})
    for e in out:
        e.setdefault("class", "")
        e.setdefault("role", "")
    return sorted(out, key=lambda e: (not e["all_day"], e["start"]))


def free_blocks(events, window=WAKE, min_minutes=45):
    lo, end = hm(window[0]), hm(window[1])
    busy = sorted((hm(e["start"]), hm(e["end"])) for e in events if not e["all_day"])
    cur, out = lo, []
    for s, f in busy + [(end, end)]:
        s, f = min(max(s, lo), end), min(max(f, lo), end)
        if s - cur >= min_minutes:
            out.append({"start": clock(cur), "end": clock(s), "minutes": s - cur})
        cur = max(cur, f)
    return out


def conflicts(events):
    timed = [e for e in events if not e["all_day"]]
    out = []
    for i, a in enumerate(timed):
        for b in timed[i + 1:]:
            o = min(hm(a["end"]), hm(b["end"])) - max(hm(a["start"]), hm(b["start"]))
            if o > 0:
                out.append({"a": a["title"], "b": b["title"], "minutes": o, "at": max(a["start"], b["start"])})
    return out


def sun_times(day, where=None):
    """local sunrise and sunset in minutes after midnight. noaa approximation, good to a few minutes.
    no location set: a fixed 6:30 to 18:30."""
    where = where or config.latlon()
    if not where:
        return NO_SKY
    lat, lon = where
    g = 2 * math.pi / 365 * (day.timetuple().tm_yday - 1)
    eq = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                   - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    la = math.radians(lat)
    x = math.cos(math.radians(90.833)) / (math.cos(la) * math.cos(decl)) - math.tan(la) * math.tan(decl)
    if not -1 <= x <= 1:  # polar day or night
        return NO_SKY
    ha = math.degrees(math.acos(x))
    off = dt.datetime.combine(day, dt.time(12), config.tz()).utcoffset().total_seconds() / 60
    return round(720 - 4 * (lon + ha) - eq + off), round(720 - 4 * (lon - ha) - eq + off)


def ribbon(events, blocks, day=None):
    """geometry for the day ribbon: percent offsets, overlap lanes, open blocks, hour ticks, daylight."""
    timed = [e for e in events if not e["all_day"]]
    lo = min([hm(WAKE[0])] + [hm(e["start"]) for e in timed]) // 60 * 60
    hi = min(-(-max([hm(WAKE[1])] + [hm(e["end"]) for e in timed]) // 60) * 60, 24 * 60)

    def pct(m):
        return round((min(max(m, lo), hi) - lo) / (hi - lo) * 100, 2)
    lane_end, out = [], []
    for e in sorted(timed, key=lambda e: (e["start"], e["end"])):
        s, f = hm(e["start"]), hm(e["end"])
        lane = next((i for i, end in enumerate(lane_end) if end <= s), len(lane_end))
        if lane == len(lane_end):
            lane_end.append(f)
        else:
            lane_end[lane] = f
        out.append({"left": pct(s), "width": max(round(pct(f) - pct(s), 2), .8), "lane": lane,
                    "kind": e.get("kind") or "other", "title": e["title"], "start": e["start"], "end": e["end"]})
    free = [{"left": pct(hm(b["start"])), "width": round(pct(hm(b["end"])) - pct(hm(b["start"])), 2),
             "minutes": b["minutes"], "label": duration(b["minutes"])} for b in blocks]
    ticks = [{"left": pct(m), "hour": m // 60} for m in range(lo, hi + 1, 60)]
    light = None
    if day:
        r, s = sun_times(day)
        light = [pct(r), pct(s)]
    return {"lo": lo, "hi": hi, "lanes": max(1, len(lane_end)), "events": out, "free": free, "ticks": ticks,
            "daylight": light}


def booked_minutes(events):
    out, cur = 0, None
    for s, f in sorted((hm(e["start"]), hm(e["end"])) for e in events if not e["all_day"]):
        if cur and s <= cur[1]:
            cur[1] = max(cur[1], f)
            continue
        if cur:
            out += cur[1] - cur[0]
        cur = [s, f]
    return out + (cur[1] - cur[0] if cur else 0)


def day_class(events):
    """HEAVY: five hours booked or three meetings back to back. OPEN: at most one short meeting."""
    timed = sorted((hm(e["start"]), hm(e["end"])) for e in events if not e["all_day"])
    if not timed or (len(timed) == 1 and timed[0][1] - timed[0][0] <= 60):
        return "OPEN"
    run, best, end = 1, 1, timed[0][1]
    for s, f in timed[1:]:
        run = run + 1 if s - end < 15 else 1
        best = max(best, run)
        end = max(end, f)
    return "HEAVY" if booked_minutes(events) >= 300 or best >= 3 else "NORMAL"
