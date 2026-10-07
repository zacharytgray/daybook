# the one store the board writes: marks, requests, a global seq. marks.json is a contract the brief reads
import datetime as dt
import json
import sqlite3
import threading
from pathlib import Path

from .. import config
from ..common import atomic_write, item_id, norm
from . import iso

MARK_STATES = ("done", "snoozed", "dismissed")
# prefilled: messages opened, not known to be sent. copy: nothing sent, the text is on the page to copy.
# not_sent: you said so, or 30 min passed. no_session: the webhook took it but no session showed up in 10 min
REQUEST_STATUS = ("sent", "prefilled", "copy", "not_sent", "started", "waiting", "done", "failed", "no_session")

SCHEMA = """
create table if not exists meta (k text primary key, v integer not null);
create table if not exists marks (item_id text primary key, title text, norm text, source text, ref text,
  state text not null, until text, note text, at text, by text, seq integer, todoist_id text default '',
  todoist_sync text default '');
create table if not exists requests (id integer primary key autoincrement, item_id text, title text, runner text,
  model text, where_ text, reach text, text text, status text, session_name text, at text, by text, seq integer,
  error text, via text default '');
insert or ignore into meta (k, v) values ('seq', 0);
"""


class Store:
    def __init__(self, data_dir):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        # the brief reads this file; DAYBOOK_MARKS moves it
        self.marks_path = config.path("DAYBOOK_MARKS") or self.dir / "marks.json"
        self.db = sqlite3.connect(self.dir / "daybook.db", check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        with self.lock:
            self.db.executescript(SCHEMA)

    def close(self):
        with self.lock:
            self.db.close()

    # every write bumps one global counter; clients ask for changes since a number
    def seq(self):
        with self.lock:
            return self.db.execute("select v from meta where k='seq'").fetchone()[0]

    def bump(self):
        with self.lock:
            self.db.execute("update meta set v = v + 1 where k='seq'")
            s = self.seq()
            self.changed.notify_all()
            return s

    def wait(self, since, timeout):
        """block until seq passes since or timeout; returns the current seq."""
        with self.changed:
            self.changed.wait_for(lambda: self.seq() > since, timeout)
            return self.seq()

    # ---------- marks ----------

    def marks(self):
        with self.lock:
            return [dict(r) for r in self.db.execute("select * from marks order by at")]

    def mark(self, iid):
        with self.lock:
            r = self.db.execute("select * from marks where item_id=?", (iid,)).fetchone()
            return dict(r) if r else None

    def set_sync(self, iid, todoist_id, sync):
        """what todoist said when this mark was made: {ok, recurring, message}"""
        with self.lock:
            s = self.bump()
            self.db.execute("update marks set todoist_id=?, todoist_sync=?, seq=? where item_id=?",
                            (todoist_id or "", json.dumps(sync), s, iid))
            return s

    def set_mark(self, item, state, until=None, note="", by="laptop", at=None):
        """item: {id?, title, source, ref}. state open removes the mark."""
        iid = item.get("id") or item_id(item.get("title", ""))
        at = at or config.now()
        with self.lock:
            s = self.bump()
            if state == "open":
                self.db.execute("delete from marks where item_id=?", (iid,))
            else:
                if state not in MARK_STATES:
                    raise ValueError(f"bad state {state}")
                self.db.execute(
                    "insert or replace into marks (item_id, title, norm, source, ref, state, until, note, at, by, seq) "
                    "values (?,?,?,?,?,?,?,?,?,?,?)",
                    (iid, item.get("title", ""), norm(item.get("title", "")), item.get("source", ""),
                     str(item.get("ref", "") or ""), state, until or "", note or "", iso(at), by, s))
            self.write_marks_json(at)
            return s

    def write_marks_json(self, at=None):
        out = [{"id": m["item_id"], "title": m["title"], "norm": m["norm"], "source": m["source"], "ref": m["ref"],
                "state": m["state"], "until": m["until"], "at": m["at"]} for m in self.marks()]
        atomic_write(self.marks_path, json.dumps({"updated": iso(at or config.now()), "marks": out}, indent=1) + "\n")

    # ---------- requests ----------

    def add_request(self, r, by="laptop", at=None):
        with self.lock:
            s = self.bump()
            cur = self.db.execute(
                "insert into requests (item_id, title, runner, model, where_, reach, text, status, session_name, at, by, "
                "seq, error, via) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (r.get("item_id", ""), r.get("title", ""), r["runner"], r.get("model", ""), r.get("where", ""),
                 r["reach"], r["text"], r["status"], "", iso(at or config.now()), by, s, r.get("error", ""),
                 r.get("via", "")))
            return cur.lastrowid

    def update_request(self, rid, **fields):
        allowed = {"status", "session_name", "error", "via", "at"}
        fields = {k: v for k, v in fields.items() if k in allowed}
        if fields.get("status") and fields["status"] not in REQUEST_STATUS:
            raise ValueError("bad status")
        with self.lock:
            s = self.bump()
            sets = ", ".join(f"{k}=?" for k in fields) + ", seq=?"
            self.db.execute(f"update requests set {sets} where id=?", (*fields.values(), s, rid))
            return s

    def requests(self, hours=72):
        cutoff = iso(config.now() - dt.timedelta(hours=hours))
        with self.lock:
            rows = self.db.execute("select * from requests where at >= ? or status in "
                                   "('sent','prefilled','copy','started','waiting') order by id desc limit 50", (cutoff,))
            return [dict(r) for r in rows]

    def request(self, rid):
        with self.lock:
            r = self.db.execute("select * from requests where id=?", (rid,)).fetchone()
            return dict(r) if r else None


def mark_hides(mark, t=None):
    """done and dismissed hide for good; snoozed hides until its time."""
    if not mark:
        return False
    if mark["state"] in ("done", "dismissed"):
        return True
    try:
        until = dt.datetime.fromisoformat(mark.get("until") or "")
    except ValueError:
        return True
    if until.tzinfo is None:
        until = until.replace(tzinfo=config.tz())
    return (t or config.now()) < until


def tomorrow_morning(t=None):
    t = t or config.now()
    return dt.datetime.combine(t.date() + dt.timedelta(days=1), dt.time(5, 0), config.tz())
