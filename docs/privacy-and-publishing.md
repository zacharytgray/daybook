# Privacy, security and publishing

Daybook reads the most private parts of a day: calendar, mail, tasks, classes, what your agents
are doing. This page says what it keeps, what it never shows, and what to check before you
publish a fork, a screenshot or a bug report.

## What stays on your machine

These are git-ignored and never belong in a commit, an issue or a screenshot:

| path | holds |
|---|---|
| `.env` | your settings, including tokens and webhook secrets |
| `data/` | the board's SQLite store, `marks.json`, `today.md`, `requests.log` |
| `briefs/` | every generated brief: `context.json` has raw calendar, mail and session text |
| `prompt/about.md` | what you tell the model about yourself |
| `demo/.data/` | demo output (invented, but still not worth committing) |

## What never reaches the page

- Session metadata passes through a whitelist (name, task line, folder, host, backend, model,
  status, times, attach line, and a Remote Control link only when it is on `claude.ai` or
  `chatgpt.com`). Anything else in a session file, such as chat ids, conversation ids or delivery
  keys, is dropped where the file is read.
- Report lines with a money amount are dropped. A session whose name, task, folder or report
  touches grading, students or scores shows no excerpt at all.
- Text that leaves the page (`today.md`, `requests.log`, request texts) has links, ids, tokens and
  money lines scrubbed, and em dashes replaced.
- The brief's model sees school mail from a second mailbox only when that connector says
  `send_to_model: true`. Otherwise code lists the items and the model gets a count.

## Security defaults

- Both servers bind `127.0.0.1`. Binding anything wider is your choice, and then the board is only
  as private as that network. Use a private network such as a tailnet, never the open internet.
- Board writes need `Content-Type: application/json`, the per-start token from the page and a
  same-origin `Origin`. Unknown `Host` headers get 421. Strict CSP with no inline script, no CORS,
  a 16 KB body limit, `X-Frame-Options: DENY`.
- The brief's model run is read-only: `dontAsk` permission mode, an allowlist of read tools, a
  denylist of every write tool, hooks off, a throwaway working folder, and a check that refuses a
  run billed to an API key.
- Hand-offs never run anything on their own. They become a request text for your agent. Folders
  outside the allowed roots are refused. Archive and revive run only your configured dispatch
  command, with a fixed argument list (`stop <name>`, `revive <name>`), a strict name pattern, one
  revive at a time, and no flags that would skip the dispatcher's own permission checks.

Report a security problem privately to the maintainer rather than in a public issue.

## Before you publish anything

Run this list before you push a fork, attach a screenshot to an issue, or post the demo.

1. `python3 tools/privacy_audit.py --history` reports 0 findings. It scans every file git would
   ship, plus commit messages, for denylisted names (stored as hashes in
   `tools/denylist.sha256`), private and tailnet IP addresses, home folder paths, temp paths, email
   addresses outside `example.com`, phone numbers, secret-shaped strings, unknown URL hosts, em
   dashes, and PNG metadata chunks. Add your own name, town, hostnames and project names to the
   denylist with `--hash`.
2. `git status --ignored` shows `.env`, `data/`, `briefs/` and `prompt/about.md` as ignored, not
   staged.
3. `python3 -m unittest discover -s tests` passes. It includes the audit above.
4. Screenshots come from the demo only (`docs/screenshots.md`), and you looked at each one.
5. Commit messages, issues and release notes carry no links to private chats, agent sessions or
   transcripts, and no session ids.
6. `git log --format='%an <%ae>' | sort -u` shows only the identity you mean to publish.

## For maintainers porting from a private copy

If you run a private, personal version of daybook and port features into this one, port by
rewriting, never by copying files or merging histories. Each ported change gets its own setting
that is off by default, invented demo data if the demo needs it, a test, fresh screenshots if the
page changed, and a clean audit. A push to the private copy should start a review of what to port,
never an automatic public push.
