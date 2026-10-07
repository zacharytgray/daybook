# Integrations

Every integration is optional and off until its setting is set. The demo uses none of them.
"Supported" below means the code path exists and has tests with stubbed outside calls. It does
not mean every service, account type or platform was tried end to end.

## Platforms

| | status |
|---|---|
| macOS | the original home of both programs; everything works, including the PDF check |
| Linux | the board, `brief render` and the demo work; the PDF works with Chrome or Chromium; the PDF text check (`tools/pdfcheck.swift`) is skipped |
| Windows | not tested; `brief generate` takes a lock with `fcntl`, which Windows lacks |
| Python | 3.11 or newer (`tomllib`, `zoneinfo`); standard library only |
| Node | only for `tools/screenshots.mjs` and the JS tests; 22 or newer |

## The model that writes the brief (Claude Code)

`daybook brief generate` runs the Claude Code CLI (`DAYBOOK_CLAUDE`, default `claude`) once, with
`DAYBOOK_CLAUDE_MODEL` (default `opus`). The calendar, mail and Todoist reads come from the MCP
connectors in your own Claude Code setup:

- calendar: the claude.ai Google Calendar connector, calendar `DAYBOOK_CALENDAR_ID`
- mail: the claude.ai Gmail connector
- tasks: a Todoist MCP server, project `DAYBOOK_TODOIST_PROJECT`

The tool allowlist and denylist live in `daybook/brief.py`. To give the model one more read-only
MCP tool, add its full name to `DAYBOOK_EXTRA_READ_TOOLS`. A name is accepted only when its tool
part starts or ends with a read verb (`get`, `list`, `search`, `read`, `fetch`, `query`, `find`,
`view`, `lookup`, `describe`) and contains no write word; whole servers, wildcards and built-in
tools are refused. That is a name check, not a guarantee, so never list a tool that can send,
write or delete. The
run refuses to start billing an API key unless `DAYBOOK_REQUIRE_SUBSCRIPTION=0`.

Write a short `prompt/about.md` (git-ignored) with what the model should know about you: what you
do, who your mail is from, what counts as urgent. `prompt/about.example.md` shows the shape.

## Sources the code reads

| source | setting | notes |
|---|---|---|
| school folder | `DAYBOOK_SCHOOL` | markdown with frontmatter, see `docs/data-contracts.md` |
| git activity | `DAYBOOK_PROJECTS` | commit subjects from the last 36 hours, per repo |
| agent session notes | `DAYBOOK_SESSIONS` | the latest section of each report in `reports/` |
| pull requests | `DAYBOOK_GH` | path to the `gh` CLI; your open PRs with checks and review state |
| weather | `DAYBOOK_WEATHER=nws` | US National Weather Service, needs `DAYBOOK_LAT` and `DAYBOOK_LON` |
| AI news | `DAYBOOK_NEWS_FEEDS` | a file of `name<TAB>url` feeds; start from `prompt/news-feeds.example.txt` |
| a second mailbox | `DAYBOOK_MAIL_HANDOFF` | a json file naming an approved connector command, below |
| marks | `DAYBOOK_MARKS` | the board's `marks.json`; defaults to `<DAYBOOK_DATA>/marks.json` |

### A second mailbox

Some mailboxes (a school or work account) cannot be read by the model's connectors, or policy
says their mail must not go to a cloud model. `DAYBOOK_MAIL_HANDOFF` points at a json file:

```json
{"approved": true, "command": ["/path/to/your-mail-digest", "--json"], "send_to_model": false}
```

The brief runs the command (90 s limit) and expects `{"fetched_at", "items": [{"kind", "title",
"from", "received", "due", "summary", "source"}]}` on stdout. With `send_to_model: false` the
items are listed on the page by code and the model only learns how many there were. Daybook never
logs in to anything itself.

## Handing to-dos to an agent

"Start" on the board builds a plain request text, the same shape as a text you would send your
agent yourself:

```
From Daybook, Avery asks: start a Claude Code session (model opus) for "Draft the lab 9 rubric".
Runner: suggested; route it as you see fit.
Where: /home/you/school/cs-1300 (suggested by the board; change it if wrong).
Reach: draft (write files only; never submit, send or push). Suggested.
Note: none.
```

