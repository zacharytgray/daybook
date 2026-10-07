import datetime as dt
import html
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from collections import Counter, deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from daybook import puzzles  # noqa: E402

# chrome or chromium for the live tests; DAYBOOK_CHROME wins, else the usual places. none: those tests skip
CHROME = Path(next((p for p in [os.environ.get("DAYBOOK_CHROME", ""),
                                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                                "/Applications/Chromium.app/Contents/MacOS/Chromium", "/usr/bin/google-chrome",
                                "/usr/bin/chromium", "/usr/bin/chromium-browser"] if p and Path(p).is_file()),
                   "/nonexistent/chrome"))
START = dt.date(2026, 10, 1)
DAYS = [START + dt.timedelta(days=i) for i in range(60)]
ALL = {}
TIMES = {}


KINDS = ["ladder", "crossword", "word", "crowns", "sunmoon"]


def setUpModule():
    for d in DAYS:
        t = time.monotonic()
        ALL[d] = puzzles.all_for_day(d)
        TIMES[d] = time.monotonic() - t


def by_kind(kind):
    return [p for d in DAYS for p in ALL[d] if p["kind"] == kind]


def print_block(markup):
    m = re.search(r'<div class="pz-print">(.*?)</div><div class="pz-play"', markup, re.S)
    return m.group(1)


class Daily(unittest.TestCase):
    def test_same_date_same_output(self):
        for d in DAYS[:3]:
            a, b = puzzles.all_for_day(d), puzzles.all_for_day(d)
            self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
            self.assertEqual([puzzles.render(p) for p in a], [puzzles.render(p) for p in b])

    def test_five_a_day(self):
        for d in DAYS:
            ps = ALL[d]
            self.assertEqual([p["kind"] for p in ps], KINDS, d)
            self.assertEqual([p["category"] for p in ps], ["word"] * 3 + ["logic"] * 2)
            for p in ps:
                self.assertEqual(p["id"], f'{p["kind"]}-{d.isoformat()}')
                for k in ("title", "tagline", "instructions", "answer_text"):
                    self.assertTrue(p[k].strip(), (d, k))
        self.assertEqual(json.dumps(puzzles.for_day(DAYS[0])), json.dumps(ALL[DAYS[0]]))

    def test_word_games_share_no_answer(self):
        for d in DAYS:
            ladder, grid, hunch = ALL[d][:3]
            rungs = set(ladder["solution"])
            rows = grid["solution"]["rows"]
            words = {"".join(rows[y][x] for y, x in e["cells"]) for k in ("across", "down") for e in grid["state"][k]}
            ans = hunch["solution"]["answer"]
            self.assertFalse(rungs & words, d)
            self.assertNotIn(ans, rungs, d)
            self.assertNotIn(ans, words, d)

    def test_hunch_never_repeats_within_a_year(self):
        seen = [puzzles.gen_word(DAYS[0] + dt.timedelta(days=i))["solution"]["answer"] for i in range(366)]
        self.assertEqual(len(set(seen)), 366)

    def test_fast_enough(self):
        # all five together, at render time
        self.assertLess(max(TIMES.values()), 3.0)

    def test_answers_for(self):
        out = puzzles.answers_for(DAYS[0])
        self.assertEqual([a["title"] for a in out], [p["title"] for p in ALL[DAYS[0]]])
        self.assertTrue(all(a["answer_text"] for a in out))

    def test_json_and_no_em_dash(self):
        files = [ROOT / "daybook" / "puzzles.py", ROOT / "templates" / "play.js", ROOT / "templates" / "play.css",
                 *(ROOT / "assets" / "puzzles").iterdir()]
        for f in files:
            self.assertNotIn("\u2014", f.read_text(), f)
        for d in DAYS:
            for p in ALL[d]:
                json.dumps(p["state"])
                self.assertNotIn("\u2014", json.dumps(p, ensure_ascii=False) + puzzles.render(p))


# independent solvers, written differently from the generator's

def brute_crowns(regions):
    n, out = len(regions), []

    def go(y, cols):
        # plots are checked as it goes, or ten wide takes minutes
        if len({regions[r][c] for r, c in enumerate(cols)}) < len(cols):
            return
        if y == n:
            out.append(cols)
            return
        for x in range(n):
            if x not in cols and (not cols or abs(cols[-1] - x) > 1):
                go(y + 1, cols + [x])

    go(0, [])
    return out


def brute_sunmoon(givens, edges):
    g = [[None] * 6 for _ in range(6)]
    for y, x, v in givens:
        g[y][x] = v
    fixed = {(y, x) for y, x, _ in givens}
    out = []

    def ok(y, x):
        row, col = g[y], [g[r][x] for r in range(6)]
        for line in (row, col):
            for s in (0, 1):
                if line.count(s) > 3:
                    return False
            for i in range(4):
                if line[i] is not None and line[i] == line[i + 1] == line[i + 2]:
                    return False
        for ey, ex, d, k in edges:
            a = g[ey][ex]
            b = g[ey][ex + 1] if d == "r" else g[ey + 1][ex]
            if a is not None and b is not None and (a == b) != (k == "="):
                return False
        return True

    def go(i):
        if len(out) > 1:
            return
        if i == 36:
            out.append([r[:] for r in g])
            return
        y, x = divmod(i, 6)
        if (y, x) in fixed:
            if ok(y, x):
                go(i + 1)
            return
        for v in (0, 1):
            g[y][x] = v
            if ok(y, x):
                go(i + 1)
            g[y][x] = None

    go(0)
    return out


def ref_score(guess, answer):
    # counts what each letter has left after exact hits, then hands out "elsewhere" left to right
    spare = Counter(a for g, a in zip(guess, answer) if g != a)
    out = ""
    for g, a in zip(guess, answer):
        if g == a:
            out += "2"
        elif spare[g] > 0:
            spare[g] -= 1
            out += "1"
        else:
            out += "0"
    return out


