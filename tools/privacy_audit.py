#!/usr/bin/env python3
# the publication gate: scan every file git would ship (and the commit messages) for personal data.
#   python3 tools/privacy_audit.py            exit 1 and a list when anything needs a look
#   python3 tools/privacy_audit.py --history  also scan commit messages
# the name denylist is stored as sha256 hashes, so this file does not itself list anyone's details.
# add a term: python3 tools/privacy_audit.py --hash "term", then paste the hash into DENY.
import hashlib
import ipaddress
import re
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def h(term):
    return hashlib.sha256(term.lower().encode()).hexdigest()[:16]


# personal names, places, hostnames, private project names and class codes from the original setup.
# one hash per line in denylist.sha256 next to this file. hashes keep the list from being a list
# of the very details it guards; they do not stop someone who already knows a term from checking it.
DENY = {line.split("#")[0].strip() for line in (Path(__file__).with_name("denylist.sha256").read_text().splitlines())
        if line.split("#")[0].strip()}

# where a denylisted word is expected: the license's copyright line, and ordinary english words in the
# puzzle word lists (checked by hand; see THIRD_PARTY_NOTICES.md)
ALLOW = {
    "LICENSE": {"name"},
    "assets/puzzles/": {"word"},
}

DOC_NETS = [ipaddress.ip_network(n) for n in ("127.0.0.0/8", "0.0.0.0/32", "192.0.2.0/24", "198.51.100.0/24",
                                              "203.0.113.0/24")]
HOSTS_OK = {"example.com", "example.org", "example.net", "localhost", "127.0.0.1", "www.w3.org",
            "github.com/undercasetype/fraunces", "api.weather.gov", "forecast.weather.gov", "api.todoist.com",
            "api.open-meteo.com", "wttr.in", "scripts.sil.org", "openfontlicense.org", "claude.ai", "chatgpt.com",
            "todoist.com", "github.com", "docs.anthropic.com", "code.claude.com"}
SECRET = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|xox[bp]-[A-Za-z0-9-]{10,}|"
                    r"AKIA[0-9A-Z]{16})\b|-----BEGIN [A-Z ]*PRIVATE KEY-----")
PHONE = re.compile(r"(?<![\w.])(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}(?![\w.])")
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
URL = re.compile(r"https?://([A-Za-z0-9.-]+)(/[^\s\"'<>)]*)?")
IPV4 = re.compile(r"(?<![\w.])(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?![\w.])")
HOME = re.compile(r"(?:/Users/|/home/)([A-Za-z0-9._-]+)")
HOME_OK = {"you", "me", "user", "example", "runner", "name", "avery", "<you>", "USER"}
TMP = re.compile(r"/private/tmp/|/var/folders/")
WORD = re.compile(r"[a-z0-9]+(?:[-_.][a-z0-9]+)*")
TEXT_SKIP = (".woff2", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf")
PNG_BAD = {b"tEXt", b"iTXt", b"zTXt", b"eXIf", b"tIME"}


def files():
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-co", "--exclude-standard"],
                         capture_output=True, text=True, check=True).stdout.split("\n")
    return [f for f in out if f and (ROOT / f).is_file()]


def allowed(rel, kind):
    return any(rel == k or (k.endswith("/") and rel.startswith(k)) for k, kinds in ALLOW.items() if kind in kinds)


def host_ok(host, path):
    host = host.lower()
    if host in HOSTS_OK or host.endswith(".example.com") or host.endswith(".example"):
        return True
    full = (host + (path or "")).lower()
    return any(full.startswith(x) for x in HOSTS_OK if "/" in x)


def scan_text(rel, text, news_hosts):
    found = []
    low = text.lower()
    for w in set(WORD.findall(low)):
        for part in {w, *re.split(r"[-_.]", w)}:
            if part and h(part) in DENY:
                kind = "name" if rel == "LICENSE" else "word"
                if not allowed(rel, kind):
                    found.append(f"denylisted term (hash {h(part)})")
    if "—" in text:
        found.append("em dash")
    for m in SECRET.finditer(text):
        found.append("secret-shaped string")
    for m in PHONE.finditer(text):
        found.append(f"phone-shaped number {m.group(0)!r}")
    for m in EMAIL.finditer(text):
        dom = m.group(1).lower()
        if not (dom.startswith("example.") or dom.endswith(".example") or dom.endswith(".test") or dom == "localhost"):
            found.append(f"email address at {dom}")
    for m in URL.finditer(text):
        if not (host_ok(m.group(1), m.group(2)) or m.group(1).lower() in news_hosts):
            found.append(f"url host {m.group(1)}")
    for m in IPV4.finditer(text):
        try:
            ip = ipaddress.ip_address(m.group(1))
        except ValueError:
            continue
        if not any(ip in n for n in DOC_NETS):
            found.append(f"ip address {ip}" + (" (tailnet range)" if ip in ipaddress.ip_network("100.64.0.0/10") else ""))
    for m in HOME.finditer(text):
        if m.group(1) not in HOME_OK:
            found.append(f"home path for {m.group(1)!r}")
    if TMP.search(text):
        found.append("machine temp path")
    return found


def png_chunks(data):
    out, i = [], 8
    while i + 8 <= len(data):
        n, kind = struct.unpack(">I4s", data[i:i + 8])
        out.append(kind)
        i += 12 + n
    return out


def audit(history=False):
    news = ROOT / "prompt" / "news-domains.txt"
    news_hosts = {x.strip().lower() for x in news.read_text().split()} if news.exists() else set()
    feeds = ROOT / "prompt" / "news-feeds.example.txt"
    if feeds.exists():
        news_hosts |= {m.group(1).lower() for m in URL.finditer(feeds.read_text())}
    problems = []
    for rel in files():
        p = ROOT / rel
        if rel.endswith(".png"):
            bad = [k.decode() for k in png_chunks(p.read_bytes()) if k in PNG_BAD]
            if bad:
                problems.append((rel, f"png metadata chunks {bad}"))
            continue
        if rel.endswith(TEXT_SKIP):
            continue
        if rel in ("tools/privacy_audit.py", "tools/denylist.sha256"):
            continue
        try:
            text = p.read_text()
        except UnicodeDecodeError:
            problems.append((rel, "binary file not on the allowlist of binary types"))
            continue
        problems += [(rel, x) for x in sorted(set(scan_text(rel, text, news_hosts)))]
    if history:
        log = subprocess.run(["git", "-C", str(ROOT), "log", "--all", "--format=%H%n%B"], capture_output=True,
                             text=True).stdout
        problems += [("commit messages", x) for x in sorted(set(scan_text("commit messages", log, news_hosts)))]
    return problems


def main(argv):
    if argv[:1] == ["--hash"]:
        print(h(argv[1]))
        return 0
    probs = audit("--history" in argv)
    for rel, why in probs:
        print(f"{rel}: {why}")
    print(f"privacy audit: {len(probs)} finding{'s' if len(probs) != 1 else ''}", file=sys.stderr)
    return 1 if probs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
