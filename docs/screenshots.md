# Screenshots

Every image in `docs/screenshots/` is a real capture of the demo pages, rendered from the
invented data in `demo/`. Never capture your own data for this folder.

## Retake them

You need Python 3.11+, Node 22+ (for the built-in `fetch` and `WebSocket`) and Chrome or
Chromium. Nothing gets installed.

```bash
python3 bin/daybook demo --fresh &          # brief on :8735, board on :8740, frozen at 10:20 AM
node tools/screenshots.mjs                  # writes docs/screenshots/*.png
kill %1
python3 tools/privacy_audit.py              # also checks the PNGs carry no metadata chunks
```

`tools/screenshots.mjs` drives headless Chrome over the DevTools protocol. It sets the viewport
with device emulation (headless Chrome will not size a window under 500px, so a phone shot needs
emulation, not `--window-size`), switches `prefers-color-scheme` for light and dark, and waits for the
board's first state. Phone shots are one real screen (390 by 844 at 2x); the board on a laptop
and `brief-desktop-full.png` are full pages. Set `DAYBOOK_CHROME` if Chrome is somewhere unusual.
`--only brief` retakes a subset; `--board` and `--brief` point it at other ports.

The demo clock is frozen with `DAYBOOK_NOW`, so the "Now" tile, the time windows and the session
ages come out the same every time. Puzzles are seeded by the date, so they repeat too. The live
"now" line on the brief's ribbon only draws when the browser's date in the configured zone matches
the brief's date, so it does not appear in the brief screenshots.

## Look at every image

After a retake, open each PNG and check by eye:

- only invented names, places and data appear (Avery, Pip, Lakeside, the demo classes and repos)
- no browser chrome, no local paths, no real hostnames, no real IPs (the demo uses 192.0.2.x)
- light and dark both look finished, and the phone shots show one room with the tab bar

## The set

| file | what |
|---|---|
| `board-desktop-light.png`, `board-desktop-dark.png` | the board, all three rooms as one bento grid |
| `board-phone-{today,agent,fleet}-{light,dark}.png` | each room on a 390 by 844 phone screen |
| `board-panel-desktop.png` | the hand-off panel open on the focus item |
| `brief-desktop-light.png`, `brief-desktop-dark.png` | the top of the brief: masthead, print, headline |
| `brief-desktop-full.png` | the whole brief, light |
| `brief-phone-light.png`, `brief-phone-dark.png` | the top of the brief on a 390 by 844 phone screen |
