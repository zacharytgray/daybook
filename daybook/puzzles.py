"""daily puzzles for the brief: five a day (three word, two logic) plus a weekly crossword, all original.

  all_for_day(day)    -> [rungs, pocket grid, hunch, crown plots, day and night]
  for_day(day)        -> same list (kept for older callers)
  render(p)           -> html for one puzzle (print block + interactive mount)
  answers_for(day)    -> [{title, answer_text}] for "yesterday's answers"
  weekly_for(day)     -> the crossword for the week holding day (fri to thu)
  weekly_entries(day) -> what the model clues on fridays; clean_weekly_clues checks its clues
  demo_page(x)        -> standalone html page with play.css/play.js inlined
"""
import base64
import datetime as dt
import hashlib
import html
import json
import random
import re
from collections import deque
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets" / "puzzles"
TEMPLATES = ROOT / "templates"
SALT = "pz-2026"

WORD = ["ladder", "crossword", "word"]
LOGIC = ["crowns", "sunmoon"]
CATEGORY = {"ladder": "word", "crossword": "word", "word": "word", "crowns": "logic", "sunmoon": "logic"}


def rng(day, tag):
    h = hashlib.sha256(f"{SALT}:{tag}:{day.isoformat()}".encode()).digest()
    return random.Random(int.from_bytes(h, "big"))


def obf(x):
    # reversed json in base64: enough that a glance at the source does not spoil it
    return base64.b64encode(json.dumps(x, ensure_ascii=True)[::-1].encode()).decode()


def unobf(s):
    return json.loads(base64.b64decode(s).decode()[::-1])


def esc(s):
    return html.escape(str(s))


# ---------- the day's set ----------

def all_for_day(day):
    # word games first, then logic. no answer is shared between the word games of one day
    hunch = gen_word(day)
    ladder = gen_ladder(day, avoid={hunch["solution"]["answer"]})
    grid = gen_crossword(day, avoid=set(ladder["solution"]) | {hunch["solution"]["answer"]})
    return [ladder, grid, hunch, gen_crowns(day), gen_sunmoon(day)]


def for_day(day):
    return all_for_day(day)


def answers_for(day):
    return [{"title": p["title"], "answer_text": p["answer_text"]} for p in for_day(day)]


def base(kind, day, title, tagline, instructions, state, solution, answer_text):
    return {"id": f"{kind}-{day.isoformat()}", "kind": kind, "category": CATEGORY[kind], "title": title,
            "tagline": tagline, "instructions": instructions, "state": state, "solution": solution,
            "answer_text": answer_text}


# ---------- word ladder ----------

@lru_cache(maxsize=None)
def ladder_words(n):
    words = set()
    for w in (ASSETS / f"ladder{n}.txt").read_text().split():
        w = w.strip().lower()
        if len(w) == n and w.isalpha() and w.isascii():
            words.add(w)
    return tuple(sorted(words))


@lru_cache(maxsize=None)
def ladder_graph(n):
    buckets = {}
    for w in ladder_words(n):
        for i in range(n):
            buckets.setdefault(w[:i] + "_" + w[i + 1:], []).append(w)
    adj = {w: set() for w in ladder_words(n)}
    for group in buckets.values():
        for a in group:
            adj[a].update(b for b in group if b != a)
    return {w: sorted(v) for w, v in adj.items()}


def bfs(adj, start):
    dist, prev = {start: 0}, {start: None}
    q = deque([start])
    while q:
        w = q.popleft()
        for v in adj[w]:
            if v not in dist:
                dist[v], prev[v] = dist[w] + 1, w
                q.append(v)
    return dist, prev


def one_apart(a, b):
    return len(a) == len(b) and sum(x != y for x, y in zip(a, b)) == 1


def gen_ladder(day, avoid=()):
    r = rng(day, "ladder")
    n = r.choice([4, 4, 5])
    adj = ladder_graph(n)
    words = [w for w in ladder_words(n) if len(adj[w]) >= 2]
    steps = r.choice([4, 5, 5]) if n == 4 else r.choice([4, 5])
    while True:
        start = r.choice(words)
        dist, prev = bfs(adj, start)
        ends = [w for w, d in dist.items() if d == steps and sum(a != b for a, b in zip(w, start)) == n]
        ends = ends or [w for w, d in dist.items() if d == steps]
        if not ends:
            continue
        end = r.choice(sorted(ends))
        path = [end]
        while prev[path[-1]]:
            path.append(prev[path[-1]])
        path = [w.upper() for w in reversed(path)]
        if not set(path) & set(avoid):
            break
    s, e = path[0], path[-1]
    state = {"len": n, "start": s, "end": e, "blanks": steps - 1,
             "words": [w.upper() for w in ladder_words(n)], "sol": obf(path)}
    return base("ladder", day, "Rungs", "Climb from one word to another, one letter at a time.",
                f"Change one letter per step to turn {s} into {e}. Every rung must be a common English word. "
                f"There are {steps - 1} rungs in between.",
                state, path, ", ".join(path))


def ladder_ok(p, rungs):
    # any shortest path counts: right length, every word real, each one letter from the last
    words = set(ladder_words(p["state"]["len"]))
    path = [p["state"]["start"]] + [w.upper() for w in rungs] + [p["state"]["end"]]
    return (len(rungs) == p["state"]["blanks"] and all(w.lower() in words for w in path)
            and all(one_apart(a, b) for a, b in zip(path, path[1:])))


# ---------- mini crossword ----------

PATTERNS = [
    ["##...", "#....", ".....", "....#", "...##"],
    ["...##", "....#", ".....", "#....", "##..."],
    ["#....", ".....", ".....", ".....", "....#"],
    ["....#", ".....", ".....", ".....", "#...."],
    ["#...#", ".....", ".....", ".....", "#...#"],
]


@lru_cache(maxsize=None)
def bank():
    out = {}
    for line in (ASSETS / "crossword.tsv").read_text().splitlines():
        if "\t" not in line:
            continue
        w, clue = (x.strip() for x in line.split("\t", 1))
        w = w.upper()
        if re.fullmatch(r"[A-Z]{3,5}", w) and clue and w.lower() not in clue.lower():
            out[w] = clue
    return out


@lru_cache(maxsize=None)
def bank_index():
    by_len, idx = {}, {}
    for w in sorted(bank()):
        by_len.setdefault(len(w), []).append(w)
        for i, ch in enumerate(w):
            idx.setdefault((len(w), i, ch), set()).add(w)
    return by_len, idx


def grid_slots(mask):
    n, out = len(mask), []
    for horiz in (True, False):
        for a in range(n):
            run = []
            for b in range(n + 1):
                r, c = (a, b) if horiz else (b, a)
                if b < n and mask[r][c] == ".":
                    run.append((r, c))
                    continue
                if len(run) >= 2:
                    out.append(("across" if horiz else "down", run))
                run = []
    return out


def numbering(mask):
    nums, k = {}, 0
    starts = {cells[0] for _, cells in grid_slots(mask)}
    for r in range(len(mask)):
        for c in range(len(mask)):
            if (r, c) in starts:
                k += 1
                nums[(r, c)] = k
    return nums


class Budget(Exception):
    pass


