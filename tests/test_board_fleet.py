import json
import os
import sys

from helpers import DAY, FIX, Env

from daybook.board.modules import fleet as F


class FleetTest(Env):
    def collect(self):
        F._cache.clear()
        return F.collect({})

    def test_services_off_by_default(self):
        sv = self.collect()["services"]
        self.assertTrue(sv["off"])
        self.assertEqual(sv["rows"], [])

    def test_services_file(self):
        os.environ["DAYBOOK_SERVICES_FILE"] = str(FIX / "services.json")
        sv = self.collect()["services"]
        self.assertEqual((sv["ok"], sv["drift"], sv["down"]), (1, 1, 1))
        self.assertEqual([r["label"] for r in sv["rows"]], ["queue", "backup", "web"])  # worst first, retired gone
        backup = sv["rows"][1]
        self.assertEqual((backup["dot"], backup["open_issues"]), ("warn", 1))
        self.assertNotIn("https://", backup["note"])
        self.assertEqual(sv["checked_at"], "2026-03-03T08:55:00-07:00")

    def test_services_command(self):
        out = {"services": [{"label": "cmd-svc", "verdict": "DOWN", "issues": []}]}
        os.environ["DAYBOOK_SERVICES_CMD"] = f"{sys.executable} -c 'print({json.dumps(json.dumps(out))})'"
        sv = self.collect()["services"]
        self.assertEqual((sv["down"], sv["rows"][0]["label"], sv["rows"][0]["dot"]), (1, "cmd-svc", "bad"))
        os.environ["DAYBOOK_SERVICES_CMD"] = f"{sys.executable} -c 'print(1/0)'"
        self.assertIn("unreadable", self.collect()["services"]["error"])

    def test_file_wins_over_command(self):
        os.environ["DAYBOOK_SERVICES_FILE"] = str(FIX / "services.json")
        os.environ["DAYBOOK_SERVICES_CMD"] = "/nonexistent/never-run"
        self.assertEqual(self.collect()["services"]["ok"], 1)

    def test_devices_without_probing(self):
        reg = self.tmp / "reg" / "devices"
        reg.mkdir(parents=True)
        (reg / "a.toml").write_text('hostname = "a"\nrole = "hub"\nip = "192.0.2.1"\nassume_up = true\n')
        (reg / "b.toml").write_text('hostname = "b"\nrole = "gpu"\ntailscale_ip = "192.0.2.2"\nassume_up = false\n')
        (reg / "c.toml").write_text('hostname = "c"\nrole = "laptop"\nip = "192.0.2.3"\n')
        (reg / "bad.toml").write_text('hostname = \n')
        os.environ["DAYBOOK_REGISTRY"] = str(self.tmp / "reg")
        self.session("hd-x", DAY.timestamp(), host="hub")
        devs = self.collect()["devices"]
        self.assertEqual([(d["hostname"], d["ip"], d["up"], d["sessions"]) for d in devs],
                         [("a", "192.0.2.1", True, 1), ("c", "192.0.2.3", None, 0), ("b", "192.0.2.2", False, 0)])

    def test_probe_is_gated(self):
        os.environ["DAYBOOK_PROBE_DEVICES"] = "1"
        called = []
        real = F.reachable
        F.reachable = lambda ip, *a, **k: called.append(ip) or True
        try:
            devs = self.collect()["devices"]
        finally:
            F.reachable = real
        self.assertEqual(called, ["127.0.0.1"])
        self.assertTrue(devs[0]["up"])

    def test_no_registry(self):
        os.environ["DAYBOOK_REGISTRY"] = ""
        self.assertEqual(self.collect()["devices"], [])
