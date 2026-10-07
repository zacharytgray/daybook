# regressions for safeguards found in review: open links, extra model tools, env parsing, the session prefix
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from daybook import config  # noqa: E402


class EnvCase(unittest.TestCase):
    def setUp(self):
        self.saved = {k: v for k, v in os.environ.items() if k.startswith(("DAYBOOK_", "TODOIST_"))}
        for k in self.saved:
            del os.environ[k]
        self.tmp = Path(tempfile.mkdtemp(prefix="dbsafe"))
        self.env = self.tmp / "t.env"
        self.env.write_text("")
        os.environ["DAYBOOK_ENV_FILE"] = str(self.env)
        config._loaded = False

    def tearDown(self):
        for k in [k for k in os.environ if k.startswith(("DAYBOOK_", "TODOIST_"))]:
            del os.environ[k]
        os.environ.update(self.saved)
        config._loaded = False

    def load(self, text):
        for k in [k for k in os.environ if k.startswith("DAYBOOK_") and k != "DAYBOOK_ENV_FILE"]:
            del os.environ[k]
        self.env.write_text(text)
        config._loaded = False
        config.load_env()


class EnvFile(EnvCase):
    def test_relative_entries_in_a_path_list_all_resolve_from_the_file(self):
        self.load("DAYBOOK_WORK_ROOTS=./a" + os.pathsep + "./b\n")
        roots = config.paths("DAYBOOK_WORK_ROOTS")
        self.assertEqual(roots, [(self.tmp / "a").resolve(), (self.tmp / "b").resolve()])

    def test_only_a_matching_pair_of_quotes_is_stripped(self):
        self.load('DAYBOOK_DISPATCH_CMD="./my tool" --x\nDAYBOOK_TITLE="A desk"\n')
        self.assertEqual(config.setting("DAYBOOK_DISPATCH_CMD"), '"./my tool" --x')
        self.assertEqual(config.setting("DAYBOOK_TITLE"), "A desk")

    def test_a_broken_dispatch_command_turns_actions_off_not_the_page(self):
        from daybook.board import server
        self.load('DAYBOOK_DISPATCH_CMD="unbalanced\n')
        self.assertIsNone(server.dispatch_argv())


class SessionPrefix(EnvCase):
    def test_a_prefix_that_could_be_a_path_or_a_flag_falls_back(self):
        from daybook.board import agent
        for bad in ("../", "-", "--", "a/b-", "HD-", "x"):
            self.load(f"DAYBOOK_SESSION_PREFIX={bad}\n")
            self.assertEqual(agent.prefix(), "hd-", bad)
            self.assertIsNone(agent.handle_re().fullmatch("../etc"))
            self.assertIsNone(agent.handle_re().fullmatch("--yes"))
        self.load("DAYBOOK_SESSION_PREFIX=job-\n")
        self.assertEqual(agent.prefix(), "job-")


class OpenLinks(EnvCase):
    def test_only_remote_control_links_reach_the_page(self):
        from daybook.board import agent
        d = self.tmp / "dispatch"
        (d / "sessions").mkdir(parents=True)
        links = {"hd-one": "https://claude.ai/code/" + "session_" + "EXAMPLE",
                 "hd-two": "https://evil.example/phish", "hd-three": "http://claude.ai/x"}
        for name, url in links.items():
            (d / "sessions" / f"{name}.json").write_text(json.dumps({"name": name, "url": url, "started_at": 1}))
        self.load(f"DAYBOOK_SESSIONS={d}\n")
        got = {s["name"]: s["url"] for s in agent.sessions()}
        self.assertTrue(got["hd-one"].startswith("https://claude.ai/"))
        self.assertEqual(got["hd-two"], "")
        self.assertEqual(got["hd-three"], "")


class ExtraTools(EnvCase):
    def test_only_read_named_tools_are_added(self):
        from daybook import brief
        self.load("DAYBOOK_EXTRA_READ_TOOLS=" + ",".join([
            "mcp__github__push_files", "mcp__shell__execute_command", "mcp__x__set_status",
            "mcp__gmail__batch_modify", "mcp__slack__add_reaction", "mcp__x__get_and_delete", "mcp__x__*",
            "Bash", "mcp__notes__search_notes", "mcp__cal__list_events", "mcp__x__events_get"]) + "\n")
        self.assertEqual(brief.extra_read_tools(), ["mcp__notes__search_notes", "mcp__cal__list_events",
                                                    "mcp__x__events_get"])

    def test_both_servers_share_one_host_rule(self):
        from daybook import brief
        from daybook.board import server
        self.load("DAYBOOK_ALLOWED_HOSTS=desk.example.ts.net\n")
        for h in ("127.0.0.1:8735", "localhost", "desk", "desk.example.ts.net", "other.ts.net", "evil.com", ""):
            self.assertEqual(brief.host_ok(h), server.host_ok(h), h)
        self.assertFalse(brief.host_ok("other.ts.net"))


if __name__ == "__main__":
    unittest.main()
