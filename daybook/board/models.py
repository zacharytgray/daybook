# the models the panel offers: only what your dispatch can start, read from the DAYBOOK_MODELS json.
# {"claude": [{"id": "opus", "label": "Opus", "default": true}, ...], "codex": [...]}. empty means the agent picks
import json
import re
import threading

from .. import config
from ..common import one_line

RUNNERS = ("claude", "codex")
PROVIDER = {"claude": "Anthropic", "codex": "OpenAI"}
MODEL_ID = re.compile(r"^[a-z0-9][a-z0-9.:_-]{0,39}$")
_cache = {}
_lock = threading.Lock()


def empty(why):
    return {k: {"models": [], "error": why} for k in RUNNERS}


def parse(d):
    """keep only well formed rows. a runner with no rows says why."""
    if not isinstance(d, dict):
        return empty("the models file is not a json object")
    out = {}
    for runner in RUNNERS:
        rows, seen = [], set()
        for m in d.get(runner) or []:
            mid = m.get("id") if isinstance(m, dict) else None
            if not isinstance(mid, str) or not MODEL_ID.fullmatch(mid) or mid in seen:
                continue
            seen.add(mid)
            rows.append({"id": mid, "label": one_line(m.get("label") or mid, 60),
                         "provider": one_line(m.get("provider") or PROVIDER[runner], 40), "default": m.get("default") is True})
        if rows and not any(r["default"] for r in rows):
            rows[0]["default"] = True
        out[runner] = {"models": rows, "error": "" if rows else f"the models file lists no {runner} models"}
    return out


def catalog():
    """{claude: {models, error}, codex: {models, error}}, read again when the file changes."""
    f = config.path("DAYBOOK_MODELS")
    if not f:
        return empty("no models file is set")
    try:
        key = (str(f), f.stat().st_mtime_ns)
    except OSError:
        return empty("the models file is missing")
    with _lock:
        hit = _cache.get(str(f))
        if hit and hit[0] == key:
            return hit[1]
    try:
        val = parse(json.loads(f.read_text()))
    except (OSError, ValueError) as e:
        val = empty(f"could not read the models file ({type(e).__name__})")
    with _lock:
        _cache[str(f)] = (key, val)
    return val


def find(runner, mid):
    return next((m for m in catalog().get(runner, {}).get("models", []) if m["id"] == mid), None)


def pick(runner, wanted=""):
    """the brief's model when the list has it, else the runner's default, else "" (the agent picks)."""
    if runner not in RUNNERS:
        return ""
    ms = catalog()[runner]["models"]
    if wanted and wanted != "default" and any(m["id"] == wanted for m in ms):
        return wanted
    return next((m["id"] for m in ms if m.get("default")), ms[0]["id"] if ms else "")
