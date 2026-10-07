# Troubleshooting

Start with `python3 bin/daybook config`. It prints every setting in effect, with secrets shown
only as set or empty. Most problems are a setting that is empty, or a path that points somewhere
other than you think.

## The board

**A tile says "unavailable: ..."** One module failed and says why. The rest of the page still
works. Common reasons:

- `no brief on disk yet`: there is no `brief.json` under `DAYBOOK_BRIEFS`. Run
  `bin/daybook brief render --date YYYY-MM-DD` on a saved brief, or `brief generate`.
- The agent tile is empty: `DAYBOOK_SESSIONS` is unset, or its `sessions/` folder has no files
  that start with `DAYBOOK_SESSION_PREFIX`.
- The fleet tile is empty: `DAYBOOK_REGISTRY` and `DAYBOOK_SERVICES_FILE` are both unset.

**The page says "wrong host" (421).** The board refuses a `Host` header it does not trust, to stop
DNS rebinding. IPs, `localhost` and bare names (no dot) work. Add a full name such as
`board.your-tailnet.ts.net` to `DAYBOOK_ALLOWED_HOSTS` (a comma list). An entry that starts with a
dot, such as `.your-tailnet.ts.net`, allows every name under it.

**Marks or Start fail with "stale token".** The server restarted and the page kept the old token.
The page fetches the new one and retries once by itself. If it keeps happening, reload.

**Start says it copied the request instead of sending it.** That is the default. Nothing is sent
until you configure a transport: `DAYBOOK_WEBHOOK_URL` plus `DAYBOOK_WEBHOOK_SECRET`, or
`DAYBOOK_AGENT_SMS`. See `docs/integrations.md`.

**Archive and Revive are missing.** They only show when `DAYBOOK_DISPATCH_CMD` is set. Without it
the endpoints answer 403.

**"That folder is outside the allowed roots."** A hand-off may only run in a folder under
`DAYBOOK_PROJECTS`, `DAYBOOK_WORK_ROOTS`, or a class `workdir` inside those. Add the root, or send
the request to your agent yourself.

**The clock is stuck.** `DAYBOOK_NOW` is set. Clear it outside the demo.

**Times are an hour off.** Set `DAYBOOK_TZ` to an IANA zone such as `Europe/Berlin`. The page uses
the server's zone, not the browser's.

**Copy SSH does nothing.** The tailnet page is not a secure context, so the clipboard API is
blocked. The page falls back to `execCommand`, and if that is blocked too the toast shows the line
to copy by hand.

## The brief

**`generate` stops with "refusing: claude used apiKeySource=..."** The run found an API key in
the environment and would bill it. Remove the key from the job's environment, or set
`DAYBOOK_REQUIRE_SUBSCRIPTION=0` if you mean to pay per call.

**`generate` says a connector is unavailable.** The calendar, mail and Todoist reads come from MCP
connectors in your Claude Code setup. Check them with `claude mcp list`. The brief still renders,
and its Sources section says which source was missing.

**No PDF.** The PDF needs Chrome or Chromium. Set `DAYBOOK_CHROME` to its binary. The page check
(`tools/pdfcheck.swift`) runs only on macOS with `swiftc`; elsewhere the PDF is written without it.

**The puzzle tests are skipped.** They drive headless Chrome. Without Chrome they skip instead of
failing.

**Weather is "off".** `DAYBOOK_WEATHER=nws` needs `DAYBOOK_LAT` and `DAYBOOK_LON`, and the National
Weather Service only covers the United States.

## The demo

**Port already in use.** `python3 bin/daybook demo --port 8840 --brief-port 8835`.

**The demo shows my own data.** It cannot: `demo` clears every `DAYBOOK_*` and `TODOIST_*`
variable from its environment and loads only `demo/demo.env`. If you see something real, stop and
file it as a bug.

**Reset the demo.** `python3 bin/daybook demo --fresh` wipes `demo/.data` (marks, requests,
rendered pages) first.