class Solvable(unittest.TestCase):
    def test_crowns_unique(self):
        for p in by_kind("crowns"):
            regs = p["state"]["regions"]
            n = p["state"]["n"]
            self.assertIn(n, (9, 10))
            self.assertEqual(sorted({g for row in regs for g in row}), list(range(n)))
            for g in range(n):
                self.assertTrue(puzzles.connected([(y, x) for y in range(n) for x in range(n) if regs[y][x] == g]), p["id"])
            self.assertEqual(brute_crowns(regs), [p["solution"]], p["id"])
            self.assertEqual(puzzles.unobf(p["state"]["sol"]), p["solution"])

    def test_sunmoon_unique(self):
        for p in by_kind("sunmoon"):
            st = p["state"]
            sols = brute_sunmoon(st["givens"], st["edges"])
            self.assertEqual(sols, [p["solution"]], p["id"])
            self.assertGreaterEqual(len(st["givens"]), 1)
            for y, x, d, k in st["edges"]:
                a = p["solution"][y][x]
                b = p["solution"][y][x + 1] if d == "r" else p["solution"][y + 1][x]
                self.assertEqual(a == b, k == "=")

    def test_crowns_graded_hard(self):
        # logically solvable without guessing, and the top tiers are really needed
        for p in by_kind("crowns"):
            gr = puzzles.crowns_grade(p["state"]["regions"])
            self.assertTrue(gr["solved"], p["id"])
            self.assertEqual(gr["tiers"], p["grade"]["tiers"], p["id"])
            self.assertGreaterEqual(gr["tiers"][3], 1, p["id"])
            self.assertGreaterEqual(gr["tiers"][2], 3, p["id"])

    def test_sunmoon_graded_hard(self):
        for p in by_kind("sunmoon"):
            st = p["state"]
            gr = puzzles.sm_grade({(y, x): v for y, x, v in st["givens"]}, [tuple(e) for e in st["edges"]])
            self.assertTrue(gr["solved"], p["id"])
            self.assertEqual(gr["tiers"], p["grade"]["tiers"], p["id"])
            self.assertGreaterEqual(gr["tiers"][3], 1, p["id"])
            self.assertGreaterEqual(gr["tiers"][2], 2, p["id"])

    def test_ladder_minimal(self):
        for p in by_kind("ladder"):
            st, path = p["state"], p["solution"]
            words = set((ROOT / "assets" / "puzzles" / f'ladder{st["len"]}.txt').read_text().split())
            self.assertEqual(path[0], st["start"])
            self.assertEqual(path[-1], st["end"])
            self.assertEqual(len(path), st["blanks"] + 2)
            for a, b in zip(path, path[1:]):
                self.assertIn(b.lower(), words)
                self.assertEqual(sum(x != y for x, y in zip(a, b)), 1, (a, b))
            dist, q = {path[0].lower(): 0}, deque([path[0].lower()])
            while q:
                w = q.popleft()
                for v in words:
                    if v not in dist and sum(x != y for x, y in zip(w, v)) == 1:
                        dist[v] = dist[w] + 1
                        q.append(v)
            self.assertEqual(dist[path[-1].lower()], len(path) - 1, p["id"])
            self.assertTrue(puzzles.ladder_ok(p, path[1:-1]))
            self.assertFalse(puzzles.ladder_ok(p, path[1:-2]))

    def test_hunch_print_clues_leave_one_word(self):
        common, answers = puzzles.hunch_common(), puzzles.hunch_answers()
        guesses = set(puzzles.hunch_guesses())
        picked = set()
        for d in DAYS:
            p = puzzles.gen_word(d)  # every date, not only the ones that show it
            ans, clues = p["solution"]["answer"], p["state"]["clues"]
            picked.add(ans)
            self.assertEqual(puzzles.unobf(p["state"]["sol"]), ans)
            self.assertEqual(p["answer_text"], ans)
            self.assertIn(ans, answers)
            self.assertIn(len(clues), (2, 3))
            for g, sc in clues:
                self.assertNotEqual(g, ans)
                self.assertIn(g, answers)
                self.assertEqual(sc, ref_score(g, ans))
            # exactly one word fits the printed marks, in the answer list and in the wider common list
            self.assertEqual([w for w in answers if all(ref_score(g, w) == sc for g, sc in clues)], [ans], p["id"])
            self.assertEqual([w for w in common if all(ref_score(g, w) == sc for g, sc in clues)], [ans], p["id"])
            hits = {i for _, sc in clues for i, k in enumerate(sc) if k == "2"}
            self.assertLessEqual(len(hits), 3, p["id"])
            ws = p["state"]["words"]
            self.assertEqual({ws[i:i + 5] for i in range(0, len(ws), 5)}, guesses)
        self.assertEqual(len(picked), 60)

    def test_hunch_word_lists(self):
        answers, guesses = puzzles.hunch_answers(), set(puzzles.hunch_guesses())
        self.assertGreater(len(answers), 1000)
        self.assertTrue(set(answers) <= set(puzzles.hunch_common()) <= guesses)
        for w in answers:
            self.assertRegex(w, r"^[A-Z]{5}$")
            self.assertFalse(re.search(r"[^SUIOA]S$", w), w)  # no plurals
        for w in ("CRANE", "THEIR", "ABOUT", "PIZZA", "BOXES", "BAKED", "EERIE", "ABBEY"):
            self.assertIn(w, guesses)


    def test_crossword_consistent(self):
        bank = puzzles.bank()
        for p in by_kind("crossword"):
            mask, rows = p["solution"]["mask"], p["solution"]["rows"]
            self.assertTrue(puzzles.crossword_ok(mask, rows), p["id"])
            self.assertEqual(puzzles.unobf(p["state"]["sol"]), rows)
            for d in ("across", "down"):
                nums = [e["num"] for e in p["state"][d]]
                self.assertEqual(nums, sorted(nums))
                for e in p["state"][d]:
                    word = "".join(rows[y][x] for y, x in e["cells"])
                    self.assertIn(word, bank)
                    self.assertEqual(e["clue"], bank[word])
                    self.assertNotIn(word.lower(), e["clue"].lower())
            # every white cell is in one across and one down entry of 3+ letters
            for y in range(5):
                for x in range(5):
                    if mask[y][x] == ".":
                        hits = [d for d in ("across", "down") for e in p["state"][d] if [y, x] in e["cells"]]
                        self.assertEqual(sorted(hits), ["across", "down"])


def sound(grid, tiers, keep):
    # wrap every tier so a step that throws away part of the known answer fails loudly
    def wrap(f):
        def g(st):
            nxt = f(st)
            if nxt is not None:
                assert keep(nxt), f.__name__
            return nxt
        return g
    return [wrap(f) for f in tiers]


class Grading(unittest.TestCase):
    """the two logical solvers, on small hand-made positions and on the whole shipped pools"""

    # small crown puzzles with known grades. the first falls to singles alone: plot B is the one
    # square at the top, and each crown after it leaves one square in some row, column or plot
    CROWNS = {
        1: [[1, 0, 1, 1, 1, 1], [1, 1, 1, 1, 1, 1], [2, 4, 1, 4, 1, 5], [2, 4, 4, 4, 3, 5], [4, 4, 4, 4, 4, 5],
            [4, 4, 4, 4, 4, 5]],
        2: [[0, 0, 0, 2, 2, 3], [1, 0, 2, 2, 2, 3], [2, 2, 2, 2, 2, 3], [2, 2, 2, 3, 3, 3], [4, 4, 2, 2, 5, 5],
            [4, 4, 4, 4, 5, 5]],
        3: [[1, 1, 1, 1, 0, 0, 0], [3, 1, 1, 2, 0, 0, 0], [3, 1, 1, 2, 2, 2, 2], [3, 3, 3, 3, 2, 2, 2],
            [5, 5, 3, 5, 2, 4, 4], [5, 5, 5, 5, 4, 4, 6], [5, 5, 5, 5, 4, 4, 6]],
        4: [[2, 2, 1, 1, 3, 0, 3], [2, 2, 2, 1, 3, 3, 3], [2, 2, 3, 3, 3, 3, 3], [2, 4, 4, 4, 3, 3, 5],
            [2, 4, 4, 3, 3, 3, 5], [2, 4, 4, 5, 5, 5, 5], [4, 4, 6, 6, 6, 6, 5]],
    }

    def test_crown_grades_on_small_puzzles(self):
        for top, regs in self.CROWNS.items():
            self.assertEqual(len(brute_crowns(regs)), 1)
            gr = puzzles.crowns_grade(regs)
            self.assertTrue(gr["solved"], top)
            self.assertEqual(gr["top"], top, gr)

    def test_crown_tiers_by_hand(self):
        regs = self.CROWNS[1]
        g = puzzles.CrownGrid(regs)
        cand, crowns = g.t1(g.start())
        self.assertEqual(crowns, 1 << 1)  # the lone square of plot B
        self.assertFalse(cand >> 0 & 1 or cand >> 7 & 1 or cand >> 6 & 1)  # its row, the square below, a corner
        # confinement: row 1 lies inside plot B, so plot B's squares in row 0 go
        regs = [[0, 1, 1, 0, 1], [1, 1, 1, 1, 1], [2, 2, 2, 2, 2], [3, 3, 3, 3, 3], [4, 4, 4, 4, 4]]
        g = puzzles.CrownGrid(regs)
        self.assertIsNone(g.t1(g.start()))
        cand, _ = g.t2(g.start())
        self.assertEqual([b for b in range(5) if not cand >> b & 1], [1, 2, 4])

    def test_crown_lookahead_is_needed_and_sound(self):
        regs = self.CROWNS[4]
        sol = brute_crowns(regs)[0]
        keep = sum(1 << (y * 7 + x) for y, x in enumerate(sol))
        g = puzzles.CrownGrid(regs)
        st = g.settle(g.start())
        self.assertFalse(g.done(st))
        nxt = g.t4(st)
        self.assertIsNotNone(nxt)
        self.assertEqual((nxt[0] | nxt[1]) & keep, keep)

    def test_sunmoon_tiers_by_hand(self):
        S, M = puzzles.SUN, puzzles.MOON

        def row(*vals, edges=()):
            st = [None] * 36
            for i, v in enumerate(vals):
                st[i] = v
            return puzzles.SunMoonGrid(list(edges)), tuple(st)
        g, st = row(S, S)
        self.assertEqual(g.t1(st)[2], M)  # two alike, the next differs
        g, st = row(S, None, S)
        self.assertEqual(g.t1(st)[1], M)  # a gap between two alike
        g, st = row(S, edges=[(0, 0, "r", "x")])
        self.assertEqual(g.t1(st)[1], M)  # x across a sign
        g, st = row(S, M, S, M, S)
        self.assertIsNone(g.t1(st))
        self.assertEqual(g.t2(st)[5], M)  # three suns, so the rest are moons
        g, st = row(S, None, None, None, None, S)
        self.assertIsNone(g.t1(st))
        self.assertIsNone(g.t2(st))
        nxt = g.t3(st)  # only SMSMMS and SMMSMS fit, both with moons second and fifth
        self.assertEqual((nxt[1], nxt[4]), (M, M))
        self.assertEqual(nxt[2:4], (None, None))

    def test_pools_cover_a_year_without_repeats(self):
        for kind in ("crowns", "sunmoon"):
            self.assertGreaterEqual(len(puzzles.pool(kind)), 366)
            picks = [json.dumps(puzzles.pool_pick(kind, DAYS[0] + dt.timedelta(days=i))) for i in range(366)]
            self.assertEqual(len(set(picks)), 366, kind)
            self.assertEqual(len({json.dumps(e) for e in puzzles.pool(kind)}), len(puzzles.pool(kind)))

    def test_whole_crown_pool(self):
        for e in puzzles.pool("crowns"):
            regs, sol, n = e["regions"], e["sol"], e["n"]
            keep = sum(1 << (y * n + x) for y, x in enumerate(sol))
            g = puzzles.CrownGrid(regs)
            gr = puzzles.run_tiers(sound(g, g.tiers, lambda st: (st[0] | st[1]) & keep == keep), g.start(), g.done)
            self.assertTrue(gr["solved"])
            self.assertEqual(gr["tiers"], e["tiers"])
            self.assertTrue(puzzles.crowns_hard(gr), e["tiers"])
            self.assertTrue(puzzles.crowns_ok(regs, sol))
            for k in range(n):
                self.assertTrue(puzzles.connected([(y, x) for y in range(n) for x in range(n) if regs[y][x] == k]))

    def test_whole_sunmoon_pool(self):
        for e in puzzles.pool("sunmoon"):
            sol = sum(e["sol"], [])
            givens = {(y, x): v for y, x, v in e["givens"]}
            g = puzzles.SunMoonGrid([tuple(x) for x in e["edges"]])
            st = [None] * 36
            for (y, x), v in givens.items():
                st[y * 6 + x] = v
            gr = puzzles.run_tiers(sound(g, g.tiers, lambda s: all(v is None or v == sol[i] for i, v in enumerate(s))),
                                   tuple(st), g.done)
            self.assertTrue(gr["solved"])
            self.assertEqual(gr["tiers"], e["tiers"])
            self.assertTrue(puzzles.sm_hard(gr), e["tiers"])


