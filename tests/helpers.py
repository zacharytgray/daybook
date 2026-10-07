# shared board test setup: settings pointed at invented fixtures and a temp data dir, fabricated dispatch metas
import datetime as dt
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures" / "board"
sys.path.insert(0, str(ROOT))

from daybook import config  # noqa: E402

TZ = ZoneInfo("America/Denver")
DAY = dt.datetime(2026, 3, 3, 9, 0, tzinfo=TZ)
# a fake remote link, put together at run time so no link-shaped literal sits in the repo
FAKE_RC = "https://" + "claude.ai/code/" + "session_" + "TESTONLY"
SECRETS = ("CHATGUID-SECRET", "SESSIONID-SECRET", "THREADID-SECRET", "PROMPTID-SECRET", "DELIVERED-SECRET")


def meta(name, started, status="busy", task="", backend="claude", **extra):
    d = {"name": name, "cwd": "~/projects/notes-site", "host": "hub", "backend": backend, "model": "opus",
         "task": task, "started_at": started, "status": status, "url": FAKE_RC,
         "chat_guid": SECRETS[0], "session_id": SECRETS[1], "thread_id": SECRETS[2], "last_prompt_id": SECRETS[3],
         "delivered_keys": [SECRETS[4]], "delivered_done": SECRETS[4]}
    d.update(extra)
    return d


def base_env(tmp, dispatch):
    return {"DAYBOOK_DATA": str(tmp / "data"), "DAYBOOK_BRIEFS": str(FIX / "briefs"), "DAYBOOK_SESSIONS": str(dispatch),
            "DAYBOOK_SCHOOL": str(FIX / "school"), "DAYBOOK_PROJECTS": str(FIX / "projects"),
            "DAYBOOK_WORK_ROOTS": str(FIX / "workspace"), "DAYBOOK_REGISTRY": str(FIX / "registry"),
            "DAYBOOK_MODELS": str(FIX / "models.json"), "DAYBOOK_TZ": "America/Denver", "DAYBOOK_LAT": "40.0",
            "DAYBOOK_LON": "-105.0", "DAYBOOK_USER_NAME": "Sam", "DAYBOOK_AGENT_NAME": "Wren",
            "DAYBOOK_BRIEF_WEB": "http://127.0.0.1:9", "DAYBOOK_PROBE_DEVICES": "0"}


class Env(unittest.TestCase):
    """every test runs against fixtures and a throwaway data dir; nothing real is read or written.
    every DAYBOOK_ and TODOIST_ variable from the real environment is set aside first."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="daybook-test"))
        self.dispatch = self.tmp / "dispatch"
        for d in ("sessions", "ended", "reports"):
            (self.dispatch / d).mkdir(parents=True)
        self.saved = {k: v for k, v in os.environ.items() if k.startswith(("DAYBOOK_", "TODOIST_"))}
        for k in self.saved:
            del os.environ[k]
        self.loaded = config._loaded
        config._loaded = True  # never read a .env during tests
        self.env = base_env(self.tmp, self.dispatch)
        os.environ.update(self.env)
        from daybook.board import models
        from daybook.board.modules import fleet
        models._cache.clear()
        fleet._cache.clear()

    def tearDown(self):
        for k in [k for k in os.environ if k.startswith(("DAYBOOK_", "TODOIST_"))]:
            del os.environ[k]
        os.environ.update(self.saved)
        config._loaded = self.loaded
        shutil.rmtree(self.tmp, ignore_errors=True)

    def session(self, name, started, ended=False, **kw):
        where = self.dispatch / ("ended" if ended else "sessions")
        (where / f"{name}.json").write_text(json.dumps(meta(name, started, **kw)))

    def report(self, name, text):
        (self.dispatch / "reports" / f"{name}.md").write_text(text)
