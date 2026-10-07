# The demo day

Everything under `demo/` is invented dummy data. No person, class, school, message, event, repo,
session, device or news story here is real. Names like Avery, Pip, Sam, Jordan and Lakeside are made up,
links point at `example.com`, and device addresses use the `192.0.2.0/24` documentation range.

The demo is one fixed day, Tuesday 2026-04-14, with the clock frozen at 10:20 AM in America/Denver.
`daybook demo` loads `demo.env`, copies `briefs/2026-04-14/` into `.data/briefs/`, renders the brief
and serves both pages on localhost. Nothing in it reaches the network, a model, a messenger or an agent.

- `briefs/2026-04-14/context.json`: what `brief generate` would have gathered. The school part is computed
  from `school/`; the forecast, news, pull requests, session reports and git activity are written by hand.
- `briefs/2026-04-14/brief.json`: what the model would have returned, written by hand.
- `school/`: three classes, their assignments, one lecture note and one decision owed.
- `projects/`: three tiny project folders, one line each.
- `workspace/`: the class work folders that `class.md` points at.
- `dispatch/`, `registry/`, `services.json`, `models.json`: the board's sessions, devices, services and models.
- `.data/`: written by the demo (rendered pages, marks, the board's store). Safe to delete.