def fill(mask, r, budget, avoid=()):
    slots = [cells for _, cells in grid_slots(mask)]
    by_len, idx = bank_index()
    grid = {cell: None for cells in slots for cell in cells}
    assign, used, nodes = {}, set(avoid), [0]

    def cands(cells):
        s = None
        for i, cell in enumerate(cells):
            if grid[cell]:
                t = idx.get((len(cells), i, grid[cell]), set())
                s = t if s is None else s & t
                if not s:
                    return []
        return by_len.get(len(cells), []) if s is None else s

    def go():
        nodes[0] += 1
        if nodes[0] > budget:
            raise Budget
        best = None
        for k, cells in enumerate(slots):
            if k in assign:
                continue
            cs = [w for w in cands(cells) if w not in used]
            if not cs:
                return False
            if best is None or len(cs) < len(best[1]):
                best = (k, cs)
        if best is None:
            return True
        k, cs = best
        cs = sorted(cs)
        r.shuffle(cs)
        for w in cs:
            fresh = [cell for cell in slots[k] if grid[cell] is None]
            for i, cell in enumerate(slots[k]):
                grid[cell] = w[i]
            assign[k] = w
            used.add(w)
            if go():
                return True
            del assign[k]
            used.discard(w)
            for cell in fresh:
                grid[cell] = None
        return False

    try:
        if go():
            return ["".join(grid.get((y, x)) or "#" for x in range(len(mask))) for y in range(len(mask))]
    except Budget:
        pass
    return None


def crossword_entries(mask, rows):
    nums, out = numbering(mask), {"across": [], "down": []}
    for d, cells in grid_slots(mask):
        out[d].append({"num": nums[cells[0]], "cells": [list(c) for c in cells],
                       "answer": "".join(rows[y][x] for y, x in cells)})
    for es in out.values():
        es.sort(key=lambda e: e["num"])
    return out


def crossword_ok(mask, rows):
    # every entry is a bank word, used once, and every white cell is crossed both ways
    ents = crossword_entries(mask, rows)
    words = [e["answer"] for d in ents.values() for e in d]
    covered = {"across": set(), "down": set()}
    for d, es in ents.items():
        for e in es:
            covered[d].update(map(tuple, e["cells"]))
    whites = {(y, x) for y in range(len(mask)) for x in range(len(mask)) if mask[y][x] == "."}
    return (all(w in bank() and len(w) >= 3 for w in words) and len(set(words)) == len(words)
            and covered["across"] == whites == covered["down"]
            and all((rows[y][x] == "#") == (mask[y][x] == "#") for y in range(5) for x in range(5)))


def gen_crossword(day, avoid=()):
    r = rng(day, "crossword")
    # staircases fill almost always; the denser shapes get one short try on some days.
    # it runs every day now, so it keeps retrying the staircases rather than giving up
    easy, hard = PATTERNS[:2], PATTERNS[2:]
    r.shuffle(easy)
    order = ([(r.choice(hard), 1500)] if r.random() < 0.4 else []) + [(m, 4000) for m in easy] * 20
    for mask, budget in order:
        rows = fill(mask, r, budget, avoid)
        if rows:
            break
    else:
        raise RuntimeError("no pocket grid found")
    ents = crossword_entries(mask, rows)
    clues = {d: [{"num": e["num"], "clue": bank()[e["answer"]], "cells": e["cells"]} for e in es]
             for d, es in ents.items()}
    state = {"size": 5, "mask": mask, "across": clues["across"], "down": clues["down"], "sol": obf(rows)}
    words = [e["answer"] for e in ents["across"]]
    return base("crossword", day, "Pocket Grid", "A five-by-five crossword for the coffee break.",
                "Fill the grid so every across and down entry answers its clue.",
                state, {"mask": mask, "rows": rows},
                "Across: " + ", ".join(f'{e["num"]} {e["answer"]}' for e in ents["across"]))


# ---------- hunch (five-letter word deduction) ----------

# fine words, but too stiff or too odd to be the morning's answer
HUNCH_SKIP = {"allay", "aptly", "beset", "covet", "edict", "ether", "exalt", "exult", "flier", "forgo", "furor",
              "gaily", "goner", "holey", "homer", "lathe", "leant", "libel", "liken", "login", "miter", "modem",
              "mousy", "nobly", "opine", "pricy", "quark", "shuck", "shyly", "slyly", "staid", "stead", "triad"}


def inflections(w):
    # plurals and past tenses a reader might try on paper, built from the short word lists
    out = set()
    if len(w) == 4 and not re.search(r"(S|X|Z|SH|CH)$", w):
        out.add(w + "S")
    if len(w) == 4 and w.endswith("E"):
        out.add(w + "D")
    if len(w) == 3:
        out.add(w + "ED")
        if re.search(r"(S|X|Z|H)$", w):
            out.add(w + "ES")
    return out


@lru_cache(maxsize=None)
def hunch_answers():
    # ladder words plus the crossword bank's five-letter words, minus plurals and past tenses
    words = {w.upper() for w in ladder_words(5) if w not in HUNCH_SKIP}
    words |= {w for w in bank() if len(w) == 5 and w.lower() not in HUNCH_SKIP and not w.endswith("ED")
              and not re.search(r"[^SUIOA]S$", w)}
    return tuple(sorted(words))


@lru_cache(maxsize=None)
def hunch_common():
    # what a paper solver could fairly think of: every answer, the whole bank, and simple inflections
    short = {w.upper() for w in ladder_words(4)} | {w for w in bank() if len(w) < 5}
    words = set(hunch_answers()) | {w for w in bank() if len(w) == 5}
    for w in short:
        words |= inflections(w)
    return tuple(sorted(words))


@lru_cache(maxsize=None)
def hunch_guesses():
    words = {w.strip().upper() for w in (ASSETS / "guess5.txt").read_text().split()}
    return tuple(sorted(w for w in words | set(hunch_common()) if re.fullmatch(r"[A-Z]{5}", w)))


def score(guess, answer):
    # 2 right spot, 1 in the word elsewhere, 0 not in it. exact hits claim their letters first,
    # so a repeated letter only scores as often as the answer has it
    out, left = [0] * 5, {}
    for i, (g, a) in enumerate(zip(guess, answer)):
        if g == a:
            out[i] = 2
        else:
            left[a] = left.get(a, 0) + 1
    for i, g in enumerate(guess):
        if not out[i] and left.get(g):
            out[i] = 1
            left[g] -= 1
    return "".join(map(str, out))


def hunch_fits(rows, words=None):
    return [w for w in (words or hunch_common()) if all(score(g, w) == s for g, s in rows)]


def hunch_clues(answer, r):
    # printed guesses whose marks leave exactly one common word, without handing it over:
    # at most three hit positions in all, and the last row still has work to do
    words = hunch_common()
    pool = [w for w in hunch_answers() if w != answer]
    for want in ([2, 3] if r.random() < 0.3 else [3]):
        for _ in range(40):
            rows, cands, hits = [], words, set()
            for _ in range(want - 1):
                for _ in range(30):
                    g = r.choice(pool)
                    s = score(g, answer)
                    h = hits | {i for i, k in enumerate(s) if k == "2"}
                    nxt = [w for w in cands if score(g, w) == s]
                    if s != "00000" and len(h) <= 2 and 3 <= len(nxt) < len(cands):
                        rows, cands, hits = rows + [(g, s)], nxt, h
                        break
                else:
                    break
            if len(rows) != want - 1:
                continue
            last = pool[:]
            r.shuffle(last)
            for g in last:
                s = score(g, answer)
                if len(hits | {i for i, k in enumerate(s) if k == "2"}) <= 3 and all(g != x for x, _ in rows):
                    if [w for w in cands if score(g, w) == s] == [answer]:
                        return rows + [(g, s)]
    return None


