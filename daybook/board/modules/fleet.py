# fleet: services from a json file or command, devices from the registry, dispatch sessions per host
import json
import shlex
import socket
import subprocess
import threading
import time
import tomllib

from ... import config
from ...common import one_line, plain
from .. import agent as A

CACHE_SECONDS = 60
_cache = {}
_lock = threading.Lock()


def cached(key, fn):
    with _lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
            return hit[1]
    val = fn()
    with _lock:
        _cache[key] = (time.monotonic(), val)
    return val


def read_services():
    """the services json from DAYBOOK_SERVICES_FILE, or the stdout of DAYBOOK_SERVICES_CMD. None when both are unset."""
    f, cmd = config.path("DAYBOOK_SERVICES_FILE"), config.setting("DAYBOOK_SERVICES_CMD")
    if f:
        return json.loads(f.read_text())
    if cmd:
        # a status command may exit non-zero when something drifts, so read stdout whatever the code
        p = subprocess.run(shlex.split(cmd), capture_output=True, text=True, timeout=5)
        return json.loads(p.stdout)
    return None


def services():
    try:
        d = read_services()
    except subprocess.TimeoutExpired:
        return {"error": "the services command timed out"}
    except (OSError, ValueError) as e:
        return {"error": f"services unreadable: {type(e).__name__}"}
    if d is None:
        return {"off": True, "ok": 0, "drift": 0, "down": 0, "checked_at": "", "rows": []}
    if not isinstance(d, dict):
        return {"error": "services unreadable: not a json object"}
    rows = []
    for s in d.get("services") or []:
        if not isinstance(s, dict) or s.get("status") == "retired":
            continue
        v = str(s.get("verdict") or "").lower()
        v = v if v in ("ok", "drift", "down") else "drift"
        open_issues = [i for i in s.get("issues") or [] if isinstance(i, dict) and i.get("status", "open") == "open"]
        dot = "good" if v == "ok" else "bad" if v == "down" else "warn"
        note = plain(one_line(open_issues[0].get("summary", ""), 160)) if open_issues and dot != "good" else ""
        rows.append({"label": one_line(s.get("label"), 80), "verdict": v, "dot": dot, "note": note,
                     "open_issues": len(open_issues)})
    rows.sort(key=lambda r: ({"bad": 0, "warn": 1, "good": 2}[r["dot"]], r["label"]))
    count = {k: sum(1 for r in rows if r["verdict"] == k) for k in ("ok", "drift", "down")}
    return dict(count, checked_at=one_line(d.get("checked_at"), 40), rows=rows)


def reachable(ip, port=22, timeout=1.0):
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def devices():
    reg = config.path("DAYBOOK_REGISTRY")
    out = []
    if not reg:
        return out
    for f in sorted((reg / "devices").glob("*.toml")):
        try:
            d = tomllib.loads(f.read_text())
        except (OSError, tomllib.TOMLDecodeError):
            continue
        assume = d.get("assume_up")
        out.append({"hostname": str(d.get("hostname") or f.stem), "role": str(d.get("role") or ""),
                    "ip": str(d.get("ip") or d.get("tailscale_ip") or ""),
                    "assume": assume if isinstance(assume, bool) else None})
    res = {}
    if config.flag("DAYBOOK_PROBE_DEVICES"):
        def probe(dev):
            res[dev["hostname"]] = reachable(dev["ip"]) if dev["ip"] else False
        threads = [threading.Thread(target=probe, args=(d,)) for d in out]
        for th in threads:
            th.start()
        for th in threads:
            th.join(2)
    else:
        # no probing: the device file may say, else the page shows "not checked"
        res = {d["hostname"]: d["assume"] for d in out}
    order = {"hub": 0, "laptop": 1, "gpu": 2}
    return sorted([{k: v for k, v in dict(d, up=res.get(d["hostname"], False)).items() if k != "assume"} for d in out],
                  key=lambda d: (order.get(d["role"], 9), d["hostname"]))


def collect(ctx):
    devs = cached(("devices", config.setting("DAYBOOK_REGISTRY"), config.setting("DAYBOOK_PROBE_DEVICES")), devices)
    counts = {}
    for s in A.sessions():
        if not s["ended_flag"]:
            counts[s["host"] or "hub"] = counts.get(s["host"] or "hub", 0) + 1
    devs = [dict(d, sessions=counts.get(d["role"], 0) + (counts.get(d["hostname"], 0) if d["hostname"] != d["role"] else 0))
            for d in devs]
    return {"services": cached(("services", config.setting("DAYBOOK_SERVICES_FILE"),
                                   config.setting("DAYBOOK_SERVICES_CMD")), services), "devices": devs, "sessions_by_host": counts}