FRIDAYS = [dt.date(2026, 10, 9) + dt.timedelta(weeks=i) for i in range(53)]


def runs(rows):
    # every across and down run of 2+ letters, found without the generator's helpers
    out = set()
    h, w = len(rows), len(rows[0])
    for y in range(h):
        for m in re.finditer(r"[A-Z]{2,}", rows[y]):
            out.add(("across", tuple((y, x) for x in range(m.start(), m.end()))))
    for x in range(w):
        col = "".join(rows[y][x] for y in range(h))
        for m in re.finditer(r"[A-Z]{2,}", col):
            out.add(("down", tuple((y, x) for y in range(m.start(), m.end()))))
    return out


class Weekly(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.times, cls.grids = [], {}
        for f in FRIDAYS:
            t = time.monotonic()
            cls.grids[f] = puzzles.weekly_for(f)
            cls.times.append(time.monotonic() - t)

    def test_grid_rules(self):
        clue_bank = puzzles.weekly_clue_bank()
        hard = puzzles.weekly_bank("hard")
        for f, p in self.grids.items():
            rows = p["solution"]["rows"]
            st = p["state"]
            self.assertTrue(12 <= len(rows) <= 15 and 12 <= len(rows[0]) <= 15, (f, len(rows), len(rows[0])))
            ents = [(d, tuple(map(tuple, e["cells"]))) for d in ("across", "down") for e in st[d]]
            # the standard rule: every run of two or more letters is a clued entry, nothing else
            self.assertEqual(runs(rows), set(ents), f)
            self.assertTrue(24 <= len(ents) <= 32, (f, len(ents)))
            words = ["".join(rows[y][x] for y, x in cells) for _, cells in ents]
            self.assertEqual(len(set(words)), len(words))
            self.assertTrue(all(w in clue_bank for w in words))
            self.assertGreaterEqual(sum(w in hard for w in words), 10, f)
            cells = {(y, x) for y, r in enumerate(rows) for x, ch in enumerate(r) if ch != "#"}
            self.assertTrue(puzzles.connected(cells), f)
            crossings = sum(len(w) for w in words) - len(cells)
            self.assertGreaterEqual(crossings, len(ents) - 1)  # a tree at least; most grids loop back
            self.assertEqual(puzzles.unobf(st["sol"]), rows)
            nums = [e["num"] for d in ("across", "down") for e in st[d]]
            starts = sorted({e["cells"][0][0] * 100 + e["cells"][0][1] for d in ("across", "down") for e in st[d]})
            self.assertEqual(sorted(set(nums)), list(range(1, len(starts) + 1)))
            for d in ("across", "down"):
                for e in st[d]:
                    self.assertEqual(e["clue"], clue_bank["".join(rows[y][x] for y, x in e["cells"])])

    def test_same_all_week_and_new_on_friday(self):
        f = FRIDAYS[0]
        week = [puzzles.weekly_for(f + dt.timedelta(days=i)) for i in range(7)]
        for p in week:
            self.assertEqual(json.dumps(p, sort_keys=True), json.dumps(week[0], sort_keys=True))
        self.assertEqual(week[0]["id"], f"weekly-{f.isoformat()}")
        self.assertEqual((week[0]["week_start"], week[0]["week_end"]), (f.isoformat(), (f + dt.timedelta(days=6)).isoformat()))
        nxt = puzzles.weekly_for(f + dt.timedelta(days=7))
        self.assertNotEqual(nxt["solution"]["rows"], week[0]["solution"]["rows"])
        self.assertEqual(puzzles.weekly_for(f - dt.timedelta(days=1))["week_start"], (f - dt.timedelta(days=7)).isoformat())
        # last week's answers on friday
        prev = puzzles.weekly_answers_for(f + dt.timedelta(days=7))
        self.assertEqual(prev["id"], week[0]["id"])
        self.assertEqual(prev["answer_text"], week[0]["answer_text"])

    def test_no_answer_within_twelve_weeks(self):
        words = {f: {e["answer"] for d in ("across", "down") for e in p["solution"]["entries"][d]} for f, p in self.grids.items()}
        for i, f in enumerate(FRIDAYS):
            for g in FRIDAYS[i + 1:i + 13]:
                self.assertFalse(words[f] & words[g], (f, g, words[f] & words[g]))

    def test_fast_enough(self):
        self.assertLess(max(self.times), 1.5)

    def test_model_clues_and_fallback(self):
        f = FRIDAYS[0]
        ents = puzzles.weekly_entries(f)
        self.assertEqual(len(ents), sum(len(self.grids[f]["state"][d]) for d in ("across", "down")))
        for e in ents:
            self.assertEqual(e["enum"], f'({len(e["answer"])})')
            self.assertIn(e["dir"], ("across", "down"))
        a, b, c, d = (e["answer"] for e in ents[:4])
        clues = {a: "A fair clue of the right kind", b.lower(): "Lower-case key is fine",
                 c: f"Contains {c.lower()} itself", d: "x" * 91}
        good = puzzles.clean_weekly_clues(ents, clues)
        self.assertEqual(good, {a: "A fair clue of the right kind", b: "Lower-case key is fine"})
        self.assertEqual(puzzles.clean_weekly_clues(ents, {a: "Dash \u2014 here"}), {})
        self.assertEqual(puzzles.clean_weekly_clues(ents, {a: "   "}), {})
        self.assertEqual(puzzles.clean_weekly_clues(ents, None), {})
        p = puzzles.weekly_for(f, clues)
        got = {"".join(p["solution"]["rows"][y][x] for y, x in e["cells"]): e["clue"] for k in ("across", "down") for e in p["state"][k]}
        self.assertEqual(got[a], clues[a])
        self.assertEqual(got[c], puzzles.weekly_clue_bank()[c])
        self.assertEqual(p["clue_source"], {"model": 2, "bank": len(ents) - 2})

    def test_stems_are_caught(self):
        leaks = puzzles.clue_leaks
        self.assertTrue(leaks("HOMEWORK", "Work for after school"))
        self.assertTrue(leaks("LACONIC", "Like a Laconian, brief"))
        self.assertTrue(leaks("MAGNUMOPUS", "Magnum opus, in short"))
        self.assertTrue(leaks("OBDURATE", "Obdurately stubborn"))
        self.assertTrue(leaks("CREATION", "Something created"))
        self.assertTrue(leaks("HAPPINESS", "Being very happy"))
        self.assertTrue(leaks("TEACHER", "One who teaches"))
        self.assertFalse(leaks("RUNNING", "Sprinting or jogging"))
        self.assertFalse(leaks("LACONIC", "Using very few words"))
        self.assertFalse(leaks("ANATHEMA", "Something you detest; to them it is cursed"))
        for w, c in puzzles.weekly_clue_bank().items():  # the fallback clues pass the same rule
            self.assertFalse(leaks(w, c), (w, c))

    def test_print(self):
        p = self.grids[FRIDAYS[0]]
        full, short = puzzles.render_weekly(p, print_full=True), puzzles.render_weekly(p, print_full=False)
        for markup in (full, short):
            block = print_block(markup)
            text = re.sub(r"<[^>]+>", " ", block)
            self.assertIsNone(re.search(r'<span class="pz-c[^"]*">[A-Z]', block))
            for d in ("across", "down"):
                for e in p["solution"]["entries"][d]:
                    self.assertNotRegex(text, rf"\b{e['answer']}\b")
            self.assertNotIn(p["state"]["sol"], block)
            self.assertNotIn("\u2014", markup)
        self.assertEqual(print_block(full).count("<li>"), sum(len(p["state"][d]) for d in ("across", "down")))
        self.assertNotIn("<li>", print_block(short))
        self.assertIn("pz-state", full)


class Feedback(unittest.TestCase):
    def test_duplicate_letters(self):
        cases = {("BABES", "ABBEY"): "11220", ("EERIE", "LEVEL"): "12000", ("SKILL", "LEVEL"): "00012",
                 ("ELDER", "LEVEL"): "11020", ("LLAMA", "HELLO"): "11000", ("SPEED", "ABIDE"): "00101",
                 ("ROBOT", "FLOOR"): "11020", ("CRANE", "CRANE"): "22222", ("FUZZY", "PIZZA"): "00220",
                 ("ZZZAA", "PIZZA"): "10202", ("GEESE", "THESE"): "00222", ("EERIE", "THEME"): "10002"}
        for (g, a), want in cases.items():
            self.assertEqual(puzzles.score(g, a), want, (g, a))
            self.assertEqual(ref_score(g, a), want, (g, a))

    def test_matches_reference_everywhere(self):
        import random
        r = random.Random(7)
        words = puzzles.hunch_answers()
        for _ in range(4000):
            g, a = r.choice(words), r.choice(words)
            self.assertEqual(puzzles.score(g, a), ref_score(g, a), (g, a))


class NoGeo(unittest.TestCase):
    def test_geography_kind_is_gone(self):
        self.assertFalse((ROOT / "assets" / "puzzles" / "countries.json").exists())
        self.assertNotIn("geo", puzzles.GENERATORS)
        self.assertNotIn("geo", puzzles.PRINTERS)
        self.assertNotIn("geo", puzzles.CATEGORY.values())
        self.assertNotIn("geo:", puzzles.PLAY_JS)
        me = Path(__file__).resolve()
        files = [f for f in [ROOT / "daybook" / "puzzles.py", ROOT / "daybook" / "brief.py", *ROOT.glob("templates/*"),
                             *ROOT.glob("docs/*.md"), *ROOT.glob("tests/test_brief*.py"), ROOT / "tests" / "test_design.py",
                             *(ROOT / "assets" / "puzzles").iterdir(), *ROOT.glob("*.md")] if f.resolve() != me and f.exists()]
        for f in files:
            text = f.read_text(errors="replace").lower()
            for bad in ("capital compass", "countries.json", "pz-geo", "gen_geo", "print_geo", '"geo"', "wordgeo"):
                self.assertFalse(bad in text, f"{bad} in {f}")
        for d in DAYS:
            for q in ALL[d]:
                self.assertNotIn("geo", (q["kind"], q["category"]))


class NoLeaks(unittest.TestCase):
    def test_print_block_has_no_answers(self):
        for d in DAYS:
            for p in ALL[d] + [puzzles.gen_word(d)]:
                block = print_block(puzzles.render(p))
                text = re.sub(r"<[^>]+>", " ", block)
                self.assertNotIn("<button", block)
                self.assertNotIn("pz-state", block)
                k = p["kind"]
                if k == "ladder":
                    for w in p["solution"][1:-1]:
                        self.assertNotRegex(text, rf"\b{w}\b", p["id"])
                    self.assertEqual(len(re.findall(r'<span class="pz-c">[A-Z]</span>', block)), 2 * p["state"]["len"])
                elif k == "crossword":
                    self.assertIsNone(re.search(r'<span class="pz-c[^"]*">[A-Z]', block), p["id"])
                    for e in p["state"]["across"] + p["state"]["down"]:
                        w = "".join(p["solution"]["rows"][y][x] for y, x in e["cells"])
                        self.assertNotRegex(text, rf"\b{w}\b", p["id"])
                elif k == "word":
                    ans = p["solution"]["answer"]
                    letters = "".join(re.findall(r'<span class="pz-wt pz-m\d"[^>]*>([A-Z])</span>', block))
                    self.assertEqual(len(letters), 5 * len(p["state"]["clues"]), p["id"])
                    self.assertNotIn(ans, letters, p["id"])
                    self.assertNotIn(ans, re.sub(r"<[^>]+>|\s", "", block).upper(), p["id"])
                    self.assertNotIn(ans.lower(), text.lower(), p["id"])
                    self.assertNotIn(p["state"]["sol"], block)
                elif k == "crowns":
                    self.assertNotIn("pz-ico pz-crown", block)
                    self.assertNotIn("<svg", block)
                elif k == "sunmoon":
                    icons = block.count('class="pz-ico pz-sun"') + block.count('class="pz-ico pz-moon"')
                    self.assertEqual(icons, len(p["state"]["givens"]), p["id"])


SELFTEST = r"""
(function () {
  var log = { dialogs: 0, puzzles: [], errors: [] };
  window.alert = window.confirm = window.prompt = function () { log.dialogs++; };
  window.addEventListener("error", function (e) { log.errors.push(String(e.message)); });
  function dec(s) { return JSON.parse(atob(s).split("").reverse().join("")); }
  function key(el, k) { el.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true })); }
  function tap(el) { el.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true })); el.click(); }
  function act(sec, a) { return sec.querySelector('.pz-play [data-act="' + a + '"]'); }
  function status(sec) { return sec.querySelector(".pz-status").textContent; }
  function wide() { return document.documentElement.scrollWidth <= window.innerWidth; }
  function filled(sec) {
    var n = 0;
    sec.querySelectorAll(".pz-play .pz-in").forEach(function (i) { if (i.value && !i.readOnly) n++; });
    sec.querySelectorAll(".pz-play .pz-cell:not(.pz-given)").forEach(function (c) { if (c.querySelector("svg")) n++; });
    n += sec.querySelectorAll(".pz-play .pz-tile.pz-ghost").length;
    return n;
  }
  function clear(sec) { tap(act(sec, "clear")); tap(act(sec, "clear")); }
  function cellAt(sec, y, x) { return sec.querySelector('.pz-play .pz-cell[data-y="' + y + '"][data-x="' + x + '"]'); }
  function inAt(sec, y, x) { return sec.querySelector('.pz-play .pz-in[data-y="' + y + '"][data-x="' + x + '"]'); }

  var solvers = {
    ladder: function (sec, st, sol) {
      inAt(sec, 1, 0).focus();
      for (var r = 1; r <= st.blanks; r++) for (var x = 0; x < st.len; x++) key(document.activeElement, sol[r][x]);
    },
    crossword: function (sec, st, sol) {
      st.across.forEach(function (e, i) {
        tap(sec.querySelectorAll(".pz-play .pz-clue")[i]);
        inAt(sec, e.cells[0][0], e.cells[0][1]).focus();
        e.cells.forEach(function (c) { key(document.activeElement, sol[c[0]][c[1]]); });
      });
    },
    word: function (sec, st, sol) {
      var out = {}, board = sec.querySelector(".pz-play .pz-wboard");
      function row(i) { return [].slice.call(sec.querySelectorAll(".pz-play .pz-wline")[i].children); }
      function marks(i) { return row(i).map(function (t) { var m = /pz-m(\d)/.exec(t.className); return m ? m[1] : "."; }).join(""); }
      function keyBtn(k) { return sec.querySelector('.pz-play .pz-key[data-key="' + k + '"]'); }
      board.focus();
      // a non-word through real key events: refused, nothing scored
      "qzqzq".split("").forEach(function (k) { key(board, k); });
      key(board, "Enter");
      out.invalid = /not in the word list/.test(status(sec)) && marks(0) === "....." && row(0)[0].textContent === "Q";
      for (var i = 0; i < 5; i++) key(board, "Backspace");
      out.backspace = row(0).every(function (t) { return t.textContent === ""; });
      // a wrong real word through on-screen key taps, checked against an independent scorer
      var wrong = null;
      for (var j = 0; j + 5 <= st.words.length && !wrong; j += 5) {
        var w = st.words.slice(j, j + 5);
        if (w !== sol && w.split("").some(function (c) { return sol.indexOf(c) >= 0; })) wrong = w;
      }
      wrong.split("").forEach(function (c) { tap(keyBtn(c)); });
      tap(keyBtn("Enter"));
      out.feedback = marks(0) === ref(wrong, sol) && row(0).every(function (t) { return /right spot|in the word|not in the word/.test(t.getAttribute("aria-label")); });
      out.keyboard = wrong.split("").every(function (c, i) { return keyBtn(c).className.indexOf("pz-m") >= 0; }) &&
        keyBtn(wrong[0]).getAttribute("aria-label").indexOf(",") > 0;
      // then the answer by typing
      board.focus();
      sol.split("").forEach(function (c) { key(board, c.toLowerCase()); });
      key(board, "Enter");
      out.won = marks(1) === "22222";
      return out;
    },
    crowns: function (sec, st, sol) {
      sol.forEach(function (x, y) { tap(cellAt(sec, y, x)); tap(cellAt(sec, y, x)); });
    },
    weekly: function (sec, st, sol) {
      // type every entry, across then down, starting from its clue
      var clues = sec.querySelectorAll(".pz-play .pz-clue"), i = 0;
      st.across.concat(st.down).forEach(function (e) {
        tap(clues[i++]);
        inAt(sec, e.cells[0][0], e.cells[0][1]).focus();
        e.cells.forEach(function (c) { var el = inAt(sec, c[0], c[1]); el.focus(); key(el, sol[c[0]][c[1]]); });
      });
    },
    sunmoon: function (sec, st, sol) {
      for (var y = 0; y < 6; y++) for (var x = 0; x < 6; x++) {
        var c = cellAt(sec, y, x);
        if (c.classList.contains("pz-given")) continue;
        for (var k = 0; k <= sol[y][x]; k++) tap(c);
      }
    }
  };
  function ref(g, a) {
    // independent scorer: spare letters after exact hits, handed out left to right
    var spare = {}, out = "";
    for (var i = 0; i < 5; i++) if (g[i] !== a[i]) spare[a[i]] = (spare[a[i]] || 0) + 1;
    for (var j = 0; j < 5; j++) {
      if (g[j] === a[j]) out += "2";
      else if (spare[g[j]] > 0) { spare[g[j]]--; out += "1"; }
      else out += "0";
    }
    return out;
  }
  function revealedOk(sec, st, sol) {
    if (st.kind === "word") {
      var shown = [].slice.call(sec.querySelectorAll(".pz-play .pz-tile.pz-shown")).map(function (t) { return t.textContent; }).join("");
      return status(sec).indexOf(sol) >= 0 && shown === sol;
    }
    if (st.kind === "crowns") return sec.querySelectorAll(".pz-play .pz-cell.pz-has").length === st.n;
    if (st.kind === "sunmoon") return sec.querySelectorAll(".pz-play .pz-cell svg").length === 36;
    var ok = true;
    sec.querySelectorAll(".pz-play .pz-in").forEach(function (i) {
      var y = +i.dataset.y, x = +i.dataset.x;
      if (i.value !== (st.kind === "ladder" ? sol[y][x] : sol[y][x])) ok = false;
    });
    return ok;
  }
  function run() {
    log.wideStart = wide();
    log.innerWidth = window.innerWidth;
    document.querySelectorAll(".pz").forEach(function (sec) {
      var r = { id: sec.dataset.pzId, live: sec.classList.contains("pz-live") };
      try {
        var st = JSON.parse(sec.querySelector("script.pz-state").textContent), sol = dec(st.sol);
        r.kind = st.kind;
        var before = filled(sec);
        tap(act(sec, "hint"));
        r.hint = filled(sec) > before || (st.kind === "crowns" && sec.querySelectorAll(".pz-play .pz-has").length > 0);
        clear(sec);
        r.cleared = status(sec) === "" && !sec.classList.contains("pz-solved");
        if (st.kind === "crowns") { var c0 = cellAt(sec, 0, 0); c0.focus(); key(c0, "ArrowRight"); r.keys = document.activeElement === cellAt(sec, 0, 1); key(document.activeElement, "x"); r.keys = r.keys && !!cellAt(sec, 0, 1).querySelector(".pz-dot"); clear(sec); }
        if (st.kind === "sunmoon") { var c1 = cellAt(sec, 0, 0); c1.focus(); key(c1, "ArrowDown"); r.keys = document.activeElement === cellAt(sec, 1, 0); }
        var extra = solvers[st.kind](sec, st, sol) || {};
        Object.keys(extra).forEach(function (k) { r[k] = extra[k]; });
        r.solved = sec.classList.contains("pz-solved") && /Solved/.test(status(sec));
        r.wideSolved = wide();
        clear(sec);
        if (st.kind === "weekly") tap(sec.querySelector('.pz-play .pz-seg[data-scope="grid"]'));  // reveal it all
        var rv = act(sec, "reveal");
        tap(rv);
        r.armed = rv.classList.contains("pz-armed") && !sec.classList.contains("pz-revealed");
        tap(rv);
        r.revealed = sec.classList.contains("pz-revealed") && revealedOk(sec, st, sol);
      } catch (e) { r.error = String(e && e.stack || e); }
      log.puzzles.push(r);
    });
    log.wideEnd = wide();
    // inside the phone-width frame, report to the outer page so --dump-dom sees it
    var doc = window.parent !== window ? window.parent.document : document;
    var out = doc.createElement("pre");
    out.id = "pz-selftest";
    out.textContent = JSON.stringify(log);
    doc.body.appendChild(out);
  }
  setTimeout(run, 50);
})();
"""

HUNCH_TEST = r"""
(function () {
  var log = { dialogs: 0, errors: [] };
  window.alert = window.confirm = window.prompt = function () { log.dialogs++; };
  window.addEventListener("error", function (e) { log.errors.push(String(e.message)); });
  function key(el, k) { el.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true })); }
  setTimeout(function () {
    try { localStorage.clear(); } catch (e) {}
    var sec = document.querySelector(".pz"), board = sec.querySelector(".pz-wboard");
    ["EERIE", "ELDER", "SKILL", "APPLE", "BREAD", "MOUSE"].forEach(function (w) {
      board.focus();
      w.split("").forEach(function (c) { key(board, c); });
      key(board, "Enter");
    });
    log.rows = [].slice.call(sec.querySelectorAll(".pz-wline")).map(function (r) {
      return [].slice.call(r.children).map(function (t) { var m = /pz-m(\d)/.exec(t.className); return m ? m[1] : "."; }).join("");
    });
    var e = sec.querySelector('.pz-key[data-key="E"]').className;
    log.keyE = (/pz-m(\d)/.exec(e) || [])[1];
    var st = sec.querySelector(".pz-status").textContent;
    log.failed = /Out of guesses/.test(st) && st.indexOf("LEVEL") >= 0 && sec.classList.contains("pz-revealed");
    key(board, "A");
    log.locked = sec.querySelector(".pz-status").textContent === st;
    log.wide = document.documentElement.scrollWidth <= window.innerWidth;
    log.innerWidth = window.innerWidth;
    try { log.saved = JSON.parse(localStorage.getItem("pz:" + sec.dataset.pzId)); } catch (e) { log.saved = null; }
    var doc = window.parent !== window ? window.parent.document : document;
    var out = doc.createElement("pre");
    out.id = "pz-selftest";
    out.textContent = JSON.stringify(log);
    doc.body.appendChild(out);
  }, 50);
})();
"""

WEEKLY_TEST = r"""
(function () {
  var log = { dialogs: 0, errors: [] };
  window.alert = window.confirm = window.prompt = function () { log.dialogs++; };
  window.addEventListener("error", function (e) { log.errors.push(String(e.message)); });
  function key(el, k) { el.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true })); }
  function tap(el) { el.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true })); el.click(); }
  setTimeout(function () {
    var sec = document.querySelector(".pz-k-weekly"), st = JSON.parse(sec.querySelector("script.pz-state").textContent);
    var sol = JSON.parse(atob(st.sol).split("").reverse().join(""));
    function at(y, x) { return sec.querySelector('.pz-in[data-y="' + y + '"][data-x="' + x + '"]'); }
    function act(a) { return sec.querySelector('[data-act="' + a + '"]'); }
    function seg(s) { return sec.querySelector('.pz-seg[data-scope="' + s + '"]'); }
    // progress saved on another day of the same week comes back
    var f = window.WK_FIRST;
    log.restored = at(f[0], f[1]).value === sol[f[0]][f[1]] && at(f[0], f[1]).parentNode.classList.contains("pz-hinted");
    // a wrong letter, checked by word
    var e = st.across[1], c0 = e.cells[0], el = at(c0[0], c0[1]);
    tap(sec.querySelectorAll(".pz-clue")[1]);
    el.focus();
    key(el, sol[c0[0]][c0[1]] === "Q" ? "Z" : "Q");
    el.focus();
    tap(seg("word"));
    tap(act("check"));
    log.checkWord = el.parentNode.classList.contains("pz-bad") && /wrong in this word/.test(sec.querySelector(".pz-status").textContent);
    // reveal just that square
    el.focus();
    tap(seg("square"));
    tap(act("reveal")); tap(act("reveal"));
    log.revealSquare = el.value === sol[c0[0]][c0[1]] && el.parentNode.classList.contains("pz-hinted") && !sec.classList.contains("pz-revealed");
    log.pressed = seg("square").getAttribute("aria-pressed") === "true" && seg("word").getAttribute("aria-pressed") === "false";
    // the clue list follows the grid, and scrolls itself on wide screens
    // a short list forces the inner scroll, whatever this week's clue count
    if (window.WK_SHORT) document.head.appendChild(Object.assign(document.createElement("style"), { textContent: ".pz-wk .pz-clues{max-height:140px}" }));
    var down = st.down[st.down.length - 1];
    var lastBtn = sec.querySelectorAll(".pz-clue")[st.across.length + st.down.length - 1];
    tap(lastBtn);
    var bar = sec.querySelector(".pz-cluebar").textContent;
    log.synced = lastBtn.classList.contains("pz-on") && bar.indexOf(down.num + "D") === 0 &&
      document.activeElement.parentNode.classList.contains("pz-cur");
    var box = lastBtn.closest(".pz-clues");
    log.listScrolls = box.scrollHeight > box.clientHeight + 2;
    log.listTop = box.scrollTop;
    try { log.saved = JSON.parse(localStorage.getItem("pz:" + st.id)); } catch (x) { log.saved = null; }
    log.wide = document.documentElement.scrollWidth <= window.innerWidth;
    log.innerWidth = window.innerWidth;
    var doc = window.parent !== window ? window.parent.document : document;
    var out = doc.createElement("pre");
    out.id = "pz-selftest";
    out.textContent = JSON.stringify(log);
    doc.body.appendChild(out);
  }, 50);
})();
"""


BLOCK_STORAGE = ("Object.defineProperty(window, 'localStorage', "
                 "{get: function () { throw new Error('storage blocked'); }});")


def framed(page_html, width, height=900):
    # headless chrome will not size a window below 500px, so phone widths run in a same-origin frame
    return (f'<!doctype html><html><body style="margin:0"><iframe srcdoc="{html.escape(page_html)}" '
            f'style="width:{width}px;height:{height}px;border:0;display:block"></iframe></body></html>')


def chrome_dom(page_html, width, height=900, scheme=None):
    # headless chrome on macos can hang after printing the dom, so watch the output and kill the group.
    # scheme "dark" or "light" forces prefers-color-scheme
    with tempfile.TemporaryDirectory() as tmp:
        page, out = Path(tmp) / "page.html", Path(tmp) / "dom.html"
        page.write_text(page_html)
        cmd = [str(CHROME), "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
               f"--user-data-dir={tmp}/profile", f"--window-size={width},{height}", "--virtual-time-budget=6000",
               "--dump-dom", page.as_uri()]
        if scheme:
            cmd.insert(-2, f"--blink-settings=preferredColorScheme={0 if scheme == 'dark' else 1}")
        with open(out, "w") as fh:
            proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.DEVNULL, start_new_session=True)
        end = time.monotonic() + 45
        while time.monotonic() < end:
            if proc.poll() is not None or "</html>" in out.read_text(errors="replace"):
                time.sleep(0.2)
                break
            time.sleep(0.2)
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
        return out.read_text(errors="replace")