@lru_cache(maxsize=None)
def hunch_order():
    order = list(hunch_answers())
    random.Random(int.from_bytes(hashlib.sha256(f"{SALT}:hunch".encode()).digest(), "big")).shuffle(order)
    return order


def gen_word(day, answer=None):
    r = rng(day, "word")
    order = hunch_order()
    # walk a fixed shuffle by date, so answers do not repeat for years. a word with no fair paper
    # clues hands over to one 400 or 800 places on, which is never another day of the same year
    picks = [answer.upper()] if answer else [order[(day.toordinal() + k) % len(order)] for k in (0, 400, 800)]
    for ans in picks:
        rows = hunch_clues(ans, r)
        if rows:
            break
    else:
        raise RuntimeError("no hunch clues found")
    state = {"words": "".join(hunch_guesses()), "clues": [[g, s] for g, s in rows], "sol": obf(ans)}
    return base("word", day, "Hunch", "Six tries to find the hidden five-letter word.",
                "Find the hidden five-letter word. A filled box marks a letter in the right spot, a circled "
                "letter is in the word but in another spot, and a plain box means the letter is not in the "
                "word. On paper, the guesses shown leave exactly one common word. On screen, you get six "
                "guesses of your own.",
                state, {"answer": ans, "clues": rows}, ans)


# ---------- logic puzzles: shared ----------
# crown plots and day and night ship as pre-graded pools in assets/puzzles/*.jsonl. the builders
# below made them offline (python3 lib/puzzles.py pool crowns 420); a date only indexes into a pool.
# every pooled puzzle has one solution, falls to the logical solver without guessing, and needs
# its top tiers. the graders also run in the tests.

class Contra(Exception):
    pass


@lru_cache(maxsize=None)
def pool(kind):
    return [json.loads(line) for line in (ASSETS / f"{kind}.jsonl").read_text().splitlines() if line.strip()]


@lru_cache(maxsize=None)
def pool_order(kind):
    order = list(range(len(pool(kind))))
    random.Random(int.from_bytes(hashlib.sha256(f"{SALT}:pool:{kind}".encode()).digest(), "big")).shuffle(order)
    return order


def pool_pick(kind, day):
    # a fixed shuffle walked by date: no repeat until the pool runs out (over a year)
    order = pool_order(kind)
    return pool(kind)[order[day.toordinal() % len(order)]]


def bits(m):
    while m:
        b = m & -m
        yield b.bit_length() - 1
        m ^= b


def run_tiers(tiers, st, done):
    # always the easiest tier that makes progress, then start over. counts steps per tier
    use = [0] * len(tiers)
    try:
        while not done(st):
            for i, f in enumerate(tiers):
                nxt = f(st)
                if nxt is not None:
                    st = nxt
                    use[i] += 1
                    break
            else:
                return {"solved": False, "tiers": use, "top": 0}
    except Contra:
        return {"solved": False, "tiers": use, "top": 0}
    return {"solved": True, "tiers": use, "top": max([i + 1 for i, k in enumerate(use) if k] or [0])}


# ---------- crown plots (one-star regions puzzle) ----------

CROWN_TIERS = ["singles and shared neighbours", "confinement", "pigeonhole", "contradiction"]


def crowns_solve(regions, limit=2):
    n, out = len(regions), []
    cols, regs = set(), set()
    row = []

    def go(y):
        if len(out) >= limit:
            return
        if y == n:
            out.append(row[:])
            return
        for x in range(n):
            g = regions[y][x]
            if x in cols or g in regs or (row and abs(row[-1] - x) < 2):
                continue
            cols.add(x)
            regs.add(g)
            row.append(x)
            go(y + 1)
            row.pop()
            cols.discard(x)
            regs.discard(g)

    go(0)
    return out


def connected(cells):
    cells = set(cells)
    if not cells:
        return True
    seen, stack = set(), [next(iter(cells))]
    while stack:
        y, x = stack.pop()
        if (y, x) in seen:
            continue
        seen.add((y, x))
        stack += [c for c in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)) if c in cells]
    return seen == cells


def nbrs4(y, x, n):
    return [(a, b) for a, b in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)) if 0 <= a < n and 0 <= b < n]


class CrownGrid:
    # cells are bits y*n+x; state is (candidates, crowns)
    def __init__(self, regions):
        n = self.n = len(regions)
        rows = [sum(1 << (y * n + x) for x in range(n)) for y in range(n)]
        cols = [sum(1 << (y * n + x) for y in range(n)) for x in range(n)]
        regs = [0] * n
        for y in range(n):
            for x in range(n):
                regs[regions[y][x]] |= 1 << (y * n + x)
        self.fam, self.units = [rows, cols, regs], rows + cols + regs
        self.nb, self.see = [], []
        for y in range(n):
            for x in range(n):
                m = 0
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        if (dy or dx) and 0 <= y + dy < n and 0 <= x + dx < n:
                            m |= 1 << ((y + dy) * n + x + dx)
                self.nb.append(m)
                self.see.append((m | rows[y] | cols[x] | regs[regions[y][x]]) & ~(1 << (y * n + x)))
        self.tiers = [self.t1, self.t2, self.t3, self.t4]

    def start(self):
        return ((1 << self.n * self.n) - 1, 0)

    def done(self, st):
        return st[1].bit_count() == self.n

    def place(self, st, c):
        cand, crowns = st
        if not cand >> c & 1:
            raise Contra
        return (cand & ~self.see[c] & ~(1 << c), crowns | 1 << c)

    def shared(self, st, masks):
        # cells outside a unit that touch (or see) every option left in it
        cand, crowns = st
        for u in self.units:
            k = cand & u
            if not k or crowns & u:
                continue
            common = -1
            for c in bits(k):
                common &= masks[c]
            kill = common & cand & ~u
            if kill:
                return (cand & ~kill, crowns)
        return None

    def t1(self, st):
        # a row, column or plot with one option left; then cells touching all of a unit's options
        cand, crowns = st
        for u in self.units:
            if crowns & u:
                continue
            k = cand & u
            if not k:
                raise Contra
            if k & (k - 1) == 0:
                return self.place(st, k.bit_length() - 1)
        return self.shared(st, self.nb)

    def t2(self, st):
        # confinement: a unit's options all in one line or plot clear the rest of it
        return self.shared(st, self.see)

    def t3(self, st):
        # pigeonhole: k units of one kind whose options fit in k units of another own those k
        cand, crowns = st
        for a in range(3):
            for b in range(3):
                if a == b:
                    continue
                A, B = self.fam[a], self.fam[b]
                live = [u for u in A if cand & u]
                m = len(live)
                if m < 4:
                    continue
                bm = [sum(1 << j for j, v in enumerate(B) if cand & u & v) for u in live]
                cover = [0] * (1 << m)
                for s in range(1, 1 << m):
                    low = s & -s
                    cover[s] = cover[s ^ low] | bm[low.bit_length() - 1]
                    k = s.bit_count()
                    if k < 2 or 2 * k > m:
                        continue
                    cc = cover[s].bit_count()
                    if cc < k:
                        raise Contra
                    if cc == k:
                        inside = zone = 0
                        for t in bits(s):
                            inside |= live[t]
                        for j in bits(cover[s]):
                            zone |= B[j]
                        kill = cand & zone & ~inside
                        if kill:
                            return (cand & ~kill, crowns)
        return None

    def settle(self, st):
        # tiers 1-3 to a standstill, for the lookahead
        while not self.done(st):
            for f in self.tiers[:3]:
                nxt = f(st)
                if nxt is not None:
                    st = nxt
                    break
            else:
                return st
        return st

    def t4(self, st):
        # contradiction: a crown here leads, by tiers 1-3, to a dead row, column or plot
        cand, crowns = st
        for c in bits(cand):
            try:
                self.settle(self.place(st, c))
            except Contra:
                return (cand & ~(1 << c), crowns)
        return None


