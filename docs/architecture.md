# Architecture

Daybook is two small programs that share one folder of settings and one data contract.

- **The brief** (`daybook/brief.py`) gathers the day once each morning, asks a model to write
  the words, and draws a self-contained HTML page (and a PDF when Chrome is around).
- **The board** (`daybook/board/`) is a live page you keep open. It reads the latest brief from
  disk, adds what is happening now, and lets you mark things done or hand a to-do to an agent.

Both are Python 3.11+ standard library only. There is no build step, no package to install and
no database server. The board stores its few writes in SQLite.

```
            each morning                                   all day
  ┌──────────────────────────────┐            ┌──────────────────────────────────────┐
  │ daybook brief generate        │            │ daybook board serve (127.0.0.1:8740)  │
  │                               │            │                                      │
  │ code gathers ─┐               │  briefs/   │ modules: today, agent, fleet          │
  │  school folder│               │  <date>/   │  today  <- brief.json, context.json   │
  │  git activity │──▶ context ──▶│──────────▶ │  agent  <- sessions/, ended/, reports/│
  │  session notes│     json      │ brief.json │  fleet  <- devices/*.toml, services   │
  │  pull requests│      │        │ context    │                                      │
  │  weather, news│      ▼        │ brief.html │ writes: data/daybook.db               │
  │  marks.json   │  claude -p    │            │         data/marks.json  ◀───────────┼──┐
  │               │  (read-only)  │            │         data/today.md                │  │
  │               │      │        │            │         data/requests.log            │  │
  │               │      ▼        │            │                                      │  │
  │ code draws ◀── brief.json     │            │ hand-off ─▶ webhook | sms: | copy    │  │
  └──────────────────────────────┘            └──────────────────────────────────────┘  │
             ▲                                                                           │
             └─────────────── tomorrow's brief skips what you marked ────────────────────┘
```

## The brief

1. **Gather (code).** Each source is an adapter that is off until its setting is set: the school
   folder, pull requests through `gh`, agent session reports, commit subjects from a folder of git
   repos, weather from the US National Weather Service, AI news feeds, an approved second mailbox,
   and the board's marks. Code trims all of it into `context.json`.
2. **Write (model).** One fresh `claude -p` run with `--permission-mode dontAsk`, a read-only tool
   allowlist (calendar and mail reads, Todoist reads, web search, fetches limited to weather and
   news domains), a denylist of every write tool as a second wall, hooks off, and no session
   persistence. It returns JSON against `prompt/schema.json`. The run is refused if Claude reports
   an API key as its auth source, unless you turn that check off.
3. **Clean (code).** Em dashes are scrubbed, news must be dated and linked from a primary source,
   suggested hand-off settings are checked against the allowed roots, Todoist rows that mirror
   school files are dropped, and anything you marked on the board is dropped.
4. **Draw (code).** Every visual is code: the generated print at the top (season and forecast pick
   the inks, the near hill rises with each event, the sun sits where it will be at 8 AM), the day
   ribbon with overlap lanes and open blocks, the sections, and five daily puzzles plus a weekly
   crossword. The page is one HTML file with the font and scripts inlined and no outside requests.

`render` redraws from a saved `brief.json` and `context.json` with no model and no network. The
demo uses it.

## The board

- `daybook/board/server.py` is a `ThreadingHTTPServer`. The page in `web/` is only a client of
  its JSON API: `GET /api/state?since=N` returns what changed since a sequence number, and
  `GET /api/events` is a server-sent event stream that says when to ask again.
- Modules are one `collect(ctx)` in `daybook/board/modules/<name>.py` plus one `render()` in
  `web/modules/<name>.js`, listed once in `daybook/board/modules/__init__.py`. A module that throws
  shows "unavailable: reason" in its tile and never breaks the page.
- Items (to-dos) are rebuilt from the latest brief on every tick and never stored. Only marks and
  hand-off requests are stored, in `data/daybook.db`, with one global sequence number that every
  write bumps.
- A tick every 15 seconds links sent requests to the agent session that picked them up, expires
  requests nobody confirmed, refreshes the modules and rewrites `data/today.md` at most every five
  minutes.
- Layout is "three rooms": Today, the agent, and the fleet. On a desktop they are one bento grid of
  tiles; under 760px wide only one room shows, behind a tab bar.

## Safety model

- Both servers bind `127.0.0.1` unless you choose another host.
- Board writes need JSON, the per-start token from the page, and a same-origin `Origin` header.
  Requests whose `Host` is not an IP, `localhost`, a bare name or a name you allowed get 421, which
  blocks DNS rebinding. Strict CSP, no CORS, a 16 KB body cap.
- Every side effect is off by default: no messages, no webhook, no Todoist writes, no session
  stop or revive. With none configured, "Start" produces a request text for you to copy.
- Session metadata passes through a field whitelist. Report lines with money, and any excerpt that
  touches grading, students or scores, never reach the page. Private links and ids are scrubbed
  from everything that leaves the page.

See `docs/data-contracts.md` for the files and payloads, and `docs/privacy-and-publishing.md`
for what stays private.