How it travels, in order of preference:

1. **Webhook** (`DAYBOOK_WEBHOOK_URL`, `DAYBOOK_WEBHOOK_SECRET`). A POST of
   `{"text", "request_id"}` with `X-Webhook-Timestamp` and `X-Webhook-Signature-V2`, the hex
   HMAC-SHA256 of `"<timestamp>.<body>"`. This matches the generic webhook format of the Hermes
   agent gateway, and any receiver can verify it the same way.
2. **SMS link** (`DAYBOOK_AGENT_SMS`). The page opens `sms:<address>&body=<text>` so your phone or
   Mac opens Messages with the request typed out. You tap send, then tell the page whether you did.
3. **Copy** (the default). Nothing is sent. The page shows the text with a Copy button.

A receiver of the webhook should apply the same checks it applies to a message from you: a kill
switch, a rate limit, an audit log, and a refusal for anything that would normally need your
explicit yes. Daybook's own checks (allowed roots, known models, one-line fields) are a first
wall, not the only one.

`reach` is how far the work may go: `draft` writes files only, `branch` may commit on a branch but
never push, `ship` may push and deploy your own app. The agent decides how to honor it.

### Runners and models

The panel offers three runners: the agent itself, a Claude Code session, or a Codex session.
`DAYBOOK_MODELS` lists the models each runner may start:

```json
{"claude": [{"id": "opus", "label": "Opus", "default": true}, {"id": "sonnet", "label": "Sonnet"}],
 "codex":  [{"id": "gpt-5-codex", "label": "GPT-5 Codex", "default": true}]}
```

Requests naming a model outside this list are refused. With no file, the panel says the agent
picks.

### Seeing sessions, and archive and revive

`DAYBOOK_SESSIONS` points at a dispatch folder with `sessions/`, `ended/` and `reports/`. Any tool
that starts agent sessions can write it; the field list is in `docs/data-contracts.md`. The board
links each sent request to the session that picked it up (started within 30 minutes, and at least
two distinctive words of the to-do in the session's task line).

`DAYBOOK_DISPATCH_CMD` turns on Archive and Revive. Daybook runs `<cmd> stop <name>` (60 s) and
`<cmd> revive <name>` (150 s) with a fixed argument list and never adds flags that would skip your
dispatcher's own checks. Success is exit 0 with output starting `stopped` or `resumed`.

Copy SSH builds `ssh -t <ssh_user>@<ip> <tmux> attach -t <name>` for live sessions on a host listed
in the registry with an `ssh_user` and an `ip`.

## Todoist

With `TODOIST_API_TOKEN` set, marking a Todoist item done on the board closes the task (Todoist
API v1), and undo reopens it. Without the token the mark stays local and the page says so once.
A recurring task moves to its next date when closed, and reopening may not move it back.

## The fleet room

- devices: `DAYBOOK_REGISTRY/devices/*.toml` with `hostname`, `role` (`hub`, `laptop`, `gpu`, or
  your own), `ip`, optional `ssh_user`. The board checks TCP port 22 on each, unless
  `DAYBOOK_PROBE_DEVICES=0`, in which case an optional `assume_up = true|false` is shown.
- services: `DAYBOOK_SERVICES_FILE`, or `DAYBOOK_SERVICES_CMD` that prints the same json. See
  `docs/data-contracts.md`.

## Delivering the brief

`daybook brief deliver --date D` prints a caption and the page link (or `MEDIA:<pdf>` when the page
server is down) once per date, and nothing on later runs. Any scheduler that sends a command's
stdout as a message can deliver it: a Hermes cron job, a shell script with your messenger's CLI,
or plain cron and email. `deliver` itself sends nothing.

## Hermes, Claude Code, Codex

The original setup ran on the Hermes agent gateway with a dispatch plugin that starts Claude Code
and Codex sessions. Nothing in daybook needs Hermes. What daybook needs from any agent setup is:

- something that accepts the request text (webhook, a messaging address, or you pasting it)
- optionally, a folder where your session tool writes session metadata and reports
- optionally, a command that can stop and revive a session by name
