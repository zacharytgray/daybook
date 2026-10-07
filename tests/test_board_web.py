# the page's own logic, run under node against a stub board. skipped where there is no node
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS = Path(__file__).resolve().parent / "js"
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "no node on PATH")
class WebTest(unittest.TestCase):
    def test_agent_actions(self):
        p = subprocess.run([NODE, str(JS / "agent_actions.js")], capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("agent actions: ok", p.stdout)

    def test_scripts_parse(self):
        for f in [ROOT / "web" / "app.js"] + sorted((ROOT / "web" / "modules").glob("*.js")):
            p = subprocess.run([NODE, "--check", str(f)], capture_output=True, text=True, timeout=30)
            self.assertEqual(p.returncode, 0, f"{f.name}: {p.stderr}")


class PageTest(unittest.TestCase):
    def test_no_fixed_zone_or_place_in_the_page(self):
        # every clock reads the configured zone; the page names no place of its own
        for f in [ROOT / "web" / "app.js"] + sorted((ROOT / "web" / "modules").glob("*.js")):
            src = f.read_text()
            self.assertNotRegex(src, r"timeZone: '[A-Z]", f.name)
            self.assertNotIn("new Date().toISOString()", src, f.name)

    def test_no_inline_script_or_style(self):
        page = (ROOT / "web" / "index.html").read_text()
        self.assertNotRegex(page, r"<script>(?!</script>)|<script(?![^>]*\bsrc=)[^>]*>")
        self.assertNotRegex(page, r"\sstyle=")
        self.assertNotRegex(page, r"https?://")
