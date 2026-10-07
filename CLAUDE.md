# daybook

A morning brief (`daybook/brief.py`) and a live day board (`daybook/board/`) that share one
settings module (`daybook/config.py`), one day-shape module (`daybook/day.py`) and one data
contract (`marks.json`, `brief.json`). Python 3.11+, standard library only. `AGENTS.md` is a link
to this file, so Claude Code, Codex and other agents read the same instructions.

Read `docs/architecture.md` first, then `docs/data-contracts.md` before changing any file format.

## Rules

- **Invented data only.** Never put a real person, place, class, calendar, mailbox, machine, IP,
  home path, session name or repo name into this repo: not in code, fixtures, demo data, tests,
  docs, screenshots or commit messages. Demo and test data use invented names, `example.com`
  links and the `192.0.2.0/24` documentation range. Write test values that look like personal
  data (IPs, phone numbers, emails) so they are assembled at run time, like
  `tests/test_privacy_audit.py` does, or the audit will flag the test file.
- **Off by default.** Every new source or side effect gets a setting in `daybook/config.py`
  `DEFAULTS` whose empty value means off, a line in `.env.example`, and a forced-off value in
  `demo/demo.env`. `bin/daybook demo` clears the caller's `DAYBOOK_*` and `TODOIST_*` variables;
  keep it that way.
- **Never weaken a safeguard.** Keep the board's host check, token, origin check, JSON-only writes,
  body cap and CSP; the session field whitelist; the money, grading and link scrubbing; the
  allowed-roots check; the fixed argument lists for the dispatch command; and the brief's
  read-only model run (dontAsk, allowlist, denylist, hooks off, subscription check).
- **The model writes words, code draws.** Visuals, timelines, puzzles and counts are code. Keep
  the prompt's output small.
- **The page is only a client.** No inline script or inline style attributes in `web/*.html`
  (JS sets `el.style`), no outside requests, no new fonts. Colors are custom properties at the top
  of `web/app.css`. Dark mode follows `prefers-color-scheme`.
- **No em dashes** anywhere: code, comments, copy, docs, fixtures. Plain short sentences in copy.
- Comments are short lowercase fragments, matching the code around them.

## How to verify

```bash
python3 -m unittest discover -s tests -v       # everything, no network; includes the privacy audit
python3 tools/privacy_audit.py --history       # 0 findings before any commit or push
python3 bin/daybook demo --fresh --no-serve    # renders the demo brief, no network, no model
python3 bin/daybook demo --fresh --port 8840 --brief-port 8835 &   # then:
curl -s http://127.0.0.1:8840/health && curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8835/2026-04-14/
```

When a page changes, retake the screenshots (`docs/screenshots.md`) and look at every image.
Never run `brief generate` against real accounts from a test, and never point a test or a
screenshot run at real data.

## Layout

```
bin/daybook              the one CLI: demo, brief <cmd>, board <cmd>, config
daybook/config.py        every setting and its default
daybook/common.py        ids, norm(), scrubbing, frontmatter, atomic writes
daybook/day.py           merged events, open blocks, overlaps, the ribbon, sun times
daybook/brief.py         gather, the model run, cleaning, rendering, the brief's server, deliver
daybook/puzzles.py       the five daily puzzles and the weekly crossword
daybook/board/           server, store, items, agent (requests, sessions), todoist, digest, modules/
web/                     the board's page: index.html, app.js, app.css, modules/*.js
templates/               the brief's inlined css and js
prompt/                  the brief's prompt, output schema, news domains, examples
demo/                    the invented demo day (see demo/README.md)
tests/                   unittest suites, fixtures under tests/fixtures/, node tests in tests/js/
tools/                   screenshots.mjs, privacy_audit.py (+ denylist.sha256), pdfcheck.swift
```

## Publishing

Nothing is pushed, released or announced without the maintainer's explicit go for that push.
Run the checklist in `docs/privacy-and-publishing.md` first. Commit messages and PR text never
carry links to private chats, agent sessions or transcripts, or session ids.