@unittest.skipUnless(CHROME.exists(), "needs google chrome")
class Interaction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # one puzzle of every kind on a single page
        cls.puzzles, kinds = [], set()
        for d in DAYS:
            for p in ALL[d]:
                if p["kind"] not in kinds:
                    kinds.add(p["kind"])
                    cls.puzzles.append(p)
        cls.puzzles.append(puzzles.weekly_for(DAYS[0]))
        assert len(cls.puzzles) == 6

    def selftest(self, width, head_js=""):
        page = puzzles.demo_page(self.puzzles, extra_js=SELFTEST, head_js=head_js)
        dom = chrome_dom(framed(page, width) if width < 500 else page, max(width, 800))
        m = re.search(r'<pre id="pz-selftest">(.*?)</pre>', dom, re.S)
        self.assertIsNotNone(m, dom[-2000:])
        return json.loads(html.unescape(m.group(1)))

    def check(self, log):
        self.assertEqual(log["dialogs"], 0)
        self.assertEqual(log["errors"], [])
        self.assertEqual(len(log["puzzles"]), 6)
        for r in log["puzzles"]:
            self.assertNotIn("error", r, r.get("error"))
            for k in ("live", "hint", "cleared", "solved", "armed", "revealed"):
                self.assertTrue(r.get(k), (r["id"], k, r))
            if r["kind"] in ("crowns", "sunmoon"):
                self.assertTrue(r.get("keys"), (r["id"], "keys"))
            if r["kind"] == "word":
                for k in ("invalid", "backspace", "feedback", "keyboard", "won"):
                    self.assertTrue(r.get(k), (r["id"], k, r))

    def test_phone_width_with_storage_blocked(self):
        log = self.selftest(375, head_js=BLOCK_STORAGE)
        self.assertEqual(log["innerWidth"], 375)
        self.check(log)
        self.assertTrue(log["wideStart"] and log["wideEnd"])
        self.assertTrue(all(r["wideSolved"] for r in log["puzzles"]))

    def test_desktop(self):
        log = self.selftest(1200)
        self.assertGreater(log["innerWidth"], 1000)
        self.check(log)

    def weekly_run(self, width, short=False):
        p = puzzles.weekly_for(DAYS[0])
        whites = [(y, x) for y, row in enumerate(p["state"]["mask"]) for x, ch in enumerate(row) if ch == "."]
        n, first = len(whites), whites[0]
        cells = ["."] * n
        cells[0] = p["solution"]["rows"][first[0]][first[1]]  # the first white square in reading order, as if hinted
        seed = json.dumps(json.dumps({"cells": "".join(cells), "helped": [0], "done": False}))
        head = (f"window.WK_FIRST={json.dumps(list(first))};window.WK_SHORT={json.dumps(short)};"
                f"try{{localStorage.clear();localStorage.setItem({json.dumps('pz:' + p['id'])},{seed});}}catch(e){{}}")
        page = puzzles.demo_page([p], extra_js=WEEKLY_TEST, head_js=head)
        dom = chrome_dom(framed(page, width, 1400) if width < 500 else page, max(width, 800), 1400)
        m = re.search(r'<pre id="pz-selftest">(.*?)</pre>', dom, re.S)
        self.assertIsNotNone(m, dom[-2000:])
        log = json.loads(html.unescape(m.group(1)))
        self.assertEqual(log["dialogs"], 0)
        self.assertEqual(log["errors"], [])
        for k in ("restored", "checkWord", "revealSquare", "pressed", "synced", "wide"):
            self.assertTrue(log[k], (k, log))
        self.assertEqual(len(log["saved"]["cells"]), n)
        self.assertGreaterEqual(len(log["saved"]["helped"]), 2)
        return log

    def test_weekly_phone(self):
        log = self.weekly_run(390, short=True)
        self.assertEqual(log["innerWidth"], 390)
        self.assertEqual(log["listTop"], 0)  # under the grid the list never scrolls itself

    def test_weekly_desktop(self):
        log = self.weekly_run(1200, short=True)
        self.assertTrue(log["listScrolls"])
        self.assertGreater(log["listTop"], 0)

    def test_hunch_repeats_failure_and_storage(self):
        # a fixed answer with repeated letters, played to six misses in the real page
        p = puzzles.gen_word(DAYS[0], answer="LEVEL")
        js = HUNCH_TEST
        page = puzzles.demo_page([p], extra_js=js)
        dom = chrome_dom(framed(page, 360, 1400), 800)
        m = re.search(r'<pre id="pz-selftest">(.*?)</pre>', dom, re.S)
        self.assertIsNotNone(m, dom[-2000:])
        log = json.loads(html.unescape(m.group(1)))
        self.assertEqual(log["dialogs"], 0)
        self.assertEqual(log["errors"], [])
        self.assertEqual(log["rows"][:3], ["12000", "11020", "00012"])
        self.assertEqual(log["keyE"], "2")  # best mark wins on the key
        self.assertTrue(log["failed"], log)
        self.assertTrue(log["locked"], log)
        self.assertTrue(log["wide"], log)
        self.assertEqual(log["innerWidth"], 360)
        self.assertEqual(log["saved"]["guesses"], ["EERIE", "ELDER", "SKILL", "APPLE", "BREAD", "MOUSE"])


