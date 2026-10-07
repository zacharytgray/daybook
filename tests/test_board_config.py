# the board's defaults are the safe ones, and every setting flows where it should
import datetime as dt
import os

from helpers import DAY, Env

from daybook import config
from daybook.board import agent as A
from daybook.board import server as S
from daybook.board import todoist as T
from daybook.board.store import tomorrow_morning


class DefaultsTest(Env):
    def setUp(self):
        super().setUp()
        for k in list(os.environ):
            if k.startswith(("DAYBOOK_", "TODOIST_")):
                del os.environ[k]

    def test_binds_localhost(self):
        self.assertEqual(S.default_host(), "127.0.0.1")
        self.assertEqual(S.default_port(), 8740)

    def test_side_effects_off(self):
        self.assertEqual(A.transport(), "copy")
        self.assertIsNone(S.dispatch_argv())
        self.assertFalse(T.connected())
        self.assertFalse(config.frozen())
        self.assertEqual(config.setting("DAYBOOK_ALLOWED_HOSTS"), "")
        self.assertFalse(S.host_ok("board.example-tailnet.ts.net"))
        self.assertIsNone(config.path("DAYBOOK_SESSIONS"))
        self.assertEqual(A.sessions(), [])
        self.assertEqual(A.ssh_targets(), {})

    def test_neutral_names(self):
        self.assertEqual(A.agent_name(), "Agent")
        self.assertEqual(A.user_name(), "the user")
        c = S.page_config()
        self.assertEqual((c["title"], c["agent"], c["tz"], c["location"], c["now"]), ("Daybook", "Agent", "UTC", "", ""))
        self.assertEqual(c["actions"], {"dispatch": False})


class OverridesTest(Env):
    def test_frozen_clock(self):
        os.environ["DAYBOOK_NOW"] = "2026-03-03T10:20:00"
        self.assertEqual(config.now().isoformat(), "2026-03-03T10:20:00-07:00")
        self.assertEqual(tomorrow_morning().isoformat(), "2026-03-04T05:00:00-07:00")
        self.assertEqual(S.page_config()["now"], "2026-03-03T10:20:00-07:00")

    def test_zone_moves_every_clock(self):
        os.environ["DAYBOOK_TZ"] = "Pacific/Auckland"
        os.environ["DAYBOOK_NOW"] = "2026-03-03T10:20:00"
        self.assertEqual(S.page_config()["tz"], "Pacific/Auckland")
        self.assertEqual(config.now().utcoffset(), dt.timedelta(hours=13))
        self.session("hd-a", DAY.timestamp())
        self.assertEqual(A.sessions()[0]["started"], "2026-03-04T05:00:00+13:00")

    def test_names_flow_into_requests_and_page(self):
        os.environ["DAYBOOK_USER_NAME"] = "Jo"
        os.environ["DAYBOOK_AGENT_NAME"] = "Moth"
        os.environ["DAYBOOK_LOCATION"] = "Hilltown"
        r = A.check({"title": "Water the tomatoes", "runner": "agent", "reach": "draft"})
        self.assertIn("Jo asks you to handle this yourself", A.request_text(r))
        c = S.page_config()
        self.assertEqual((c["user"], c["agent"], c["location"]), ("Jo", "Moth", "Hilltown"))
        from daybook.board.modules import layout
        self.assertEqual(layout()[1]["title"], "Moth")

    def test_dispatch_command_is_an_argv(self):
        os.environ["DAYBOOK_DISPATCH_CMD"] = "/opt/dispatch/bin/run --profile 'my box'"
        self.assertEqual(S.dispatch_argv(), ["/opt/dispatch/bin/run", "--profile", "my box"])
        self.assertTrue(S.page_config()["actions"]["dispatch"])

    def test_transport_order(self):
        os.environ["DAYBOOK_AGENT_SMS"] = "agent@example.com"
        self.assertEqual(A.transport(), "sms")
        os.environ["DAYBOOK_WEBHOOK_URL"] = "http://127.0.0.1:9/hook"
        self.assertEqual(A.transport(), "sms")  # a url with no secret is not a webhook
        os.environ["DAYBOOK_WEBHOOK_SECRET"] = "s"
        self.assertEqual(A.transport(), "webhook")