def crowns_grade(regions):
    g = CrownGrid(regions)
    return run_tiers(g.tiers, g.start(), g.done)


def crowns_hard(gr):
    # the bar: lookahead at least once and pigeonhole at least three times
    return gr["solved"] and gr["tiers"][3] >= 1 and gr["tiers"][2] >= 3


def crowns_regions(r, n):
    # a random no-touch placement, plots grown around it, then cells moved until one solution is left
    sol = []

    def place(y):
        if y == n:
            return True
        xs = list(range(n))
        r.shuffle(xs)
        for x in xs:
            if x not in sol and (not sol or abs(sol[-1] - x) > 1):
                sol.append(x)
                if place(y + 1):
                    return True
                sol.pop()
        return False

    place(0)
    reg = [[-1] * n for _ in range(n)]
    for y, x in enumerate(sol):
        reg[y][x] = y
    left = n * n - n
    while left:
        front = [(y, x, reg[a][b]) for y in range(n) for x in range(n) if reg[y][x] < 0
                 for a, b in nbrs4(y, x, n) if reg[a][b] >= 0]
        y, x, g = r.choice(front)
        reg[y][x] = g
        left -= 1
    crown = set(enumerate(sol))
    for _ in range(80):
        cg = CrownGrid(reg)
        st = cg.settle(cg.start())
        if cg.done(st):
            return reg, sol
        found = crowns_from(reg, st)
        if len(found) == 1:
            return reg, sol
        alt = next(s for s in found if s != sol)
        moves = []
        for y, x in enumerate(alt):
            if (y, x) in crown:
                continue
            g = reg[y][x]
            if not connected([(a, b) for a in range(n) for b in range(n) if reg[a][b] == g and (a, b) != (y, x)]):
                continue
            moves += [(y, x, reg[a][b]) for a, b in nbrs4(y, x, n) if reg[a][b] != g]
        if not moves:
            return None
        y, x, g = r.choice(sorted(set(moves)))
        reg[y][x] = g
    return None


def crowns_from(regions, st, limit=2):
    # brute force from a part-solved state
    n, (cand, crowns) = len(regions), st
    out = []

    def go(y, cols, regs, prev, acc):
        if len(out) >= limit:
            return
        if y == n:
            out.append(acc[:])
            return
        for x in bits((cand | crowns) >> (y * n) & ((1 << n) - 1)):
            g = regions[y][x]
            if cols >> x & 1 or regs >> g & 1 or (prev >= 0 and abs(prev - x) < 2):
                continue
            acc.append(x)
            go(y + 1, cols | 1 << x, regs | 1 << g, x, acc)
            acc.pop()

    go(0, 0, 0, -1, [])
    return out


def crowns_make(r, n, climb=600):
    # offline: find a puzzle that needs the lookahead, then shift plot borders while it stays
    # logically solvable and gets harder, until it clears the bar
    while True:
        made = crowns_regions(r, n)
        if not made:
            continue
        reg, sol = made
        gr = crowns_grade(reg)
        if not (gr["solved"] and gr["tiers"][3]):
            continue
        crown = set(enumerate(sol))
        key = lambda g: (min(g["tiers"][3], 4), min(g["tiers"][2], 8))
        for _ in range(climb):
            if crowns_hard(gr):
                break
            moves = [(y, x, reg[a][b]) for y in range(n) for x in range(n) if (y, x) not in crown
                     for a, b in nbrs4(y, x, n) if reg[a][b] != reg[y][x]]
            y, x, g = r.choice(moves)
            old = reg[y][x]
            if not connected([(a, b) for a in range(n) for b in range(n) if reg[a][b] == old and (a, b) != (y, x)]):
                continue
            reg[y][x] = g
            nxt = crowns_grade(reg)
            if nxt["solved"] and key(nxt) >= key(gr):
                gr = nxt
            else:
                reg[y][x] = old
        if crowns_hard(gr) and crowns_solve(reg) == [sol]:
            order = []
            for row in reg:
                for g in row:
                    if g not in order:
                        order.append(g)
            reg = [[order.index(g) for g in row] for row in reg]
            return {"n": n, "regions": reg, "sol": sol, "tiers": crowns_grade(reg)["tiers"]}


def gen_crowns(day):
    e = pool_pick("crowns", day)
    n, sol = e["n"], e["sol"]
    state = {"n": n, "regions": e["regions"], "sol": obf(sol)}
    p = base("crowns", day, "Crown Plots", "One crown per row, column and plot.",
             "Place one crown in every row, every column and every lettered plot. "
             "Crowns may not touch each other, not even at a corner.",
             state, sol, "Crown columns, top row first: " + " ".join(str(x + 1) for x in sol))
    p["grade"] = {"tiers": e["tiers"], "names": CROWN_TIERS}
    return p


def crowns_ok(regions, cols):
    n = len(regions)
    return (sorted(cols) == list(range(n)) and len({regions[y][x] for y, x in enumerate(cols)}) == n
            and all(abs(a - b) > 1 for a, b in zip(cols, cols[1:])))


# ---------- day and night (binary grid) ----------

SUN, MOON = 0, 1
SM_TIERS = ["pairs, gaps and signs", "full lines", "line options", "contradiction"]
SM_LINES = [[y * 6 + x for x in range(6)] for y in range(6)] + [[y * 6 + x for y in range(6)] for x in range(6)]


@lru_cache(maxsize=None)
def sm_rows():
    out = []
    for m in range(64):
        row = tuple((m >> (5 - i)) & 1 for i in range(6))
        if sum(row) == 3 and all(not (row[i] == row[i + 1] == row[i + 2]) for i in range(4)):
            out.append(row)
    return out


def sm_solve(givens, edges, limit=2):
    # givens {(y,x): v}; edges [(y, x, "r"|"d", "="|"x")]
    hz = [[] for _ in range(6)]
    vt = [[] for _ in range(6)]
    for y, x, d, k in edges:
        (hz if d == "r" else vt)[y].append((x, k))
    rows_ok = []
    for y in range(6):
        rows_ok.append([row for row in sm_rows()
                        if all(row[x] == v for (yy, x), v in givens.items() if yy == y)
                        and all((row[x] == row[x + 1]) == (k == "=") for x, k in hz[y])])
    out, grid = [], []

    def go(y):
        if len(out) >= limit:
            return
        if y == 6:
            out.append([r[:] for r in grid])
            return
        for row in rows_ok[y]:
            ok = True
            for x in range(6):
                col = [g[x] for g in grid] + [row[x]]
                if col.count(row[x]) > 3 or (y >= 2 and col[-1] == col[-2] == col[-3]):
                    ok = False
                    break
            if ok and y:
                ok = all((grid[y - 1][x] == row[x]) == (k == "=") for x, k in vt[y - 1])
            if ok:
                grid.append(list(row))
                go(y + 1)
                grid.pop()

    go(0)
    return out


