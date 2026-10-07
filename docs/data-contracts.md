# Data contracts

Every file and payload daybook reads or writes. The demo folder has a working example of each
input; the paths below point at it.

## Inputs you provide

### The school folder (`DAYBOOK_SCHOOL`)

```
classes/<code>/class.md                 one per class; a folder starting with _ is skipped
classes/<code>/assignments/<slug>.md    one per assignment or grading job
classes/<code>/lectures/YYYY-MM-DD-*.md optional lecture notes; the brief reads the last two days
inbox/decisions.md                      optional; each "## " heading is one decision you owe
```

`class.md` frontmatter (`demo/school/classes/cs-1300/class.md`):

| key | meaning |
|---|---|
| `code` | the class code shown everywhere, e.g. `CS-1300` |
| `name` | the class name |
| `role` | `student` or `ta` |
| `schedule` | `"TR 13:00-14:15"`: day letters `MTWRFSU` and a 24h range |
| `starts`, `ends` | the term, `YYYY-MM-DD`; meetings outside it are skipped |
| `workdir` | optional folder for this class's work; relative paths resolve against the school folder |

A `## Office hours` section in a TA class becomes a TA duty line.

Assignment frontmatter (`demo/school/classes/cs-1300/assignments/grade-lab-8.md`):

| key | meaning |
|---|---|
| `title` | shown as written |
| `due` | `YYYY-MM-DD` (end of day) or `YYYY-MM-DDTHH:MM` |
| `status` | `open`, or anything else (`submitted`, `graded`) to hide it |
| `grading` | `true` on a grading job you owe as a TA |
| `todoist_task_id` | optional; a Todoist task with this id is dropped from the brief as a duplicate |

Items due within 14 days show in the brief; within 7 days (plus anything overdue) they become
board to-dos. In a TA class, open assignments without `grading: true` are student deadlines and
never count as your work.

### Agent sessions (`DAYBOOK_SESSIONS`)

```
sessions/<prefix><name>.json   live sessions
ended/<prefix><name>.json      finished ones (sessions/ended/ also works)
reports/<prefix><name>.md      what the session reported; the latest "## " section is shown
```

Session json (`demo/dispatch/sessions/hd-trailmix-map-tiles.json`). Only these fields are read;
anything else in the file is ignored and never leaves the server:

| field | meaning |
|---|---|
| `name` | the handle, `<prefix>` plus lowercase letters, digits and dashes. The prefix must be a lowercase letter, up to 15 more letters or digits, then a dash; anything else falls back to `hd-` |
| `task` | the first line is shown; a line with a money amount is hidden |
| `cwd`, or `repo` plus `branch` | where it runs; shown as `repo on branch` when both are set |
| `host` | a device role or hostname from the registry |
| `backend` | `claude`, `codex`, or empty |
| `model` | free text |
| `status` | `busy`, `starting`, `idle`, `waiting` |
| `waiting_for` | `permission` makes the card say so |
| `started_at`, `ended_at` | unix seconds |
| `url` | a Remote Control link, shown only when it is on `claude.ai` or `chatgpt.com` |
| `transport` | `codex-native` sessions get no attach line |

### Devices (`DAYBOOK_REGISTRY/devices/*.toml`)

```toml
hostname = "desk"
role = "hub"            # hub, laptop, gpu, or your own word
ip = "192.0.2.10"       # tailscale_ip is read too
ssh_user = "avery"      # optional; without it there is no Copy SSH line
tmux = "/usr/local/bin/tmux"   # optional
assume_up = true        # shown when DAYBOOK_PROBE_DEVICES=0
```

### Services (`DAYBOOK_SERVICES_FILE`, or the stdout of `DAYBOOK_SERVICES_CMD`)

```json
{"checked_at": "2026-04-14T10:15:00-06:00",
 "services": [{"label": "nightly-backup", "verdict": "drift",
               "issues": [{"status": "open", "summary": "The last backup finished two days ago."}]}]}
```

