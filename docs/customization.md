# Customization

Settings come from the environment, then from `.env` in the repo root (or the file named by
`DAYBOOK_ENV_FILE`), then from the defaults in `daybook/config.py`. The real environment wins.
In an env file, a value starting with `./` or `../` resolves from the file's own folder.
`.env.example` lists every setting with a one-line note. `python3 bin/daybook config` prints what
is in effect.

An empty value means off (for a source or a side effect) or the default (for a name or a path).

## Who and where

```bash
DAYBOOK_USER_NAME=Mara              # request texts say "Mara asks"; the prompt calls the reader Mara
DAYBOOK_AGENT_NAME=Juniper          # the agent room, the panel, "Hand to Juniper"
DAYBOOK_TITLE="Mara's desk"         # the board's masthead and tab title
DAYBOOK_BRIEF_TITLE="Good Morning"  # the brief's masthead
DAYBOOK_TZ=Europe/Lisbon            # every date and clock, on the server and in the page
DAYBOOK_LOCATION=Lisbon             # a label only
DAYBOOK_LAT=38.72                   # sunrise, sunset and the sun's arc on the print
DAYBOOK_LON=-9.14
DAYBOOK_FIRST_EDITION=2026-01-05    # issue numbers count from here
```

Without a location the sky uses a fixed 6:30 AM to 6:30 PM day. The weather adapter
(`DAYBOOK_WEATHER=nws`) also needs the coordinates and only covers the United States. Outside the
US, leave it off; the model can still fetch a forecast if your prompt asks for one.

Tell the model about yourself in `prompt/about.md` (git-ignored). Keep it to a few short
paragraphs: what you do, what is urgent, what news you care about, when you exercise.

## Paths

```bash
DAYBOOK_DATA=~/.local/share/daybook          # the board's store, marks.json, today.md
DAYBOOK_BRIEFS=~/.local/share/daybook/briefs # one folder per date
DAYBOOK_SCHOOL=~/notes/school                # see docs/data-contracts.md for the layout
DAYBOOK_PROJECTS=~/code                      # a folder of git repos
DAYBOOK_WORK_ROOTS=~/notes:~/writing         # more folders a hand-off may run in (':' between them)
DAYBOOK_SESSIONS=~/.agents/dispatch          # sessions/, ended/, reports/
DAYBOOK_REGISTRY=~/infra/registry            # devices/*.toml
DAYBOOK_SERVICES_FILE=~/infra/services.json
DAYBOOK_MODELS=~/infra/models.json
```

A hand-off may run only in a folder at or under `DAYBOOK_PROJECTS`, a `DAYBOOK_WORK_ROOTS` entry,
or a class `workdir` that sits inside one of those. Symlinks and `..` are resolved first. The where
picker offers each repo, each root and each class workdir. Anything else is refused and the panel
tells you to send it to your agent yourself.

## Serving

```bash
DAYBOOK_HOST=127.0.0.1          # both servers
DAYBOOK_BOARD_PORT=8740
DAYBOOK_BRIEF_PORT=8735
DAYBOOK_BRIEF_WEB=http://127.0.0.1:8735   # the link the board and deliver use for the brief
DAYBOOK_ALLOWED_HOSTS=desk.example.ts.net # dotted Host names the board accepts
```

To reach the board from your phone, bind a private interface (a tailnet address, for example)
and list its DNS name in `DAYBOOK_ALLOWED_HOSTS`. Do not expose it to the open internet: the board
has no login, only a per-start token that the page itself carries.

## Sources for the brief

```bash
DAYBOOK_CALENDAR_ID=primary
DAYBOOK_TODOIST_PROJECT=              # a Todoist project id; empty reads the Inbox
DAYBOOK_GH=/usr/local/bin/gh
DAYBOOK_WEATHER=nws
DAYBOOK_NEWS_FEEDS=~/notes/feeds.txt       # start from prompt/news-feeds.example.txt
DAYBOOK_MAIL_HANDOFF=~/notes/mail-handoff.json
DAYBOOK_EXTRA_READ_TOOLS=mcp__notes__search_notes   # the tool name must start or end with a read verb (get, list, search, read, ...)
DAYBOOK_CLAUDE=~/.local/bin/claude
DAYBOOK_CLAUDE_MODEL=opus
DAYBOOK_REQUIRE_SUBSCRIPTION=1
```

Each unset source shows "off" in the brief's Sources section and never counts as a gap.

## Side effects

All off by default. Turn on only what you use.

```bash
DAYBOOK_WEBHOOK_URL=http://127.0.0.1:8644/webhooks/daybook   # your agent gateway's webhook route
DAYBOOK_WEBHOOK_SECRET=...                                   # keep it in .env, never in git
DAYBOOK_AGENT_SMS=agent@example.com                          # an sms: or iMessage address
DAYBOOK_DISPATCH_CMD="/usr/local/bin/my-dispatch"            # gets "stop <name>" or "revive <name>"
DAYBOOK_SESSION_PREFIX=hd-                                   # session handles look like hd-some-task
TODOIST_API_TOKEN=...                                        # close and reopen Todoist tasks on marks
DAYBOOK_PROBE_DEVICES=1                                      # TCP/22 checks for the fleet room
```

## Adding a board module

1. Write `daybook/board/modules/<name>.py` with `collect(ctx)` that returns a json-able dict.
   `ctx` has `store` and `now`. Raise if the source is missing; the tile shows the reason.
2. Write `web/modules/<name>.js` that sets `window.Board.modules.<name> = { render: render }` with
   `render(el, data)`, like `web/modules/fleet.js`, and builds DOM with the page's `Board.h()` helper (no inline styles in HTML, no outside
   requests; the CSP blocks both).
3. Add one line to `MODULES` in `daybook/board/modules/__init__.py` with its name, title and room.
4. Give its tiles a grid area in `web/app.css` for the 2-column and 12-column layouts.
5. Add a test next to `tests/test_board_*.py` and demo data if the demo should show it.

## Examples

`examples/` has starting points: `minimal.env` (just names and a zone), `agent-gateway.env`
(webhook, dispatch command, models), `models.json`, `services.json` and `devices/hub.toml`.