class SunMoonGrid:
    # state is a tuple of 36 cells, None, SUN or MOON
    def __init__(self, edges):
        self.pairs = []
        for y, x, d, k in edges:
            a = y * 6 + x
            self.pairs.append((a, a + 1 if d == "r" else a + 6, k == "="))
        self.inline = []
        for line in SM_LINES:
            pos = {c: i for i, c in enumerate(line)}
            self.inline.append([(pos[a], pos[b], eq) for a, b, eq in self.pairs if a in pos and b in pos])
        self.tiers = [self.t1, self.t2, self.t3, self.t4]

    def done(self, st):
        if None in st:
            return False
        self.check(st)
        return True

    def check(self, st):
        for a, b, eq in self.pairs:
            if st[a] is not None and st[b] is not None and (st[a] == st[b]) != eq:
                raise Contra
        for line in SM_LINES:
            v = [st[c] for c in line]
            if v.count(SUN) > 3 or v.count(MOON) > 3:
                raise Contra
            if any(v[i] is not None and v[i] == v[i + 1] == v[i + 2] for i in range(4)):
                raise Contra

    def put(self, st, cells, v):
        g = list(st)
        for c in cells:
            g[c] = v
        return tuple(g)

    def t1(self, st):
        # two alike force both ends, a gap between two alike is the other, and = or x copies across
        self.check(st)
        for a, b, eq in self.pairs:
            for p, q in ((a, b), (b, a)):
                if st[p] is not None and st[q] is None:
                    return self.put(st, [q], st[p] if eq else 1 - st[p])
        for line in SM_LINES:
            v = [st[c] for c in line]
            for i in range(5):
                if v[i] is not None and v[i] == v[i + 1]:
                    for j in (i - 1, i + 2):
                        if 0 <= j < 6 and v[j] is None:
                            return self.put(st, [line[j]], 1 - v[i])
            for i in range(4):
                if v[i] is not None and v[i] == v[i + 2] and v[i + 1] is None:
                    return self.put(st, [line[i + 1]], 1 - v[i])
        return None

    def t2(self, st):
        # a line that already has three of one fills the rest with the other
        for line in SM_LINES:
            v = [st[c] for c in line]
            for s in (SUN, MOON):
                if v.count(s) == 3 and None in v:
                    return self.put(st, [c for c in line if st[c] is None], 1 - s)
        return None

    def t3(self, st):
        # line options: every way to finish one line (counts, no three, its own signs) agrees on a cell
        for li, line in enumerate(SM_LINES):
            v = [st[c] for c in line]
            if None not in v:
                continue
            fits = [row for row in sm_rows() if all(a is None or a == b for a, b in zip(v, row))
                    and all((row[i] == row[j]) == eq for i, j, eq in self.inline[li])]
            if not fits:
                raise Contra
            g = list(st)
            for i in range(6):
                if v[i] is None and len({row[i] for row in fits}) == 1:
                    g[line[i]] = fits[0][i]
            if g != list(st):
                return tuple(g)
        return None

    def settle(self, st):
        while not self.done(st):
            for f in self.tiers[:3]:
                nxt = f(st)
                if nxt is not None:
                    st = nxt
                    break
            else:
                return st
        return st

    def t4(self, st):
        # contradiction: one symbol here breaks a rule by tiers 1-3, so it is the other
        for c in range(36):
            if st[c] is not None:
                continue
            for v in (SUN, MOON):
                try:
                    self.settle(self.put(st, [c], v))
                except Contra:
                    return self.put(st, [c], 1 - v)
        return None


def sm_grade(givens, edges):
    g = SunMoonGrid(edges)
    st = [None] * 36
    for (y, x), v in givens.items():
        st[y * 6 + x] = v
    return run_tiers(g.tiers, tuple(st), g.done)


def sm_hard(gr):
    # the bar: lookahead at least once and line options at least twice
    return gr["solved"] and gr["tiers"][3] >= 1 and gr["tiers"][2] >= 2


def sm_full(r):
    rows = sm_rows()[:]
    grid = []

    def build(y):
        if y == 6:
            return True
        cand = rows[:]
        r.shuffle(cand)
        for row in cand:
            if all(([g[x] for g in grid] + [row[x]]).count(row[x]) <= 3 and
                   not (y >= 2 and grid[-1][x] == grid[-2][x] == row[x]) for x in range(6)):
                grid.append(list(row))
                if build(y + 1):
                    return True
                grid.pop()
        return False

    build(0)
    return grid


def sm_strip(r, sol, n_edges=20):
    # start from every cell plus some true signs, then drop clues one at a time in random order,
    # keeping a drop only if the logical solver still finishes. what is left is minimal
    every = [(y, x, "r", "=" if sol[y][x] == sol[y][x + 1] else "x") for y in range(6) for x in range(5)]
    every += [(y, x, "d", "=" if sol[y][x] == sol[y + 1][x] else "x") for y in range(5) for x in range(6)]
    edges = r.sample(sorted(every), n_edges)
    givens = {(y, x): sol[y][x] for y in range(6) for x in range(6)}
    items = [("g", k) for k in sorted(givens)] + [("e", e) for e in edges]
    r.shuffle(items)
    for kind, k in items:
        if kind == "g":
            v = givens.pop(k)
            if not sm_grade(givens, edges)["solved"]:
                givens[k] = v
        else:
            trial = [e for e in edges if e != k]
            if sm_grade(givens, trial)["solved"]:
                edges = trial
    return givens, sorted(edges)


def sm_make(r, keep=4):
    # offline: strip random grids until a few clear the bar, keep the hardest of them
    best = None
    while keep:
        sol = sm_full(r)
        givens, edges = sm_strip(r, sol)
        gr = sm_grade(givens, edges)
        if not sm_hard(gr) or sm_solve(givens, edges) != [sol]:
            continue
        keep -= 1
        key = (gr["tiers"][3], gr["tiers"][2], -len(givens) - len(edges))
        if best is None or key > best[0]:
            best = (key, {"givens": sorted([y, x, v] for (y, x), v in givens.items()),
                          "edges": [list(e) for e in edges], "sol": sol, "tiers": gr["tiers"]})
    return best[1]


def gen_sunmoon(day):
    e = pool_pick("sunmoon", day)
    sol = e["sol"]
    state = {"givens": e["givens"], "edges": e["edges"], "sol": obf(sol)}
    p = base("sunmoon", day, "Day and Night", "Balance the suns and moons.",
             "Fill every cell with a sun or a moon. Each row and column holds three of each, "
             "and no three of the same symbol sit in a line. Cells joined by = match; cells joined by × differ.",
             state, sol, "Rows, S for sun and M for moon: " + " ".join("".join("SM"[v] for v in row) for row in sol))
    p["grade"] = {"tiers": e["tiers"], "names": SM_TIERS}
    return p


def build_pool(kind, count, procs=None):
    # offline only. job i is seeded by its index, so a rebuild gives the same file
    import multiprocessing
    with multiprocessing.Pool(procs) as mp:
        rows = mp.map(_pool_job, [(kind, i) for i in range(count)], chunksize=1)
    (ASSETS / f"{kind}.jsonl").write_text("".join(json.dumps(x, separators=(",", ":")) + "\n" for x in rows))


def _pool_job(args):
    kind, i = args
    r = random.Random(int.from_bytes(hashlib.sha256(f"{SALT}:build:{kind}:{i}".encode()).digest(), "big"))
    return crowns_make(r, 9 + i % 2) if kind == "crowns" else sm_make(r)


