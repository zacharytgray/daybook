# the demo must ignore the caller's own settings and keep every side effect off
import os
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHILD = """
import runpy, sys
ns = runpy.run_path(sys.argv[1], run_name="notmain")
ns["demo_env"]()
from daybook import config
for k in ("TODOIST_API_TOKEN", "DAYBOOK_WEBHOOK_URL", "DAYBOOK_WEBHOOK_SECRET", "DAYBOOK_AGENT_SMS",
          "DAYBOOK_DISPATCH_CMD", "DAYBOOK_GH", "DAYBOOK_WEATHER", "DAYBOOK_NEWS_FEEDS", "DAYBOOK_MAIL_HANDOFF",
          "DAYBOOK_HOST", "DAYBOOK_TZ", "DAYBOOK_NOW", "DAYBOOK_USER_NAME", "DAYBOOK_PROBE_DEVICES"):
    print(f"{k}={config.setting(k)}")
"""


def demo_settings(extra_env):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DAYBOOK_", "TODOIST_"))}
    env.update(extra_env)
    out = subprocess.run([sys.executable, "-c", CHILD, str(ROOT / "bin" / "daybook")], cwd=ROOT, env=env,
                         capture_output=True, text=True, timeout=60, check=True).stdout
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


class DemoIsolation(unittest.TestCase):
    def test_caller_side_effects_are_cleared(self):
        s = demo_settings({"TODOIST_API_TOKEN": "caller-token", "DAYBOOK_WEBHOOK_URL": "https://example.com/hook",
                           "DAYBOOK_WEBHOOK_SECRET": "caller-secret", "DAYBOOK_AGENT_SMS": "agent@example.com",
                           "DAYBOOK_DISPATCH_CMD": "/bin/echo", "DAYBOOK_GH": "/bin/echo",
                           "DAYBOOK_HOST": "0.0.0.0", "DAYBOOK_USER_NAME": "Caller"})
        for k in ("TODOIST_API_TOKEN", "DAYBOOK_WEBHOOK_URL", "DAYBOOK_WEBHOOK_SECRET", "DAYBOOK_AGENT_SMS",
                  "DAYBOOK_DISPATCH_CMD", "DAYBOOK_GH", "DAYBOOK_WEATHER", "DAYBOOK_NEWS_FEEDS", "DAYBOOK_MAIL_HANDOFF"):
            self.assertEqual(s[k], "", k)
        self.assertEqual(s["DAYBOOK_HOST"], "127.0.0.1")
        self.assertEqual(s["DAYBOOK_USER_NAME"], "Avery")
        self.assertEqual(s["DAYBOOK_PROBE_DEVICES"], "0")

    def test_demo_is_frozen_and_invented(self):
        s = demo_settings({})
        self.assertEqual(s["DAYBOOK_NOW"], "2026-04-14T10:20:00")
        self.assertEqual(s["DAYBOOK_TZ"], "America/Denver")

    def test_a_repo_env_file_is_not_read_by_the_demo(self):
        ns = runpy.run_path(str(ROOT / "bin" / "daybook"), run_name="notmain")
        self.assertIn("demo.env", (ROOT / "demo" / "demo.env").name)
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "caller.env"
            fake.write_text("TODOIST_API_TOKEN=from-file\n")
            s = demo_settings({"DAYBOOK_ENV_FILE": str(fake)})
        self.assertEqual(s["TODOIST_API_TOKEN"], "")
        self.assertTrue(callable(ns["demo_env"]))

    def test_demo_env_lists_every_side_effect_as_empty(self):
        text = (ROOT / "demo" / "demo.env").read_text()
        for k in ("DAYBOOK_AGENT_SMS", "DAYBOOK_WEBHOOK_URL", "DAYBOOK_WEBHOOK_SECRET", "DAYBOOK_DISPATCH_CMD",
                  "TODOIST_API_TOKEN"):
            self.assertIn(f"\n{k}=\n", text, k)


class Defaults(unittest.TestCase):
    def test_defaults_are_local_and_off(self):
        sys.path.insert(0, str(ROOT))
        from daybook import config
        d = config.DEFAULTS
        self.assertEqual(d["DAYBOOK_HOST"], "127.0.0.1")
        for k in ("DAYBOOK_AGENT_SMS", "DAYBOOK_WEBHOOK_URL", "DAYBOOK_WEBHOOK_SECRET", "DAYBOOK_DISPATCH_CMD",
                  "TODOIST_API_TOKEN", "DAYBOOK_GH", "DAYBOOK_WEATHER", "DAYBOOK_NEWS_FEEDS", "DAYBOOK_MAIL_HANDOFF",
                  "DAYBOOK_SCHOOL", "DAYBOOK_PROJECTS", "DAYBOOK_SESSIONS", "DAYBOOK_REGISTRY", "DAYBOOK_NOW"):
            self.assertEqual(d[k], "", k)
        self.assertEqual(d["DAYBOOK_REQUIRE_SUBSCRIPTION"], "1")

    def test_env_example_covers_every_setting(self):
        sys.path.insert(0, str(ROOT))
        from daybook import config
        text = (ROOT / ".env.example").read_text()
        for k in config.DEFAULTS:
            self.assertIn(f"\n{k}=\n", text, k)


if __name__ == "__main__":
    unittest.main()