# contrast probe: every puzzle text against the colour actually behind it, alpha composited
CONTRAST = r"""
addEventListener("load", function () {
  var x = document.querySelector(".pz-k-crossword .pz-in:not([readonly])"); if (x) x.focus();
  var r = document.querySelector(".pz-k-sunmoon [data-act=reveal]"); if (r) r.click();
  setTimeout(function () {  // after the colour transitions settle
  function rgba(c) { var m = c.match(/[\d.]+/g).map(Number); return [m[0], m[1], m[2], m.length > 3 ? m[3] : 1]; }
  function over(a, b) { var k = a[3]; return [a[0] * k + b[0] * (1 - k), a[1] * k + b[1] * (1 - k), a[2] * k + b[2] * (1 - k), 1]; }
  function lum(c) { var v = c.slice(0, 3).map(function (x) { x /= 255; return x <= .03928 ? x / 12.92 : Math.pow((x + .055) / 1.055, 2.4); });
                    return .2126 * v[0] + .7152 * v[1] + .0722 * v[2]; }
  function bg(el) {
    var stack = [];
    for (var n = el; n && n.nodeType === 1; n = n.parentElement) {
      var c = rgba(getComputedStyle(n).backgroundColor);
      if (c[3] > 0) stack.push(c);
      if (c[3] >= 1) break;
    }
    var out = [255, 255, 255, 1];
    for (var i = stack.length - 1; i >= 0; i--) out = over(stack[i], out);
    return out;
  }
  function ratio(fg, b) { fg = over(fg, b); var x = lum(fg), y = lum(b); return (Math.max(x, y) + .05) / (Math.min(x, y) + .05); }
  var out = {};
  function note(name, fg, b) { var r = ratio(rgba(fg), b); if (!(name in out) || r < out[name]) out[name] = Math.round(r * 100) / 100; }
  function text(sel, name, pick) {
    document.querySelectorAll(sel).forEach(function (el) {
      if (pick && !pick(el)) return;
      note(name || sel, getComputedStyle(el).color, bg(el));
    });
  }
  text(".pz-tile", "tile", function (t) { return t.textContent && !t.classList.contains("pz-ghost"); });
  ["0", "1", "2"].forEach(function (m) { text(".pz-tile.pz-m" + m, "tile m" + m); text(".pz-key.pz-m" + m, "key m" + m); });
  text(".pz-key"); text(".pz-in", "letter", function (i) { return i.value; }); text(".pz-xc.pz-cur .pz-in", "letter cur");
  text(".pz-xc.pz-on .pz-in", "letter on"); text(".pz-xc.pz-fixed .pz-in", "letter fixed"); text(".pz-xc i", "clue number");
  text(".pz-btn"); text(".pz-btn.pz-armed", "armed"); text(".pz-clue"); text(".pz-cluebar"); text(".pz-help"); text(".pz-lgi");
  text(".pz-title"); text(".pz-instructions"); text(".pz-edge", "edge clue");
  var st = document.querySelector(".pz-status");
  ["", " pz-good", " pz-warn"].forEach(function (t) { st.className = "pz-status" + t; st.textContent = "x"; note("status" + t, getComputedStyle(st).color, bg(st)); });
  // graphics need 3:1 against their square
  document.querySelectorAll(".pz-crowns .pz-cell").forEach(function (c) {
    note("plot letter", getComputedStyle(c, "::before").color, bg(c));
    var cr = c.querySelector(".pz-crown path"); if (cr && !c.classList.contains("pz-clash")) note("crown", getComputedStyle(cr).fill, bg(c));
    var d = c.querySelector(".pz-dot"); if (d) note("dot", getComputedStyle(d).backgroundColor, bg(c));
  });
  document.querySelectorAll(".pz-sm .pz-cell").forEach(function (c) {
    var m = c.querySelector(".pz-moon path"); if (m) note("moon", getComputedStyle(m).fill, bg(c));
    var s = c.querySelector(".pz-sun path"); if (s) note("sun", getComputedStyle(s).stroke, bg(c));
  });
  var blk = document.querySelector(".pz-k-crossword .pz-xc.pz-block"), cell = document.querySelector(".pz-k-crossword .pz-xc:not(.pz-block)");
  out.blockVsCell = Math.round(ratio(rgba(getComputedStyle(blk).backgroundColor), bg(cell)) * 100) / 100;
  out.blockHatch = getComputedStyle(blk).backgroundImage !== "none";
  out.dark = matchMedia("(prefers-color-scheme: dark)").matches;
  out.paper = getComputedStyle(document.body).backgroundColor;
  document.body.setAttribute("data-contrast", JSON.stringify(out));
}, 400); });
"""