# ---------- the weekly (freeform crossword, friday to thursday) ----------

WEEKLY_EPOCH = dt.date(2026, 10, 2)  # a friday; week 0
WEEKLY_MAX = 15
WEEKLY_SPAN = 13  # a word comes back no sooner than 13 weeks later


def week_friday(day):
    return day - dt.timedelta(days=(day.weekday() - 4) % 7)


@lru_cache(maxsize=None)
def weekly_bank(tier):
    # hard: the 7-8 out of 10 words the grid is built around. mid: everyday long words for crossers
    out = {}
    for line in (ASSETS / f"weekly_{tier}.tsv").read_text().splitlines():
        if "\t" in line:
            w, clue = (x.strip() for x in line.split("\t", 1))
            if re.fullmatch(r"[A-Z]{6,12}", w) and clue:
                out[w] = clue
    return out


def weekly_clue_bank():
    return {**bank(), **weekly_bank("mid"), **weekly_bank("hard")}


@lru_cache(maxsize=None)
def weekly_order(tier):
    words = sorted(bank()) if tier == "short" else sorted(weekly_bank(tier))
    random.Random(int.from_bytes(hashlib.sha256(f"{SALT}:weekly:{tier}".encode()).digest(), "big")).shuffle(words)
    return words


def weekly_window(tier, week):
    # week i draws from its own slice of a fixed shuffle. slices are len/13 long and walk forward,
    # so no word is offered twice within twelve weeks
    order = weekly_order(tier)
    k = len(order) // WEEKLY_SPAN
    return [order[(week * k + t) % len(order)] for t in range(k)]


def weekly_runs(cells):
    # every across and down run of two or more letters
    out = []
    for d, (dy, dx) in (("across", (0, 1)), ("down", (1, 0))):
        for (y, x) in cells:
            if (y - dy, x - dx) in cells or (y + dy, x + dx) not in cells:
                continue
            run = []
            while (y, x) in cells:
                run.append((y, x))
                y, x = y + dy, x + dx
            out.append((d, run))
    return out


def criss(r, pools, target):
    # greedy freeform fill: start from a long hard word, then keep adding the word that crosses the
    # most letters (ties go to harder words, whatever their length, which leaves room for more entries). no letter may touch another word side on.
    # live placements are kept and only rechecked near each new word
    cells, cover, placed, used = {}, {}, [], set()
    box = [0, 0, 0, 0]  # min y, max y, min x, max x
    tier = {w: t for t, ws in pools.items() for w in ws}
    by_letter = {}
    for w in sorted(tier):
        for i, ch in enumerate(w):
            by_letter.setdefault(ch, []).append((w, i))
    bonus = {"hard": 6, "mid": 3, "short": 0}
    live, near = {}, {}  # placement -> (hits, noise); cell -> placements whose footprint holds it

    def span(w, y, x, d):
        dy, dx = (0, 1) if d == "across" else (1, 0)
        return dy, dx, y + dy * (len(w) - 1), x + dx * (len(w) - 1)

    def in_box(w, y, x, d):
        _, _, y2, x2 = span(w, y, x, d)
        return max(box[1], y2) - min(box[0], y) < WEEKLY_MAX and max(box[3], x2) - min(box[2], x) < WEEKLY_MAX

    def fits(w, y, x, d):
        dy, dx, _, _ = span(w, y, x, d)
        n = len(w)
        if w in used or (y - dy, x - dx) in cells or (y + dy * n, x + dx * n) in cells or not in_box(w, y, x, d):
            return -1
        hits = 0
        for k, ch in enumerate(w):
            c = (y + dy * k, x + dx * k)
            got = cells.get(c)
            if got:
                if got != ch or d in cover[c]:
                    return -1
                hits += 1
            elif (c[0] + dx, c[1] + dy) in cells or (c[0] - dx, c[1] - dy) in cells:
                return -1
        return hits if 0 < hits < n else -1

    def footprint(w, y, x, d):
        dy, dx, _, _ = span(w, y, x, d)
        for k in range(-1, len(w) + 1):
            c = (y + dy * k, x + dx * k)
            yield c
            if 0 <= k < len(w):
                yield (c[0] + dx, c[1] + dy)
                yield (c[0] - dx, c[1] - dy)

    def put(w, y, x, d):
        dy, dx, y2, x2 = span(w, y, x, d)
        new = [(y + dy * k, x + dx * k) for k in range(len(w))]
        for c, ch in zip(new, w):
            cells[c] = ch
            cover.setdefault(c, set()).add(d)
        box[:] = [min(box[0], y), max(box[1], y2), min(box[2], x), max(box[3], x2)]
        placed.append((w, y, x, d))
        used.add(w)
        for key in {k for c in new for k in near.get(c, ())}:
            if key in live:
                h = fits(*key)
                if h < 1:
                    del live[key]
                else:
                    live[key] = (h, live[key][1])
        for (cy, cx) in new:
            if len(cover[(cy, cx)]) > 1:
                continue
            nd = "down" if d == "across" else "across"
            for v, i in by_letter.get(cells[(cy, cx)], ()):
                key = (v, cy - i, cx, nd) if nd == "down" else (v, cy, cx - i, nd)
                if key in live:
                    continue
                h = fits(*key)
                if h > 0:
                    live[key] = (h, r.random() * 3)
                    for c in footprint(*key):
                        near.setdefault(c, set()).add(key)

    first = sorted(w for w in pools["hard"] if len(w) >= 9)
    put(r.choice(first or sorted(pools["hard"])), 0, 0, "across")
    while len(placed) < target:
        best = None
        for key, (h, noise) in list(live.items()):
            if key[0] in used or not in_box(*key):
                del live[key]
                continue
            s = 10 * (h - 1) + bonus[tier[key[0]]] + noise
            if best is None or s > best[0]:
                best = (s, key)
        if best is None:
            break
        put(*best[1])
    return placed


def weekly_layout(placed):
    # shift to the origin, number in reading order, and check every run is a placed entry
    y0 = min(p[1] for p in placed)
    x0 = min(p[2] for p in placed)
    cells = {}
    ents = []
    for w, y, x, d in placed:
        dy, dx = (0, 1) if d == "across" else (1, 0)
        cs = [(y - y0 + dy * k, x - x0 + dx * k) for k in range(len(w))]
        for c, ch in zip(cs, w):
            cells[c] = ch
        ents.append((d, cs, w))
    h = max(c[0] for c in cells) + 1
    wd = max(c[1] for c in cells) + 1
    rows = ["".join(cells.get((y, x), "#") for x in range(wd)) for y in range(h)]
    return rows, ents


def weekly_ok(rows, ents):
    # the standard rule: every run of two or more letters is a clued entry, and the grid is one piece
    cells = {(y, x) for y, row in enumerate(rows) for x, ch in enumerate(row) if ch != "#"}
    runs = {(d, tuple(cs)) for d, cs in weekly_runs(cells)}
    mine = {(d, tuple(cs)) for d, cs, _ in ents}
    return runs == mine and connected(cells) and len({w for _, _, w in ents}) == len(ents)


