# shared bits for the brief and the board: ids, urls, frontmatter, scrubbing, files
import hashlib
import json
import os
import re
from pathlib import Path


def norm(s):
    # the brief and the board both match on this; marks.json depends on it
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


def item_id(title):
    return hashlib.sha1(norm(title).encode()).hexdigest()[:12]


def safe_url(u):
    return u if isinstance(u, str) and re.match(r"^https://[^\s\"'<>]+$", u) else ""


def split_frontmatter(path):
    text = Path(path).read_text(errors="replace")
    m = re.match(r"^---\n(.*?)\n---\n?", text, re.S)
    out = {}
    if not m:
        return out, text
    for line in m.group(1).splitlines():
        if ":" not in line or line.startswith((" ", "\t", "#")):
            continue
        k, v = line.split(":", 1)
        v = v.strip()
        q = re.match(r'^(["\'])(.*?)\1', v)
        out[k.strip()] = q.group(2) if q else re.sub(r"\s+#.*$", "", v).strip()
    return out, text[m.end():]


# private links, ids and tokens never reach a prompt, a page, the digest or a log
PRIVATE = [r"https?://claude\.ai/\S+", r"https?://chatgpt\.com/\S+",
           r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
           r"\bsession_[A-Za-z0-9]+\b", r"\b(?:sk|ghp|gho|xox[bp])-?[A-Za-z0-9_-]{16,}\b"]
MONEY = re.compile(r"(?i)(?:[$€£¥]\s?\d|\b\d[\d,]*(?:\.\d+)?\s?(?:usd|dollars?|bucks|cents?)\b|¢|\busd\b)")
CTRL = re.compile(r"[\x00-\x1f\x7f\u0085  ]")


def scrub_private(text):
    for pat in PRIVATE:
        text = re.sub(pat, "[link removed]", text)
    return text


def has_money(text):
    return bool(MONEY.search(str(text or "")))


def one_line(text, cap=300):
    """no newlines or control characters, so a field cannot fake another line of a request."""
    return re.sub(r"\s+", " ", CTRL.sub(" ", str(text or ""))).strip()[:cap]


def plain(text):
    """for text that leaves the page: no urls, no ids, no money, no em-dashes."""
    text = scrub_private(str(text or ""))
    text = re.sub(r"https?://\S+", "[link removed]", text)
    text = "\n".join("[line removed]" if has_money(line) else line for line in text.split("\n"))
    return text.replace("\u2014", ", ").replace("\u2013", "-")


def scrub_dashes(obj):
    """no em-dashes anywhere. en-dash ranges are fine."""
    if isinstance(obj, str):
        return re.sub(r"^, ", "", re.sub("\\s*[\u2014\u2015\u2e3a\u2e3b]\\s*", ", ", obj))
    if isinstance(obj, list):
        return [scrub_dashes(x) for x in obj]
    if isinstance(obj, dict):
        return {k: (v if k == "url" else scrub_dashes(v)) for k, v in obj.items()}
    return obj


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def short_path(p):
    p, home = str(p or ""), str(Path.home())
    return "~" + p[len(home):] if p.startswith(home) else p