def brief_puzzle_page(puzzles_, probe):
    """the five kinds in the brief's own css, with some progress saved so every mark shows"""
    word = puzzles.gen_word(DAYS[0], answer="LEVEL")
    ps = [word] + [p for p in puzzles_ if p["kind"] != "word"]
    by = {p["kind"]: p for p in ps}
    cw, ld, cr, sm = by["crowns"], by["ladder"], by["crossword"], by["sunmoon"]
    n = cw["state"]["n"]
    marks = [0] * (n * n)
    for y, x in enumerate(cw["solution"][:-1]):
        marks[y * n + x] = 2
    for k in range(n * n):
        if not marks[k] and k % 5 == 3:
            marks[k] = 1
    rows = cr["solution"]["rows"]
    seed = {word["id"]: {"guesses": ["EERIE", "ELDER"], "cur": "LE", "hints": [], "done": False},
            cw["id"]: {"marks": marks, "done": False},
            ld["id"]: {"rungs": [ld["solution"][1]] + [""] * (len(ld["solution"]) - 3), "done": False},
            cr["id"]: {"cells": "".join(c for c in rows[0] + rows[1] if c != "#")[:5], "done": False},
            sm["id"]: {"vals": [v if i % 3 == 0 else -1 for i, v in enumerate(sum(sm["solution"], []))], "done": False}}
    head = "try{" + "".join(f"localStorage.setItem({json.dumps('pz:' + k)},{json.dumps(json.dumps(v))});" for k, v in seed.items()) + "}catch(e){}"
    css = (ROOT / "templates" / "play.css").read_text() + (ROOT / "templates" / "brief.css").read_text()
    body = "".join(f'<div class="puzzle">{puzzles.render(p)}</div>' for p in ps)
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="color-scheme" content="light dark">'
            f'<script>{head}</script><style>{css}*{{transition:none!important}}</style></head><body><main class="page"><section class="sec play">'
            f'<div class="puzzles pz-set">{body}</div></section></main><script>{puzzles.PLAY_JS}</script>'
            f'<script>{probe}</script></body></html>')