@lru_cache(maxsize=None)
def weekly_grid(friday):
    week = (friday - WEEKLY_EPOCH).days // 7
    r = rng(friday, "weekly")
    pools = {t: weekly_window(t, week) for t in ("hard", "mid", "short")}
    best = None
    for _ in range(10):
        # tries until one has 24+ entries; otherwise the best by entries, crossings and hard words
        placed = criss(r, pools, r.randint(26, 30))
        rows, ents = weekly_layout(placed)
        filled = sum(1 for row in rows for ch in row if ch != "#")
        key = (24 <= len(ents) <= 32 and len(rows) >= 12 and len(rows[0]) >= 12, len(ents),
               sum(len(w) for _, _, w in ents) - filled, sum(w in weekly_bank("hard") for _, _, w in ents))
        if weekly_ok(rows, ents) and (best is None or key > best[0]):
            best = (key, rows, ents)
        if best and best[0][0]:
            break
    if best is None:
        raise RuntimeError("no weekly grid found")
    _, rows, ents = best
    starts = sorted({cs[0] for _, cs, _ in ents})
    num = {c: i + 1 for i, c in enumerate(starts)}
    out = {"across": [], "down": []}
    for d, cs, w in ents:
        out[d].append({"num": num[cs[0]], "answer": w, "cells": [list(c) for c in cs]})
    for es in out.values():
        es.sort(key=lambda e: e["num"])
    return rows, out


def weekly_entries(day):
    # what bin/brief hands the model on fridays
    _, ents = weekly_grid(week_friday(day))
    return [{"num": e["num"], "dir": d, "answer": e["answer"], "enum": f'({len(e["answer"])})'}
            for d in ("across", "down") for e in ents[d]]


def clean_weekly_clues(entries, clues):
    # keep only fair model clues: present, short, no em-dash, and no answer or obvious stem inside
    out = {}
    clues = {str(k).strip().upper(): v for k, v in (clues or {}).items()}
    for e in entries:
        w = e["answer"]
        c = clues.get(w)
        if not isinstance(c, str):
            continue
        c = " ".join(c.split())
        if not c or len(c) > 90 or "\u2014" in c or clue_leaks(w, c):
            continue
        out[w] = c
    return out


def clue_leaks(answer, clue):
    a = answer.lower()
    flat = re.sub(r"[^a-z]", "", clue.lower())
    if len(a) >= 6 and a in flat:  # run-together phrases; short answers hide inside innocent words
        return True
    stems = {a[:max(4, min(6, len(a) - 2))]}
    # the root under a common ending: CREATION -> creat, HAPPINESS -> happ, TEACHER -> teach
    for end in ("iness", "ation", "ness", "ment", "ion", "ity", "ing", "ers", "est", "ed", "er", "es", "ly", "y", "s", "e"):
        if a.endswith(end) and len(a) - len(end) >= 4:
            stems.add(a[:-len(end)])
    for word in re.findall(r"[a-z]+", clue.lower()):
        if any(word.startswith(st) for st in stems):
            return True
        if len(word) >= 4 and (a.startswith(word) or a.endswith(word)) or len(word) >= 5 and word in a:
            return True
    return False


def weekly_for(day, clues=None):
    friday = week_friday(day)
    rows, ents = weekly_grid(friday)
    flat = [dict(e, dir=d) for d in ("across", "down") for e in ents[d]]
    good = clean_weekly_clues(flat, clues)
    fallback = weekly_clue_bank()
    state = {"rows": len(rows), "cols": len(rows[0]), "mask": ["".join("#" if ch == "#" else "." for ch in row) for row in rows],
             "week": friday.isoformat(), "sol": obf(rows)}
    for d in ("across", "down"):
        state[d] = [{"num": e["num"], "clue": good.get(e["answer"]) or fallback[e["answer"]], "cells": e["cells"],
                     "len": len(e["answer"])} for e in ents[d]]
    p = {"id": f"weekly-{friday.isoformat()}", "kind": "weekly", "category": "word", "title": "The Weekly",
         "tagline": "A bigger crossword that lasts all week. A new one comes out every Friday.",
         "instructions": "Fill the grid so every across and down entry answers its clue. Chip away at it through "
                         "the week; next Friday brings a new grid and this one's answers.",
         "state": state, "solution": {"rows": rows, "entries": ents},
         "answer_text": weekly_answer_text(ents), "week_start": friday.isoformat(),
         "week_end": (friday + dt.timedelta(days=6)).isoformat(),
         "clue_source": {"model": sum(1 for e in flat if e["answer"] in good), "bank": sum(1 for e in flat if e["answer"] not in good)}}
    return p


def weekly_answer_text(ents):
    return "; ".join(d.title() + ": " + ", ".join(f'{e["num"]} {e["answer"]}' for e in ents[d]) for d in ("across", "down"))


def weekly_answers_for(day):
    # last week's grid, for fridays
    friday = week_friday(day) - dt.timedelta(days=7)
    _, ents = weekly_grid(friday)
    return {"id": f"weekly-{friday.isoformat()}", "title": "The Weekly", "week_start": friday.isoformat(),
            "answer_text": weekly_answer_text(ents)}


GENERATORS = {"ladder": gen_ladder, "crossword": gen_crossword, "word": gen_word,
              "crowns": gen_crowns, "sunmoon": gen_sunmoon}


# ---------- render ----------

SUN_SVG = ('<svg class="pz-ico pz-sun" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="5.2" />'
           '<path d="M12 1.8v3M12 19.2v3M1.8 12h3M19.2 12h3M4.8 4.8l2.1 2.1M17.1 17.1l2.1 2.1M4.8 19.2l2.1-2.1M17.1 6.9l2.1-2.1" /></svg>')
MOON_SVG = ('<svg class="pz-ico pz-moon" viewBox="0 0 24 24" aria-hidden="true">'
            '<path d="M15.5 3.2a9 9 0 1 0 5.3 13.9A7.4 7.4 0 0 1 15.5 3.2z" /></svg>')


def state_json(p):
    return json.dumps(dict(p["state"], id=p["id"], kind=p["kind"]), ensure_ascii=True).replace("</", "<\\/")


def edge_cls(y, x, n):
    return (" pz-lc" if x == n - 1 else "") + (" pz-lr" if y == n - 1 else "")


def print_ladder(p):
    s = p["state"]
    rows = [s["start"]] + [None] * s["blanks"] + [s["end"]]
    out = ['<div class="pz-ladder-print">']
    for i, w in enumerate(rows):
        cells = "".join(f'<span class="pz-c">{esc(ch)}</span>' if w else '<span class="pz-c"></span>'
                        for ch in (w or " " * s["len"]))
        out.append(f'<div class="pz-rung{" pz-fixed" if w else ""}">{cells}</div>')
    out.append("</div>")
    return "".join(out)


def print_crossword(p):
    s = p["state"]
    nums = {tuple(e["cells"][0]): e["num"] for d in ("across", "down") for e in s[d]}
    cells = []
    for y, row in enumerate(s["mask"]):
        for x, ch in enumerate(row):
            edge = edge_cls(y, x, 5)
            if ch == "#":
                cells.append(f'<span class="pz-c pz-block{edge}"></span>')
            else:
                n = nums.get((y, x))
                cells.append(f'<span class="pz-c{edge}">{f"<i>{n}</i>" if n else ""}</span>')
    lists = "".join(f'<div class="pz-clues"><h4>{d.title()}</h4><ol>'
                    + "".join(f'<li><b>{e["num"]}</b> {esc(e["clue"])}</li>' for e in s[d]) + "</ol></div>"
                    for d in ("across", "down"))
    return (f'<div class="pz-xw-print"><div class="pz-grid" style="--n:5">{"".join(cells)}</div>'
            f'<div class="pz-cluecols">{lists}</div></div>')


MARKS = {"2": "right spot", "1": "in the word, other spot", "0": "not in the word"}


