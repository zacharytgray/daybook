# shared bits for the brief's tests: a clean, invented environment and small builders
import datetime as dt
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from daybook import brief, config  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "brief"
TUE = dt.date(2026, 10, 6)
DENVER = (39.74, -104.99)

# every test starts here: no env file, no network sinks, nothing real
BASE_ENV = {
    "DAYBOOK_ENV_FILE": str(FIX / "no.env"),
    "DAYBOOK_TZ": "America/Denver",
    "DAYBOOK_LAT": str(DENVER[0]),
    "DAYBOOK_LON": str(DENVER[1]),
    "DAYBOOK_LOCATION": "Lakeside",
    "DAYBOOK_USER_NAME": "Avery",
    "DAYBOOK_AGENT_NAME": "Pip",
    "DAYBOOK_SCHOOL": str(FIX / "school"),
    "DAYBOOK_PROJECTS": str(FIX / "projects"),
    "DAYBOOK_WORK_ROOTS": str(FIX / "work"),
    "DAYBOOK_DATA": "/nonexistent/daybook-test-data",
    "DAYBOOK_BRIEFS": "/nonexistent/daybook-test-briefs",
    "DAYBOOK_BRIEF_WEB": "http://127.0.0.1:9",  # never a live server
    "DAYBOOK_CHROME": "/nonexistent/chrome",
    "DAYBOOK_MARKS": "/nonexistent/marks.json",
}


def clean_env(**over):
    """a mock.patch.dict over os.environ with every daybook and todoist variable cleared, then BASE_ENV, then over."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DAYBOOK_", "TODOIST_"))}
    env.update(BASE_ENV)
    env.update({k: str(v) for k, v in over.items()})
    return mock.patch.dict(os.environ, env, clear=True)


class Case(unittest.TestCase):
    """runs each test inside clean_env(); ENV adds per-class overrides."""
    ENV = {}

    def setUp(self):
        p = clean_env(**self.ENV)
        p.start()
        self.addCleanup(p.stop)
        # no env file ever loads here; put the flag back so other suites see what they expect
        old = config._loaded
        config._loaded = True
        self.addCleanup(setattr, config, "_loaded", old)

    def env(self, **over):
        os.environ.update({k: str(v) for k, v in over.items()})


def ev(start, end, title, kind="meeting", source="Google Calendar", **kw):
    return dict({"start": start, "end": end, "title": title, "where": "", "kind": kind,
                 "source": source, "detail": "", "url": ""}, **kw)


def base_brief(**kw):
    b = {"day_class": "NORMAL", "headline": "Two classes and a long open afternoon.",
         "opening": "A teaching day with room to think after lunch.",
         "focus": {"title": "Grade Lab 4", "why": "Students turned it in last night.",
                   "when": "1-2 PM", "source": "school folder"},
         "next_actions": [], "events": [], "tomorrow": "", "needs_attention": [], "resolved": [],
         "todoist_schedule": [], "in_lecture": [], "projects": [], "news": [], "news_note": "",
         "movement": "Mild, 70F at noon.", "weather_line": "Sunny, 78 / 55",
         "source_status": []}
    b.update(kw)
    return b


def ctx_for(day, **school):
    s = {"date": day.isoformat(), "class_meetings": [], "due_soon": [], "to_grade": [],
         "ta_grading_done": [], "ta_cutoffs_closed": [], "decisions_owed": [], "recent_lectures": [],
         "todoist_task_ids": [], "problems": [], "office_hours": []}
    s.update(school)
    return {"school": s, "prs": [], "projects": {"reports": [], "sessions": [], "git": []},
            "mail": {"status": "off", "note": "no second mailbox set", "items": []},
            "gathered_at": f"{day.isoformat()}T07:30:00-06:00"}