@unittest.skipUnless(CHROME.exists(), "needs google chrome")
class Themes(unittest.TestCase):
    """puzzles in the brief's real css, light and dark: text passes wcag aa, marks and plots stay readable"""

    @classmethod
    def setUpClass(cls):
        cls.puzzles = Interaction.puzzles if hasattr(Interaction, "puzzles") else None
        if not cls.puzzles:
            Interaction.setUpClass()
            cls.puzzles = Interaction.puzzles

    def probe(self, scheme):
        dom = chrome_dom(brief_puzzle_page(self.puzzles, CONTRAST), 900, 2000, scheme=scheme)
        m = re.search(r'data-contrast="([^"]+)"', dom)
        self.assertIsNotNone(m, dom[-1500:])
        return json.loads(html.unescape(m.group(1)))

    def check(self, r):
        graphics = {"plot letter", "crown", "dot", "moon", "sun"}
        # a dark block on a dark square cannot reach 3:1 without greying the squares, so dark blocks are hatched too
        self.assertTrue(r["blockVsCell"] >= 3 or (r["blockVsCell"] >= 1.2 and r["blockHatch"]), r)
        for k, v in r.items():
            if k in ("dark", "paper", "blockVsCell", "blockHatch"):
                continue
            self.assertGreaterEqual(v, 3 if k in graphics else 4.5, (k, r))
        for k in ("tile m0", "tile m1", "tile m2", "key m0", "key m2", "letter cur", "letter fixed", "armed",
                  "crown", "dot", "plot letter", "moon", "status pz-warn", "status pz-good"):
            self.assertIn(k, r)

    def test_dark(self):
        r = self.probe("dark")
        self.assertTrue(r["dark"])
        self.assertEqual(r["paper"], "rgb(18, 21, 27)")
        self.check(r)

    def test_light(self):
        r = self.probe("light")
        self.assertFalse(r["dark"])
        self.check(r)

    def test_plot_tints_stay_apart(self):
        # every pair of plot colours differs clearly in both themes, and a crown reads on each
        css = (ROOT / "templates" / "play.css").read_text()
        light = re.search(r"\.pz \{(.*?)\}", css, re.S).group(1)
        dark = re.search(r'prefers-color-scheme: dark\) \{\s*:root:not\(\[data-theme="light"\]\) \.pz \{(.*?)\}', css, re.S).group(1)
        attr = re.search(r':root\[data-theme="dark"\] \.pz \{(.*?)\}', css, re.S).group(1)
        self.assertEqual(dark.split(), attr.split())  # the two dark switches must not drift

        def tints(block):
            return [tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) for h in re.findall(r"--pz-r\d: #([0-9a-f]{6})", block)]

        def lin(c):
            return [(x / 255 / 12.92) if x / 255 <= .03928 else ((x / 255 + .055) / 1.055) ** 2.4 for x in c]

        def lum(c):
            v = lin(c)
            return .2126 * v[0] + .7152 * v[1] + .0722 * v[2]

        def lab(c):  # cie lab, d65
            r, g, b = lin(c)
            xyz = ((.4124 * r + .3576 * g + .1805 * b) / .9505, .2126 * r + .7152 * g + .0722 * b,
                   (.0193 * r + .1192 * g + .9505 * b) / 1.089)
            f = [t ** (1 / 3) if t > .008856 else 7.787 * t + 16 / 116 for t in xyz]
            return 116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])
        for block, ink in ((light, (29, 27, 24)), (dark, (236, 230, 218))):
            ts = tints(block)
            self.assertEqual(len(ts), 10)
            for i in range(10):
                hi, lo = sorted((lum(ts[i]), lum(ink)))[::-1]
                self.assertGreaterEqual((hi + .05) / (lo + .05), 4.5, ts[i])
                for j in range(i):
                    de = sum((a - b) ** 2 for a, b in zip(lab(ts[i]), lab(ts[j]))) ** .5
                    self.assertGreater(de, 10, (ts[i], ts[j], de))

    def test_paper_never_goes_dark(self):
        # every dark switch sits inside a screen-only media block, so print and pdf stay light
        for name in ("brief.css", "play.css"):
            css = (ROOT / "templates" / name).read_text()
            for m in re.finditer(r'data-theme="dark"|prefers-color-scheme: dark', css):
                depth, stack = 0, []
                for t in re.finditer(r"@media[^{]*\{|\{|\}", css[:m.start()]):
                    t = t.group(0)
                    if t == "}":
                        depth -= 1
                        if stack and stack[-1][1] == depth:
                            stack.pop()
                        continue
                    if t.startswith("@media"):
                        stack.append((t, depth))
                    depth += 1
                where = " ".join(s for s, _ in stack) + " " + css[max(0, m.start() - 60):m.start()]
                self.assertIn("screen", where, (name, m.start()))


if __name__ == "__main__":
    unittest.main()