def print_word(p):
    clues = p["state"]["clues"]
    rows = []
    for g, sc in clues:
        rows.append('<div class="pz-wrow">' + "".join(
            f'<span class="pz-wt pz-m{k}" aria-label="{esc(ch)}, {MARKS[k]}">{esc(ch)}</span>' for ch, k in zip(g, sc))
            + "</div>")
    rows += ['<div class="pz-wrow pz-wblank">' + '<span class="pz-wt"></span>' * 5 + "</div>"] * (6 - len(clues))
    legend = "".join(f'<li><span class="pz-wt pz-wmini pz-m{k}"></span>{MARKS[k]}</li>' for k in "210")
    abc = "".join(f"<span>{ch}</span>" for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    return (f'<div class="pz-word-print"><div class="pz-wgrid">{"".join(rows)}</div>'
            f'<div class="pz-wside"><ul class="pz-legend">{legend}</ul>'
            f'<p class="pz-abc-label">Cross off letters as you go</p><p class="pz-abc">{abc}</p></div></div>')


PLOTS = "ABCDEFGHIJKL"


def print_crowns(p):
    s = p["state"]
    n, reg = s["n"], s["regions"]
    cells = []
    for y in range(n):
        for x in range(n):
            g = reg[y][x]
            cls = ["pz-c", f"pz-r{g}" + edge_cls(y, x, n)]
            if x + 1 < n and reg[y][x + 1] != g:
                cls.append("pz-br")
            if y + 1 < n and reg[y + 1][x] != g:
                cls.append("pz-bb")
            cells.append(f'<span class="{" ".join(cls)}"><i>{PLOTS[g]}</i></span>')
    return f'<div class="pz-crowns-print"><div class="pz-grid pz-regions" style="--n:{n}">{"".join(cells)}</div></div>'


def print_sunmoon(p):
    s = p["state"]
    given = {(y, x): v for y, x, v in s["givens"]}
    cells = []
    for y in range(6):
        for x in range(6):
            v = given.get((y, x))
            cells.append(f'<span class="pz-c{edge_cls(y, x, 6)}">{"" if v is None else (SUN_SVG if v == SUN else MOON_SVG)}</span>')
    marks = "".join(f'<span class="pz-edge pz-edge-{d}" style="--y:{y};--x:{x}">{"=" if k == "=" else "&times;"}</span>'
                    for y, x, d, k in s["edges"])
    return f'<div class="pz-sm-print"><div class="pz-grid pz-sm-grid" style="--n:6">{"".join(cells)}{marks}</div></div>'


def print_weekly(p, full=True):
    s = p["state"]
    nums = {tuple(e["cells"][0]): e["num"] for d in ("across", "down") for e in s[d]}
    cells = []
    for y, row in enumerate(s["mask"]):
        for x, ch in enumerate(row):
            edge = (" pz-lc" if x == s["cols"] - 1 else "") + (" pz-lr" if y == s["rows"] - 1 else "")
            if ch == "#":
                cells.append(f'<span class="pz-c pz-block pz-void{edge}"></span>')
            else:
                n = nums.get((y, x))
                cells.append(f'<span class="pz-c{edge}">{f"<i>{n}</i>" if n else ""}</span>')
    if not full:
        return (f'<div class="pz-wk-print pz-wk-short"><p class="pz-wk-note">This week\'s crossword runs until '
                f'{esc(dt.date.fromisoformat(p["week_end"]).strftime("%A %-d %B"))}. Its clues are on the page and in '
                f'Friday\'s print.</p></div>')
    grid = f'<div class="pz-grid pz-wk-grid" style="--n:{s["cols"]}">{"".join(cells)}</div>'
    lists = "".join(f'<div class="pz-clues"><h4>{d.title()}</h4><ol>'
                    + "".join(f'<li><b>{e["num"]}</b> {esc(e["clue"])} <span class="pz-enum">({e["len"]})</span></li>'
                              for e in s[d]) + "</ol></div>" for d in ("across", "down"))
    return f'<div class="pz-wk-print">{grid}<div class="pz-cluecols">{lists}</div></div>'


PRINTERS = {"ladder": print_ladder, "crossword": print_crossword, "word": print_word,
            "crowns": print_crowns, "sunmoon": print_sunmoon, "weekly": print_weekly}


def render(p, body=None):
    return (f'<section class="pz pz-k-{p["kind"]}" id="pz-{esc(p["id"])}" data-pz-id="{esc(p["id"])}">'
            f'<header class="pz-head"><h3 class="pz-title">{esc(p["title"])}</h3>'
            f'<p class="pz-tagline">{esc(p["tagline"])}</p></header>'
            f'<p class="pz-instructions">{esc(p["instructions"])}</p>'
            f'<div class="pz-print">{PRINTERS[p["kind"]](p) if body is None else body}</div>'
            f'<div class="pz-play" data-kind="{p["kind"]}">'
            f'<script type="application/json" class="pz-state">{state_json(p)}</script></div></section>')


def render_weekly(p, print_full=True):
    # print_full: the whole grid and clues (fridays); otherwise one line pointing to the page
    return render(p, print_weekly(p, print_full))


PLAY_CSS = (TEMPLATES / "play.css").read_text()
PLAY_JS = (TEMPLATES / "play.js").read_text()

DEMO_TOKENS = (":root{--paper:#fff;--ink:#1f1d1a;--muted:#6b6a63;--rule:#e4e3dc;--accent:#c6613f;"
               "--accent-soft:#f6e3db;--serif:Georgia,'Times New Roman',serif;"
               "--sans:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif}"
               "@media screen and (prefers-color-scheme:dark){:root:not([data-theme=light]){--paper:#12151b;--ink:#ece6da;"
               "--muted:#b9b1a3;--rule:#262b34;--accent:#ef8f62;--accent-soft:#3a2419}}"
               "@media screen{:root[data-theme=dark]{--paper:#12151b;--ink:#ece6da;--muted:#b9b1a3;--rule:#262b34;"
               "--accent:#ef8f62;--accent-soft:#3a2419}}"
               "@page{size:Letter;margin:.5in}html,body{margin:0;background:var(--paper);color:var(--ink);"
               "font-family:var(--sans)}.demo{max-width:860px;margin:0 auto;padding:24px 16px}"
               ".demo h1{font-family:var(--serif);font-style:italic;font-weight:600;margin:0 0 4px}"
               ".demo .ans{font-size:13px;color:var(--muted)}")


def demo_page(x, extra_js="", head_js=""):
    puzzles = for_day(x) if isinstance(x, dt.date) else list(x)
    label = x.isoformat() if isinstance(x, dt.date) else "puzzles"
    body = "".join(render(p) for p in puzzles)
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="color-scheme" content="light dark">'
            f"<title>Puzzles {esc(label)}</title>{f'<script>{head_js}</script>' if head_js else ''}<style>{DEMO_TOKENS}{PLAY_CSS}</style></head>"
            f'<body><main class="demo"><h1>Puzzles</h1><p class="ans">{esc(label)}</p>'
            f'<div class="pz-set">{body}</div></main>'
            f"<script>{PLAY_JS}</script>{f'<script>{extra_js}</script>' if extra_js else ''}</body></html>")


if __name__ == "__main__":
    import sys
    # python3 -m daybook.puzzles pool crowns|sunmoon COUNT
    if sys.argv[1:2] == ["pool"]:
        build_pool(sys.argv[2], int(sys.argv[3]))
