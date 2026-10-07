# every setting in one place. order: the real environment, then the env file, then these defaults.
# nothing here points at a real person, machine or account; an empty value turns that adapter off.
import datetime as dt
import os
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = {
    # identity and place
    "DAYBOOK_TITLE": "Daybook",                 # the board's name in the masthead and tab title
    "DAYBOOK_BRIEF_TITLE": "Morning Brief",     # the brief's masthead
    "DAYBOOK_USER_NAME": "you",                 # how request texts and the prompt name the reader
    "DAYBOOK_AGENT_NAME": "Agent",              # the agent that takes handed-off to-dos
    "DAYBOOK_TZ": "UTC",                        # IANA zone for every date and clock
    "DAYBOOK_LOCATION": "",                     # a label for the masthead, e.g. "Lakeside"
    "DAYBOOK_LAT": "",                          # sun times and the forecast; empty means a fixed 6:30 to 18:30 sky
    "DAYBOOK_LON": "",
    "DAYBOOK_FIRST_EDITION": "",                # YYYY-MM-DD of issue No. 1; empty hides the number
    "DAYBOOK_NOW": "",                          # freeze the clock (ISO, local) for demos, tests and screenshots
    # where things live
    "DAYBOOK_DATA": str(ROOT / "data"),         # the board's sqlite store, marks.json, today.md, requests.log
    "DAYBOOK_BRIEFS": str(ROOT / "briefs"),     # one folder per date: brief.json, context.json, brief.html
    "DAYBOOK_MARKS": "",                        # marks.json the brief reads; empty means <DAYBOOK_DATA>/marks.json
    "DAYBOOK_SCHOOL": "",                       # a classes/<code>/class.md folder; empty turns school off
    "DAYBOOK_PROJECTS": "",                     # a folder of git repos; empty turns git activity and repo picks off
    "DAYBOOK_WORK_ROOTS": "",                   # extra folders a handed-off task may run in (os.pathsep list)
    "DAYBOOK_SESSIONS": "",                     # an agent dispatch folder: sessions/, ended/, reports/
    "DAYBOOK_SESSION_PREFIX": "hd-",            # session handles look like <prefix><kebab-name>
    "DAYBOOK_REGISTRY": "",                     # a folder of devices/*.toml for the fleet room
    "DAYBOOK_SERVICES_FILE": "",                # a services json for the fleet room (see docs/data-contracts.md)
    "DAYBOOK_SERVICES_CMD": "",                 # or a command that prints that json; the file wins
    "DAYBOOK_MODELS": "",                       # a models json: what each runner may start; empty means the agent picks
    # serving. localhost unless you say otherwise
    "DAYBOOK_HOST": "127.0.0.1",
    "DAYBOOK_BOARD_PORT": "8740",
    "DAYBOOK_BRIEF_PORT": "8735",
    "DAYBOOK_BRIEF_WEB": "",                    # where the brief pages are served; empty means http://<host>:<brief port>
    "DAYBOOK_ALLOWED_HOSTS": "",                # extra Host header names for the board (comma list), e.g. a tailnet name
    # side effects. all off until set
    "DAYBOOK_AGENT_SMS": "",                    # an address for a prefilled sms: link to your agent
    "DAYBOOK_WEBHOOK_URL": "",                  # a signed webhook that hands requests to your agent
    "DAYBOOK_WEBHOOK_SECRET": "",
    "DAYBOOK_DISPATCH_CMD": "",                 # runs "<cmd> stop <name>" and "<cmd> revive <name>"; empty hides both
    "DAYBOOK_PROBE_DEVICES": "1",               # tcp/22 reachability checks for registry devices
    "TODOIST_API_TOKEN": "",                    # closes and reopens Todoist tasks when marks change
    # the brief's generator (none of this runs in the demo)
    "DAYBOOK_CLAUDE": "claude",                 # Claude Code CLI used by `brief generate`
    "DAYBOOK_CLAUDE_MODEL": "opus",
    "DAYBOOK_REQUIRE_SUBSCRIPTION": "1",        # refuse a run that would bill an API key
    "DAYBOOK_CALENDAR_ID": "primary",
    "DAYBOOK_TODOIST_PROJECT": "",              # a Todoist project id to read; empty reads the inbox by name
    "DAYBOOK_EXTRA_READ_TOOLS": "",             # comma list of extra read-only tools for the model
    "DAYBOOK_WEATHER": "",                      # "nws" for the US National Weather Service; empty turns it off
    "DAYBOOK_NEWS_FEEDS": "",                   # a feeds file (name<TAB>url); empty turns news feeds off
    "DAYBOOK_GH": "",                           # gh CLI for open pull requests; empty turns PRs off
    "DAYBOOK_MAIL_HANDOFF": "",                 # an approved second-mailbox connector (see docs/integrations.md)
    "DAYBOOK_CHROME": "",                       # Chrome or Chromium for the PDF; empty finds one or skips the PDF
    "DAYBOOK_COLOPHON": "",                     # the brief's closing line; empty uses a plain default
}

_loaded = False


def env_file():
    return Path(os.environ.get("DAYBOOK_ENV_FILE") or ROOT / ".env")


def load_env(path=None):
    """KEY=VALUE lines from the env file. the real environment wins. relative paths resolve from the file."""
    global _loaded
    _loaded = True
    f = Path(path) if path else env_file()
    try:
        lines = f.read_text().splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":  # only a matching pair of outer quotes
            v = v[1:-1]
        # a relative path resolves from the env file's folder, entry by entry in a path list
        if any(x.startswith(("./", "../")) for x in v.split(os.pathsep)):
            v = os.pathsep.join(str((f.parent / x).resolve()) if x.startswith(("./", "../")) else x
                                for x in v.split(os.pathsep))
        os.environ.setdefault(k, v)


def setting(name):
    if not _loaded:
        load_env()
    v = os.environ.get(name)
    return v if v not in (None, "") else DEFAULTS.get(name, "")


def flag(name):
    return setting(name).strip().lower() in ("1", "true", "yes", "on")


def path(name):
    """a path setting, or None when it is empty (the adapter is off)."""
    v = setting(name)
    return Path(os.path.expanduser(v)) if v else None


def paths(name):
    return [Path(os.path.expanduser(p)) for p in setting(name).split(os.pathsep) if p.strip()]


def tz():
    try:
        return ZoneInfo(setting("DAYBOOK_TZ"))
    except Exception:
        return ZoneInfo("UTC")


def now():
    """the wall clock in the configured zone, or the frozen DAYBOOK_NOW."""
    frozen = setting("DAYBOOK_NOW")
    if frozen:
        t = dt.datetime.fromisoformat(frozen)
        return t if t.tzinfo else t.replace(tzinfo=tz())
    return dt.datetime.now(tz())


def frozen():
    return bool(setting("DAYBOOK_NOW"))


def latlon():
    try:
        return float(setting("DAYBOOK_LAT")), float(setting("DAYBOOK_LON"))
    except ValueError:
        return None


def marks_file():
    return path("DAYBOOK_MARKS") or Path(os.path.expanduser(setting("DAYBOOK_DATA"))) / "marks.json"


def brief_web():
    return setting("DAYBOOK_BRIEF_WEB") or f'http://{setting("DAYBOOK_HOST")}:{setting("DAYBOOK_BRIEF_PORT")}'


def first_edition():
    try:
        return dt.date.fromisoformat(setting("DAYBOOK_FIRST_EDITION"))
    except ValueError:
        return None