`verdict` is `ok`, `drift` or `down`. A service with `"status": "retired"` is skipped. The first
open issue is shown, scrubbed of links and money.

### Models (`DAYBOOK_MODELS`)

```json
{"claude": [{"id": "opus", "label": "Opus", "default": true}],
 "codex":  [{"id": "gpt-5-codex", "label": "GPT-5 Codex"}]}
```

Malformed rows are dropped. With no `default`, the first row is the default.

## Between the brief and the board

### `briefs/<date>/brief.json`

What the model returns, after code cleans it. The schema is `prompt/schema.json`; the demo is
`demo/briefs/2026-04-14/brief.json`. The board reads `headline`, `opening`, `focus`,
`next_actions`, `events`, `todoist_schedule` and `tomorrow`. Each next action may carry:

```json
"handoff": {"runner": "agent|claude|codex", "model": "default or an id", "where": "", "reach": "draft|branch|ship", "prompt": "one or two sentences"}
```

`where` is empty or an absolute folder inside the allowed roots; anything else is cleared.

### `briefs/<date>/context.json`

What code gathered: `school`, `prs`, `projects` (session `reports`, `sessions`, `git`), `mail`,
`news`, `weather`, `marks`, `gathered_at`, and `off` (the adapters that were not configured). The
board reads `school` (class meetings, due soon, Todoist ids that mirror school files) and
`weather`.

### `data/marks.json` (written by the board, read by the brief)

```json
{"updated": "2026-04-14T10:21:00-06:00",
 "marks": [{"id": "3f2a…", "title": "Return library books", "norm": "return library books",
            "source": "Todoist", "ref": "…", "state": "done", "until": "", "at": "2026-04-14T10:21:00-06:00"}]}
```

`state` is `done`, `snoozed` (hidden until `until`) or `dismissed`. `id` is the first 12 hex
digits of the SHA-1 of `norm`, and `norm` is the title lowercased with every run of other
characters turned into one space. The brief drops next actions and Todoist rows whose `norm` or
Todoist id matches a mark from the last 14 days (or a snooze still running). The file is rewritten
atomically on every mark change.

## Written by the board

| file | what |
|---|---|
| `data/daybook.db` | SQLite: `marks`, `requests`, and one global sequence number |
| `data/today.md` | a short plain digest of the day for agents to read; no links, ids, money or grades |
| `data/requests.log` | one json line per request, mark sync, archive or revive; links scrubbed |

## The board's HTTP API

| method and path | what |
|---|---|
| `GET /health` | `{"ok": true, "seq": N}` |
| `GET /api/state[?since=N]` | `seq`, `layout`, `modules` (only those changed since N), `marks`, `requests`, `models`, `config` |
| `GET /api/events` | server-sent events; `event: seq` each time something changes |
| `GET /api/token` | the current write token, same origin only |
| `POST /api/marks` | `{title, state: done|snoozed|dismissed|open, until?, source?, ref?, item_id?}` |
| `POST /api/requests` | `{item_id, title, runner, model, where, reach, note, source, ref, changed[], suggested_by}` |
| `POST /api/requests/sent` | `{id, sent: true|false}` after a prefilled or copied request |
| `POST /api/sessions/archive` | `{name}`; 403 unless `DAYBOOK_DISPATCH_CMD` is set |
| `POST /api/sessions/revive` | `{name}`; 403 unless `DAYBOOK_DISPATCH_CMD` is set |

Every POST needs `Content-Type: application/json`, the `X-Daybook-Token` header and, when the
browser sends one, a same-origin `Origin`.

`config` in `/api/state` is what the page needs to draw: `title`, `user`, `agent`, `tz`,
`location`, `now` (set only when the clock is frozen), `brief_web`, `prefix`, `transport`
(`webhook`, `sms` or `copy`) and `actions.dispatch`.

Request statuses: `sent`, `prefilled` (an sms link opened), `copy` (shown for you to copy),
`not_sent` (you said so, or 30 minutes passed), `started`, `waiting`, `done`, `failed`,
`no_session` (a webhook took it but no session appeared within 10 minutes).
