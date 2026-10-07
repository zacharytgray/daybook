# the publication gate as a test: the shipped tree carries no personal data, and the scanner catches what it should.
# bad samples are put together at run time so this file passes its own scan
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import privacy_audit as A  # noqa: E402


class TreeIsClean(unittest.TestCase):
    def test_no_findings_in_the_shipped_tree(self):
        probs = A.audit(history=True)
        self.assertEqual(probs, [], "\n".join(f"{r}: {w}" for r, w in probs))


class ScannerCatches(unittest.TestCase):
    def scan(self, text, rel="x.md"):
        return A.scan_text(rel, text, set())

    def test_tailnet_and_private_ips(self):
        self.assertTrue(any("tailnet" in x for x in self.scan("bind " + ".".join(["100", "101", "102", "103"]))))
        self.assertTrue(self.scan("ssh " + ".".join(["10", "0", "0", "5"])))
        self.assertEqual(self.scan("demo 192.0.2.10 and 127.0.0.1"), [])

    def test_home_paths_emails_phones(self):
        self.assertTrue(self.scan("/Us" + "ers/somebody/code"))
        self.assertTrue(self.scan("mail me at person" + "@" + "gmail.com"))
        self.assertEqual(self.scan("agent@example.com"), [])
        self.assertTrue(self.scan("call " + "-".join(["555", "867", "5309"])))

    def test_urls_secrets_dashes(self):
        self.assertTrue(self.scan("see https:" + "//private.internal/thing"))
        self.assertEqual(self.scan("see https://example.com/thing"), [])
        self.assertTrue(self.scan("token ghp_" + "a" * 30))
        self.assertTrue(self.scan("a " + chr(0x2014) + " b"))

    def test_denylist_by_hash(self):
        A.DENY.add(A.h("lakesidecanary"))
        try:
            self.assertTrue(self.scan("hello Lakesidecanary-team"))
            self.assertEqual(self.scan("hello Lakesidecanary", rel="assets/puzzles/x.txt"), [])
        finally:
            A.DENY.discard(A.h("lakesidecanary"))

    def test_png_metadata_chunks(self):
        import struct
        import zlib

        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", b"\0" * 13) + chunk(b"tEXt", b"Author\0x") + chunk(b"IEND", b"")
        self.assertIn(b"tEXt", A.png_chunks(png))


if __name__ == "__main__":
    unittest.main()
