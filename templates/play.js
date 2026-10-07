/* daily puzzles: hydrates every .pz-play mount. no network, no dialogs, storage is optional */
(function () {
  "use strict";

  function load(id) {
    try { var v = window.localStorage.getItem("pz:" + id); return v ? JSON.parse(v) : null; } catch (e) { return null; }
  }
  function save(id, v) {
    try { window.localStorage.setItem("pz:" + id, JSON.stringify(v)); } catch (e) { /* blocked storage is fine */ }
  }
  function drop(id) {
    try { window.localStorage.removeItem("pz:" + id); } catch (e) { /* same */ }
  }
  function decode(s) { return JSON.parse(atob(s).split("").reverse().join("")); }

  function h(tag, props, kids) {
    var n = document.createElement(tag);
    Object.keys(props || {}).forEach(function (k) {
      var v = props[k];
      if (v == null || v === false) return;
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k === "html") n.innerHTML = v;
      else if (k.slice(0, 2) === "on") n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? "" : v);
    });
    (kids || []).forEach(function (c) {
      if (c != null) n.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return n;
  }

  function edge(y, x, rows, cols) { return (x === cols - 1 ? " pz-lc" : "") + (y === rows - 1 ? " pz-lr" : ""); }

  var SUN = '<svg class="pz-ico pz-sun" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="5.2"/>' +
    '<path d="M12 1.8v3M12 19.2v3M1.8 12h3M19.2 12h3M4.8 4.8l2.1 2.1M17.1 17.1l2.1 2.1M4.8 19.2l2.1-2.1M17.1 6.9l2.1-2.1"/></svg>';
  var MOON = '<svg class="pz-ico pz-moon" viewBox="0 0 24 24" aria-hidden="true">' +
    '<path d="M15.5 3.2a9 9 0 1 0 5.3 13.9A7.4 7.4 0 0 1 15.5 3.2z"/></svg>';
  var CROWN = '<svg class="pz-ico pz-crown" viewBox="0 0 24 24" aria-hidden="true">' +
    '<path d="M3 8l4.5 4L12 5l4.5 7L21 8l-1.8 10H4.8z"/></svg>';

  // toolbar, status line and the solved / revealed bookkeeping shared by every kind
  function shell(root, st, kind) {
    var section = root.closest(".pz") || root;
    var status = h("p", { class: "pz-status", role: "status", "aria-live": "polite" });
    var tools = h("div", { class: "pz-tools" });
    var ctx = { id: st.id, sol: decode(st.sol), done: false, section: section };

    function btn(act, label, fn) {
      var b = h("button", { type: "button", class: "pz-btn", "data-act": act, text: label });
      b.addEventListener("click", fn);
      tools.appendChild(b);
      return b;
    }
    function twoStep(act, label, sure, fn) {
      var armed = false, timer = null;
      var b = btn(act, label, function () {
        if (!armed) {
          armed = true;
          b.textContent = sure;
          b.classList.add("pz-armed");
          timer = setTimeout(reset, 4000);
          return;
        }
        reset();
        fn();
      });
      function reset() { armed = false; clearTimeout(timer); b.textContent = label; b.classList.remove("pz-armed"); }
      b.addEventListener("blur", function () { setTimeout(reset, 150); });
      return b;
    }
    ctx.say = function (msg, tone) {
      status.textContent = msg || "";
      status.className = "pz-status" + (tone ? " pz-" + tone : "");
    };
    ctx.finish = function (how, msg) {
      ctx.done = how;
      section.classList.remove("pz-solved", "pz-revealed");
      section.classList.add(how === "revealed" ? "pz-revealed" : "pz-solved");
      ctx.say(msg || (how === "revealed" ? "Answer revealed. Try again tomorrow." : "Solved! Nice work."), "good");
    };
    ctx.reset = function () {
      ctx.done = false;
      section.classList.remove("pz-solved", "pz-revealed");
      ctx.say("");
    };
    ctx.tools = function (h_) {
      if (h_.check) btn("check", h_.checkLabel || "Check", h_.check);
      btn("hint", "Hint", h_.hint);
      twoStep("reveal", "Reveal", "Tap again to reveal", h_.reveal);
      twoStep("clear", "Clear", "Tap again to clear", function () { drop(st.id); h_.clear(); ctx.reset(); });
      root.appendChild(tools);
      root.appendChild(status);
    };
    ctx.store = function (v) { save(st.id, v); };
    ctx.saved = function () { return load(st.id); };
    return ctx;
  }

  // a grid of single-letter inputs with crossword style movement (ladder and mini crossword)
  function letterGrid(o) {
    var board = h("div", { class: "pz-board pz-letters", style: "--n:" + o.cols, "aria-label": o.label });
    var cells = [], dir = "a", cur = null, at = {};
    o.words.forEach(function (w, i) {
      w.cells.forEach(function (c) { var k = c[0] + "," + c[1]; at[k] = at[k] || {}; at[k][w.dir] = i; });
    });
    function wordOf(y, x, d) {
      var m = at[y + "," + x] || {};
      return m[d] != null ? m[d] : (m.a != null ? m.a : m.d);
    }
    for (var y = 0; y < o.rows; y++) {
      var row = [];
      for (var x = 0; x < o.cols; x++) {
        if (!o.white(y, x)) { board.appendChild(h("div", { class: "pz-xc pz-block" + edge(y, x, o.rows, o.cols), "aria-hidden": "true" })); row.push(null); continue; }
        var fx = o.fixed ? o.fixed(y, x) : null;
        var inp = h("input", {
          class: "pz-in", type: "text", maxlength: "1", autocomplete: "off", autocapitalize: "characters",
          autocorrect: "off", spellcheck: "false", enterkeyhint: "next", "aria-label": o.cellLabel(y, x),
          readonly: fx ? true : null, tabindex: fx ? "-1" : null, "data-y": y, "data-x": x
        });
        if (fx) inp.value = fx;
        var num = o.num ? o.num(y, x) : null;
        var wrap = h("div", { class: "pz-xc" + (fx ? " pz-fixed" : "") + edge(y, x, o.rows, o.cols) }, [num ? h("i", { text: String(num), "aria-hidden": "true" }) : null, inp]);
        board.appendChild(wrap);
        row.push(inp);
        bind(inp, y, x, !!fx);
      }
      cells.push(row);
    }
    function editable(y, x) { var c = cells[y] && cells[y][x]; return c && !c.readOnly ? c : null; }
    function focus(y, x) { var c = editable(y, x); if (c) c.focus(); }
    function highlight() {
      board.querySelectorAll(".pz-on, .pz-cur").forEach(function (n) { n.classList.remove("pz-on", "pz-cur"); });
      if (!cur) return;
      var wi = wordOf(cur[0], cur[1], dir);
      if (wi != null) {
        o.words[wi].cells.forEach(function (c) { cells[c[0]][c[1]].parentNode.classList.add("pz-on"); });
        if (o.onWord) o.onWord(wi);
      }
      cells[cur[0]][cur[1]].parentNode.classList.add("pz-cur");
    }
    function stepWord(wi, delta) {
      var n = o.words.length;
      for (var k = 1; k <= n; k++) {
        var w = o.words[(wi + delta * k + n * 4) % n];
        var empty = w.cells.filter(function (c) { return editable(c[0], c[1]) && !cells[c[0]][c[1]].value; })[0];
        var first = empty || w.cells.filter(function (c) { return editable(c[0], c[1]); })[0];
        if (first) { dir = w.dir; focus(first[0], first[1]); return true; }
      }
      return false;
    }
    function advance(y, x, back) {
      var wi = wordOf(y, x, dir);
      if (wi == null) return;
      var w = o.words[wi].cells, i = -1;
      w.forEach(function (c, j) { if (c[0] === y && c[1] === x) i = j; });
      var j = back ? i - 1 : i + 1;
      while (j >= 0 && j < w.length && !editable(w[j][0], w[j][1])) j += back ? -1 : 1;
      if (j >= 0 && j < w.length) focus(w[j][0], w[j][1]);
      else if (!back) stepWord(wi, 1);
    }
    function move(y, x, dy, dx) {
      for (var yy = y + dy, xx = x + dx; yy >= 0 && yy < o.rows && xx >= 0 && xx < o.cols; yy += dy, xx += dx) {
        if (editable(yy, xx)) { focus(yy, xx); return; }
      }
    }
    function put(inp, ch) {
      inp.value = ch;
      inp.parentNode.classList.remove("pz-bad");
      o.onChange();
    }
    function bind(inp, y, x, fixed) {
      var wasCur = false;
      inp.addEventListener("focus", function () { cur = [y, x]; highlight(); });
      inp.addEventListener("pointerdown", function () { wasCur = cur && cur[0] === y && cur[1] === x && document.activeElement === inp; });
      inp.addEventListener("click", function () {
        var m = at[y + "," + x] || {};
        if (wasCur && m.a != null && m.d != null) { dir = dir === "a" ? "d" : "a"; highlight(); }
        wasCur = false;
      });
      if (fixed) return;
      inp.addEventListener("keydown", function (e) {
        var k = e.key;
        if (e.metaKey || e.ctrlKey || e.altKey) return;
        if (k.length === 1 && /[a-z]/i.test(k)) { e.preventDefault(); put(inp, k.toUpperCase()); advance(y, x, false); }
        else if (k === "Backspace") {
          e.preventDefault();
          if (inp.value) put(inp, "");
          else { advance(y, x, true); var c = document.activeElement; if (c !== inp && c.classList.contains("pz-in")) put(c, ""); }
        }
        else if (k === "Delete") { e.preventDefault(); put(inp, ""); }
        else if (k === "ArrowLeft" || k === "ArrowRight") { e.preventDefault(); dir = "a"; move(y, x, 0, k === "ArrowLeft" ? -1 : 1); highlight(); }
        else if (k === "ArrowUp" || k === "ArrowDown") {
          e.preventDefault();
          if (o.downWords) dir = "d";
          move(y, x, k === "ArrowUp" ? -1 : 1, 0);
          highlight();
        }
        else if (k === "Tab") {
          var wi = wordOf(y, x, dir), d = e.shiftKey ? -1 : 1, nxt = wi + d;
          if (nxt >= 0 && nxt < o.words.length) { e.preventDefault(); stepWord(wi, d); }
        }
        else if (k === " " || k === "Enter") {
          e.preventDefault();
          var m = at[y + "," + x] || {};
          if (k === " " && m.a != null && m.d != null) { dir = dir === "a" ? "d" : "a"; highlight(); }
          else if (k === "Enter") stepWord(wordOf(y, x, dir), 1);
        }
      });
      // phone keyboards often skip keydown, so read whatever landed in the box
      inp.addEventListener("input", function () {
        var v = (inp.value || "").replace(/[^a-z]/gi, "").toUpperCase();
        put(inp, v.slice(-1));
        if (v) advance(y, x, false);
      });
    }
    return {
      board: board, cells: cells,
      get: function (y, x) { return cells[y][x] ? cells[y][x].value : ""; },
      set: function (y, x, v) { if (cells[y][x] && !cells[y][x].readOnly) { cells[y][x].value = v; cells[y][x].parentNode.classList.remove("pz-bad"); } },
      mark: function (y, x, cls, on) { if (cells[y][x]) cells[y][x].parentNode.classList.toggle(cls, on); },
      cur: function () { return cur; },
      dir: function () { return dir; },
      word: function () { return cur ? wordOf(cur[0], cur[1], dir) : null; },
      focusWord: function (wi) { stepWord(wi, 0) || stepWord(wi - 1, 1); },
      highlight: highlight
    };
  }

  // ---------- rungs (word ladder) ----------
  function ladder(root, st) {
    var ctx = shell(root, st), L = st.len, n = st.blanks, sol = ctx.sol;
    var dict = {}; st.words.forEach(function (w) { dict[w] = 1; });
    var words = [];
    for (var r = 1; r <= n; r++) {
      var cs = []; for (var x = 0; x < L; x++) cs.push([r, x]);
      words.push({ dir: "a", cells: cs });
    }
    var g = letterGrid({
      rows: n + 2, cols: L, label: "Word ladder from " + st.start + " to " + st.end, words: words,
      white: function () { return true; },
      fixed: function (y, x) { return y === 0 ? st.start[x] : y === n + 1 ? st.end[x] : null; },
      cellLabel: function (y, x) {
        return y === 0 ? "Start word " + st.start + ", letter " + (x + 1) : y === n + 1 ? "End word " + st.end + ", letter " + (x + 1)
          : "Rung " + y + " of " + n + ", letter " + (x + 1);
      },
      onChange: changed
    });
    g.board.classList.add("pz-ladder");
    root.appendChild(g.board);

    function rung(r) { var s = ""; for (var x = 0; x < L; x++) s += g.get(r, x) || " "; return s; }
    function apart(a, b) { var d = 0; for (var i = 0; i < a.length; i++) if (a[i] !== b[i]) d++; return d === 1; }
    function path() { var p = [st.start]; for (var r = 1; r <= n; r++) p.push(rung(r)); p.push(st.end); return p; }
    function valid(p) {
      for (var i = 1; i < p.length; i++) if (!dict[p[i]] || !apart(p[i - 1], p[i])) return false;
      return true;
    }
    // distance to the end word over the dictionary, for hints that respect the player's own path
    var dist = null;
    function distances() {
      if (dist) return dist;
      dist = {}; dist[st.end] = 0;
      var q = [st.end];
      while (q.length) {
        var w = q.shift();
        for (var i = 0; i < L; i++) for (var c = 65; c < 91; c++) {
          var v = w.slice(0, i) + String.fromCharCode(c) + w.slice(i + 1);
          if (dict[v] && dist[v] == null) { dist[v] = dist[w] + 1; q.push(v); }
        }
      }
      return dist;
    }
    function changed() {
      for (var r = 1; r <= n; r++) for (var x = 0; x < L; x++) g.mark(r, x, "pz-bad", false);
      ctx.store({ rungs: path().slice(1, -1), done: ctx.done });
      if (!ctx.done && valid(path())) ctx.finish("solved");
    }
    function fill(r, w) { for (var x = 0; x < L; x++) g.set(r, x, w[x]); }
    ctx.tools({
      check: function () {
        var p = path(), bad = 0, blank = 0;
        for (var r = 1; r <= n; r++) {
          var w = p[r];
          if (w.indexOf(" ") >= 0) { blank++; continue; }
          if (!dict[w] || !apart(p[r - 1], w)) { bad++; for (var x = 0; x < L; x++) g.mark(r, x, "pz-bad", true); }
        }
        if (valid(p)) ctx.finish("solved");
        else ctx.say(bad ? bad + (bad === 1 ? " rung needs" : " rungs need") + " another look." :
          blank ? "So far so good. " + blank + " to go." : "The last rung does not reach " + st.end + " yet.", bad ? "warn" : "");
      },
      hint: function () {
        var d = distances(), p = path();
        for (var r = 1; r <= n; r++) {
          var w = p[r], prev = p[r - 1];
          if (dict[w] && apart(prev, w) && d[w] === n + 1 - r) continue;
          var opts = Object.keys(dict).filter(function (v) { return apart(prev, v) && d[v] === n + 1 - r; }).sort();
          var pick = opts.indexOf(sol[r]) >= 0 && prev === sol[r - 1] ? sol[r] : opts[0];
          if (!pick) { pick = sol[r]; for (var k = 1; k < r; k++) fill(k, sol[k]); }
          fill(r, pick);
          ctx.say("Rung " + r + " filled in.");
          changed();
          return;
        }
        ctx.say("Every rung already works.");
      },
      reveal: function () { for (var r = 1; r <= n; r++) fill(r, sol[r]); ctx.finish("revealed"); changed(); },
      clear: function () { ctx.done = false; for (var r = 1; r <= n; r++) for (var x = 0; x < L; x++) g.set(r, x, ""); }
    });
    var s = ctx.saved();
    if (s && s.rungs) {
      s.rungs.forEach(function (w, i) { for (var x = 0; x < L; x++) g.set(i + 1, x, (w[x] || "").trim()); });
      if (s.done === "revealed") ctx.finish("revealed");
      else if (valid(path())) ctx.finish("solved");
    }
  }

  // ---------- pocket grid (mini crossword) ----------
  function crossword(root, st) {
    var ctx = shell(root, st), N = st.size, mask = st.mask, rows = ctx.sol;
    var words = [], nums = {};
    ["across", "down"].forEach(function (d) {
      st[d].forEach(function (e) {
        words.push({ dir: d === "across" ? "a" : "d", cells: e.cells, num: e.num, clue: e.clue, d: d });
        nums[e.cells[0][0] + "," + e.cells[0][1]] = e.num;
      });
    });
    function lab(wi) { var w = words[wi]; return w.num + (w.d === "across" ? " Across" : " Down"); }
    var bar = h("p", { class: "pz-cluebar", "aria-live": "polite" });
    var g = letterGrid({
      rows: N, cols: N, label: "Crossword grid", words: words, downWords: true,
      white: function (y, x) { return mask[y][x] === "."; },
      num: function (y, x) { return nums[y + "," + x]; },
      cellLabel: function (y, x) {
        var parts = [];
        words.forEach(function (w, i) {
          w.cells.forEach(function (c, j) { if (c[0] === y && c[1] === x) parts.push(lab(i) + " letter " + (j + 1)); });
        });
        return parts.join(", ");
      },
      onChange: changed,
      onWord: function (wi) {
        bar.textContent = "";
        bar.appendChild(h("b", { text: lab(wi).replace(" Across", "A").replace(" Down", "D") }));
        bar.appendChild(document.createTextNode(" " + words[wi].clue));
        clueBtns.forEach(function (b, i) { b.classList.toggle("pz-on", i === wi); });
      }
    });
    var wrap = h("div", { class: "pz-xw" });
    var left = h("div", { class: "pz-xw-main" }, [bar, g.board]);
    var clueBtns = [];
    var lists = h("div", { class: "pz-cluecols" });
    ["across", "down"].forEach(function (d) {
      var ol = h("ol");
      words.forEach(function (w, i) {
        if (w.d !== d) return;
        var b = h("button", { type: "button", class: "pz-clue", "aria-label": lab(i) + ": " + w.clue }, [h("b", { text: String(w.num) }), " " + w.clue]);
        b.addEventListener("click", function () { g.focusWord(i); });
        clueBtns[i] = b;
        ol.appendChild(h("li", {}, [b]));
      });
      lists.appendChild(h("div", { class: "pz-clues" }, [h("h4", { text: d === "across" ? "Across" : "Down" }), ol]));
    });
    wrap.appendChild(left);
    wrap.appendChild(lists);
    root.appendChild(wrap);
    bar.textContent = "Tap a square to start. Tap it again to switch direction.";

    function whites(fn) { for (var y = 0; y < N; y++) for (var x = 0; x < N; x++) if (mask[y][x] === ".") fn(y, x); }
    function solved() { var ok = true; whites(function (y, x) { if (g.get(y, x) !== rows[y][x]) ok = false; }); return ok; }
    function changed() {
      var v = []; whites(function (y, x) { v.push(g.get(y, x) || "."); });
      ctx.store({ cells: v.join(""), done: ctx.done });
      if (!ctx.done && solved()) ctx.finish("solved");
    }
    ctx.tools({
      check: function () {
        var bad = 0, empty = 0;
        whites(function (y, x) {
          var v = g.get(y, x);
          if (!v) empty++;
          else if (v !== rows[y][x]) { bad++; g.mark(y, x, "pz-bad", true); }
        });
        if (solved()) ctx.finish("solved");
        else ctx.say(bad ? bad + (bad === 1 ? " square is" : " squares are") + " wrong." : "All correct so far. " + empty + " to go.", bad ? "warn" : "");
      },
      hint: function () {
        var c = g.cur(), target = null;
        function wrong(y, x) { return g.get(y, x) !== rows[y][x]; }
        if (c && wrong(c[0], c[1])) target = c;
        var wi = g.word();
        if (!target && wi != null) words[wi].cells.forEach(function (cc) { if (!target && wrong(cc[0], cc[1])) target = cc; });
        if (!target) whites(function (y, x) { if (!target && wrong(y, x)) target = [y, x]; });
        if (!target) { ctx.say("Nothing left to hint."); return; }
        g.set(target[0], target[1], rows[target[0]][target[1]]);
        g.mark(target[0], target[1], "pz-hinted", true);
        ctx.say("One square filled in.");
        changed();
      },
      reveal: function () { whites(function (y, x) { g.set(y, x, rows[y][x]); }); ctx.finish("revealed"); changed(); },
      clear: function () { whites(function (y, x) { g.set(y, x, ""); g.mark(y, x, "pz-hinted", false); }); ctx.done = false; }
    });
    var s = ctx.saved();
    if (s && s.cells) {
      var i = 0;
      whites(function (y, x) { var ch = s.cells[i++]; g.set(y, x, ch && ch !== "." ? ch : ""); });
      if (s.done === "revealed") ctx.finish("revealed");
      else if (solved()) ctx.finish("solved");
    }
  }

  // ---------- hunch (five-letter word) ----------
  var KEYROWS = ["QWERTYUIOP", "ASDFGHJKL", "+ZXCVBNM-"];
  var MARK = ["not in the word", "in the word, other spot", "right spot"];
  // 2 right spot, 1 elsewhere in the word, 0 not in it. exact hits claim letters first, same as lib/puzzles.py
  function score(g, a) {
    var out = [0, 0, 0, 0, 0], left = {};
    for (var i = 0; i < 5; i++) { if (g[i] === a[i]) out[i] = 2; else left[a[i]] = (left[a[i]] || 0) + 1; }
    for (var j = 0; j < 5; j++) if (!out[j] && left[g[j]]) { out[j] = 1; left[g[j]]--; }
    return out;
  }
  function word(root, st) {
    var ctx = shell(root, st), answer = ctx.sol, MAX = 6;
    var dict = {};
    for (var i = 0; i + 5 <= st.words.length; i += 5) dict[st.words.slice(i, i + 5)] = 1;
    var guesses = [], cur = "", hints = [], shown = false;

    var board = h("div", { class: "pz-wboard", tabindex: "0", role: "group", "aria-label": "Hunch board. Type a five-letter word, then press Enter." });
    var rows = [], tiles = [];
    for (var r = 0; r < MAX; r++) {
      var row = h("div", { class: "pz-wline", role: "group" }), line = [];
      for (var x = 0; x < 5; x++) { var t = h("span", { class: "pz-tile", role: "img" }); row.appendChild(t); line.push(t); }
      board.appendChild(row);
      rows.push(row);
      tiles.push(line);
    }
    var keys = {}, kb = h("div", { class: "pz-kb", role: "group", "aria-label": "Letter keys" });
    KEYROWS.forEach(function (ks, ri) {
      var row = h("div", { class: "pz-kbrow" });
      if (ri === 1) row.appendChild(h("span", { class: "pz-kgap", "aria-hidden": "true" }));
      ks.split("").forEach(function (k) {
        var name = k === "+" ? "Enter" : k === "-" ? "Backspace" : k;
        var b = h("button", { type: "button", class: "pz-key" + (k === "+" || k === "-" ? " pz-wide" : ""), tabindex: "-1",
          "data-key": name, "aria-label": k === "+" ? "Enter, submit guess" : k === "-" ? "Delete letter" : k,
          text: k === "+" ? "Enter" : k === "-" ? "Del" : k });
        b.addEventListener("click", function () {
          press(name);
          try { board.focus({ preventScroll: true }); } catch (e) { board.focus(); }
        });
        if (name.length === 1) keys[k] = b;
        row.appendChild(b);
      });
      if (ri === 1) row.appendChild(h("span", { class: "pz-kgap", "aria-hidden": "true" }));
      kb.appendChild(row);
    });
    var legend = h("p", { class: "pz-help pz-wlegend" }, [2, 1, 0].map(function (m) {
      return h("span", { class: "pz-lgi" }, [h("span", { class: "pz-lg pz-m" + m, "aria-hidden": "true" }), MARK[m]]);
    }));
    var help = h("p", { class: "pz-help", text: "Type on your keyboard or tap the keys. Enter makes the guess." });
    var wrap = h("div", { class: "pz-word" }, [board, kb, legend, help]);
    root.appendChild(wrap);

    function persist() { ctx.store({ guesses: guesses, cur: cur, hints: hints, done: ctx.done }); }
    function shake() {
      var row = rows[guesses.length];
      if (!row) return;
      row.classList.remove("pz-shake");
      void row.offsetWidth;
      row.classList.add("pz-shake");
      setTimeout(function () { row.classList.remove("pz-shake"); }, 450);
    }
    function known() {
      var k = {};
      guesses.forEach(function (g) { var s = score(g, answer); for (var i = 0; i < 5; i++) if (s[i] === 2) k[i] = g[i]; });
      hints.forEach(function (i) { k[i] = answer[i]; });
      return k;
    }
    function draw() {
      var best = {}, hinted = {};
      hints.forEach(function (i) { hinted[i] = answer[i]; best[answer[i]] = 2; });
      for (var r = 0; r < MAX; r++) {
        var parts = [], g = guesses[r], s = g ? score(g, answer) : null, now = r === guesses.length && !ctx.done;
        var last = r === guesses.length && shown && ctx.done === "revealed";
        for (var x = 0; x < 5; x++) {
          var t = tiles[r][x], ch = "", m = null, ghost = false, lab;
          if (g) { ch = g[x]; m = s[x]; best[ch] = Math.max(best[ch] == null ? -1 : best[ch], m); }
          else if (last) { ch = answer[x]; m = 2; }
          else if (now) { ch = cur[x] || ""; if (!ch && hinted[x]) { ch = hinted[x]; ghost = true; } }
          t.textContent = ch;
          t.className = "pz-tile" + (m != null ? " pz-m" + m : ch && !ghost ? " pz-typed" : "") + (ghost ? " pz-ghost" : "") +
            (last ? " pz-shown" : "") + (now && x === Math.min(cur.length, 4) ? " pz-at" : "");
          lab = m != null ? ch + ", " + MARK[m] : ghost ? "hint, " + ch : ch || "empty";
          t.setAttribute("aria-label", lab);
          parts.push(lab);
        }
        rows[r].setAttribute("aria-label", (g ? "Guess " + (r + 1) : last ? "Answer" : "Row " + (r + 1)) + ": " + parts.join("; "));
        rows[r].classList.toggle("pz-now", now);
      }
      Object.keys(keys).forEach(function (k) {
        var m = best[k];
        keys[k].className = "pz-key" + (m != null && m >= 0 ? " pz-m" + m : "");
        keys[k].setAttribute("aria-label", k + (m != null && m >= 0 ? ", " + MARK[m] : ""));
      });
    }
    function fail() {
      ctx.done = "revealed";
      ctx.section.classList.add("pz-revealed");
      ctx.say("Out of guesses. The word was " + answer + ".", "warn");
    }
    function won() {
      ctx.finish("solved");
      var n = guesses.length;
      ctx.say("Solved in " + n + (n === 1 ? " guess" : " guesses") + ". Nice work.", "good");
    }
    function submit() {
      if (cur.length < 5) { ctx.say("Not enough letters. A guess needs five.", "warn"); shake(); return; }
      if (!dict[cur]) { ctx.say(cur + " is not in the word list.", "warn"); shake(); return; }
      guesses.push(cur);
      cur = "";
      if (guesses[guesses.length - 1] === answer) won();
      else if (guesses.length >= MAX) fail();
      else { var left = MAX - guesses.length; ctx.say(left + (left === 1 ? " guess" : " guesses") + " left."); }
      draw();
      persist();
    }
    function press(k) {
      if (ctx.done) return;
      if (k === "Enter") { submit(); return; }
      if (k === "Backspace") cur = cur.slice(0, -1);
      else if (/^[A-Z]$/.test(k) && cur.length < 5) cur += k;
      else return;
      ctx.say("");
      draw();
      persist();
    }
    function onKey(e) {
      if (e.metaKey || e.ctrlKey || e.altKey || ctx.done) return;
      var k = e.key;
      if (k && k.length === 1 && /[a-z]/i.test(k)) k = k.toUpperCase();
      else if (k !== "Enter" && k !== "Backspace") return;
      e.preventDefault();
      press(k);
    }
    wrap.addEventListener("keydown", onKey);
    // typing with nothing focused also lands here, so a desktop reader can just start
    document.addEventListener("keydown", function (e) {
      var a = document.activeElement;
      if (!e.defaultPrevented && (!a || a === document.body)) onKey(e);
    });
    ctx.tools({
      hint: function () {
        if (ctx.done) { ctx.say("This one is finished."); return; }
        var k = known();
        for (var i = 0; i < 5; i++) if (k[i] == null) {
          hints.push(i);
          ctx.say("Hint: letter " + (i + 1) + " is " + answer[i] + ".");
          draw();
          persist();
          return;
        }
        ctx.say("Every letter is already in place.");
      },
      reveal: function () {
        shown = true;
        cur = "";
        ctx.finish("revealed");
        ctx.say("The word was " + answer + ".", "good");
        draw();
        persist();
      },
      clear: function () { guesses = []; cur = ""; hints = []; shown = false; ctx.done = false; draw(); }
    });
    var s = ctx.saved();
    if (s && s.guesses) {
      guesses = s.guesses.filter(function (g) { return dict[g]; }).slice(0, MAX);
      cur = typeof s.cur === "string" ? s.cur.replace(/[^A-Z]/g, "").slice(0, 5) : "";
      hints = (s.hints || []).filter(function (i) { return i >= 0 && i < 5; });
      var at = guesses.indexOf(answer);
      if (at >= 0) { guesses = guesses.slice(0, at + 1); won(); }
      else if (guesses.length >= MAX) fail();
      else if (s.done === "revealed") { shown = true; ctx.finish("revealed"); ctx.say("The word was " + answer + ".", "good"); }
    }
    draw();
  }

  // ---------- shared button grid for the two logic kinds ----------
  function buttonGrid(n, label, cellLabel, onAct) {
    var board = h("div", { class: "pz-board pz-btngrid", role: "grid", "aria-label": label, style: "--n:" + n });
    var cells = [], cur = [0, 0];
    for (var y = 0; y < n; y++) {
      var row = h("div", { role: "row", class: "pz-row" }), line = [];
      for (var x = 0; x < n; x++) {
        var b = h("button", { type: "button", role: "gridcell", class: "pz-cell" + edge(y, x, n, n), tabindex: y + x === 0 ? "0" : "-1", "data-y": y, "data-x": x });
        (function (b, y, x) {
          b.addEventListener("click", function () { cur = [y, x]; rove(); onAct(y, x, "cycle"); });
          b.addEventListener("keydown", function (e) {
            var k = e.key, dy = 0, dx = 0;
            if (k === "ArrowUp") dy = -1; else if (k === "ArrowDown") dy = 1; else if (k === "ArrowLeft") dx = -1; else if (k === "ArrowRight") dx = 1;
            if (dy || dx) {
              e.preventDefault();
              cur = [Math.max(0, Math.min(n - 1, y + dy)), Math.max(0, Math.min(n - 1, x + dx))];
              rove();
              cells[cur[0]][cur[1]].focus();
              return;
            }
            var act = (k === " " || k === "Enter") ? "cycle" : (k === "Backspace" || k === "Delete" || k === "0") ? "clear" : /^[1-9a-z]$/i.test(k) ? k.toLowerCase() : null;
            if (act) { e.preventDefault(); onAct(y, x, act); }
          });
        })(b, y, x);
        b.setAttribute("aria-label", cellLabel(y, x));
        row.appendChild(b);
        line.push(b);
      }
      board.appendChild(row);
      cells.push(line);
    }
    function rove() { cells.forEach(function (l) { l.forEach(function (b) { b.tabIndex = -1; }); }); cells[cur[0]][cur[1]].tabIndex = 0; }
    return { board: board, cells: cells };
  }

  // ---------- crown plots ----------
  function crowns(root, st) {
    var ctx = shell(root, st), n = st.n, reg = st.regions, sol = ctx.sol, L = "ABCDEFGHIJKL";
    var marks = []; for (var i = 0; i < n * n; i++) marks.push(0);
    var names = ["empty", "marked empty", "crown"];
    var g = buttonGrid(n, "Crown plots, " + n + " by " + n, function (y, x) { return lab(y, x); }, act);
    function lab(y, x) { return "Row " + (y + 1) + ", column " + (x + 1) + ", plot " + L[reg[y][x]] + ", " + names[marks[y * n + x]]; }
    g.board.classList.add("pz-crowns");
    for (var y = 0; y < n; y++) for (var x = 0; x < n; x++) {
      var c = g.cells[y][x], r = reg[y][x];
      c.classList.add("pz-r" + r);
      c.setAttribute("data-plot", L[r]);
      if (x + 1 < n && reg[y][x + 1] !== r) c.classList.add("pz-br");
      if (y + 1 < n && reg[y + 1][x] !== r) c.classList.add("pz-bb");
      if (x > 0 && reg[y][x - 1] !== r) c.classList.add("pz-bl");
      if (y > 0 && reg[y - 1][x] !== r) c.classList.add("pz-bt");
    }
    root.appendChild(g.board);
    root.appendChild(h("p", { class: "pz-help", text: "Tap once to mark a square empty, twice for a crown. Keys: arrows move, Space cycles, C crown, X mark." }));

    function act(y, x, a) {
      if (ctx.done === "revealed") return;
      var k = y * n + x;
      if (a === "cycle") marks[k] = (marks[k] + 1) % 3;
      else if (a === "clear") marks[k] = 0;
      else if (a === "c") marks[k] = marks[k] === 2 ? 0 : 2;
      else if (a === "x") marks[k] = marks[k] === 1 ? 0 : 1;
      else return;
      changed();
    }
    function crownsAt() { var out = []; for (var k = 0; k < n * n; k++) if (marks[k] === 2) out.push([Math.floor(k / n), k % n]); return out; }
    function clashes() {
      var cs = crownsAt(), bad = {};
      cs.forEach(function (a, i) {
        cs.forEach(function (b, j) {
          if (i >= j) return;
          if (a[0] === b[0] || a[1] === b[1] || reg[a[0]][a[1]] === reg[b[0]][b[1]] || (Math.abs(a[0] - b[0]) < 2 && Math.abs(a[1] - b[1]) < 2)) {
            bad[a[0] * n + a[1]] = 1; bad[b[0] * n + b[1]] = 1;
          }
        });
      });
      return bad;
    }
    function draw(checked) {
      var bad = clashes();
      for (var y = 0; y < n; y++) for (var x = 0; x < n; x++) {
        var k = y * n + x, c = g.cells[y][x];
        c.innerHTML = marks[k] === 2 ? CROWN : marks[k] === 1 ? '<span class="pz-dot" aria-hidden="true"></span>' : "";
        c.classList.toggle("pz-has", marks[k] === 2);
        c.classList.toggle("pz-clash", !!bad[k]);
        c.classList.toggle("pz-bad", !!checked && marks[k] === 2 && sol[y] !== x);
        c.setAttribute("aria-label", lab(y, x));
      }
    }
    function solved() { var cs = crownsAt(); return cs.length === n && cs.every(function (c) { return sol[c[0]] === c[1]; }); }
    function changed() {
      draw(false);
      ctx.store({ marks: marks, done: ctx.done });
      if (!ctx.done && solved()) ctx.finish("solved");
    }
    ctx.tools({
      check: function () {
        draw(true);
        var wrong = crownsAt().filter(function (c) { return sol[c[0]] !== c[1]; }).length;
        if (solved()) ctx.finish("solved");
        else ctx.say(wrong ? wrong + (wrong === 1 ? " crown is" : " crowns are") + " in the wrong place." : "No mistakes so far. " + (n - crownsAt().length) + " crowns to go.", wrong ? "warn" : "");
      },
      hint: function () {
        var wrong = crownsAt().filter(function (c) { return sol[c[0]] !== c[1]; })[0];
        if (wrong) { marks[wrong[0] * n + wrong[1]] = 0; ctx.say("Removed a misplaced crown."); changed(); return; }
        for (var y = 0; y < n; y++) if (marks[y * n + sol[y]] !== 2) {
          marks[y * n + sol[y]] = 2;
          ctx.say("Placed a crown in row " + (y + 1) + ".");
          changed();
          return;
        }
      },
      reveal: function () {
        for (var k = 0; k < n * n; k++) marks[k] = 0;
        sol.forEach(function (x, y) { marks[y * n + x] = 2; });
        ctx.finish("revealed");
        changed();
      },
      clear: function () { for (var k = 0; k < n * n; k++) marks[k] = 0; ctx.done = false; draw(false); }
    });
    var s = ctx.saved();
    if (s && s.marks && s.marks.length === n * n) {
      marks = s.marks.map(function (v) { return v === 1 || v === 2 ? v : 0; });
      if (s.done === "revealed") ctx.finish("revealed");
      else if (solved()) ctx.finish("solved");
    }
    draw(false);
  }

  // ---------- day and night ----------
  function sunmoon(root, st) {
    var ctx = shell(root, st), sol = ctx.sol, N = 6;
    var given = {}, vals = [];
    st.givens.forEach(function (t) { given[t[0] * N + t[1]] = t[2]; });
    for (var k = 0; k < N * N; k++) vals.push(given[k] != null ? given[k] : -1);
    var names = { "-1": "empty", "0": "sun", "1": "moon" };
    var g = buttonGrid(N, "Day and night, 6 by 6", function (y, x) { return lab(y, x); }, act);
    function lab(y, x) { var k = y * N + x; return "Row " + (y + 1) + ", column " + (x + 1) + ", " + names[vals[k]] + (given[k] != null ? ", given" : ""); }
    g.board.classList.add("pz-sm");
    for (var y = 0; y < N; y++) for (var x = 0; x < N; x++) if (given[y * N + x] != null) {
      g.cells[y][x].classList.add("pz-given");
      g.cells[y][x].setAttribute("aria-disabled", "true");
    }
    st.edges.forEach(function (e) {
      g.board.appendChild(h("span", { class: "pz-edge pz-edge-" + e[2], style: "--y:" + e[0] + ";--x:" + e[1], "aria-hidden": "true", text: e[3] === "=" ? "=" : "×" }));
    });
    root.appendChild(g.board);
    root.appendChild(h("p", { class: "pz-help", text: "Tap to cycle sun, moon, empty. Keys: arrows move, Space cycles, S sun, M moon." }));

    function act(y, x, a) {
      var k = y * N + x;
      if (given[k] != null || ctx.done === "revealed") return;
      if (a === "cycle") vals[k] = vals[k] === -1 ? 0 : vals[k] === 0 ? 1 : -1;
      else if (a === "clear") vals[k] = -1;
      else if (a === "s" || a === "1") vals[k] = 0;
      else if (a === "m" || a === "2") vals[k] = 1;
      else return;
      changed();
    }
    function errors() {
      var bad = {};
      function v(y, x) { return vals[y * N + x]; }
      for (var i = 0; i < N; i++) {
        [0, 1].forEach(function (s) {
          var rc = 0, cc = 0;
          for (var j = 0; j < N; j++) { if (v(i, j) === s) rc++; if (v(j, i) === s) cc++; }
          for (var j2 = 0; j2 < N; j2++) { if (rc > 3 && v(i, j2) === s) bad[i * N + j2] = 1; if (cc > 3 && v(j2, i) === s) bad[j2 * N + i] = 1; }
        });
        for (var j3 = 0; j3 + 2 < N; j3++) {
          if (v(i, j3) >= 0 && v(i, j3) === v(i, j3 + 1) && v(i, j3) === v(i, j3 + 2)) { bad[i * N + j3] = bad[i * N + j3 + 1] = bad[i * N + j3 + 2] = 1; }
          if (v(j3, i) >= 0 && v(j3, i) === v(j3 + 1, i) && v(j3, i) === v(j3 + 2, i)) { bad[j3 * N + i] = bad[(j3 + 1) * N + i] = bad[(j3 + 2) * N + i] = 1; }
        }
      }
      st.edges.forEach(function (e) {
        var a = e[0] * N + e[1], b = e[2] === "r" ? a + 1 : a + N;
        if (vals[a] >= 0 && vals[b] >= 0 && ((vals[a] === vals[b]) !== (e[3] === "="))) { bad[a] = bad[b] = 1; }
      });
      return bad;
    }
    function draw(checked) {
      var bad = errors();
      for (var y = 0; y < N; y++) for (var x = 0; x < N; x++) {
        var k = y * N + x, c = g.cells[y][x];
        c.innerHTML = vals[k] === 0 ? SUN : vals[k] === 1 ? MOON : "";
        c.classList.toggle("pz-clash", !!bad[k]);
        c.classList.toggle("pz-bad", !!checked && vals[k] >= 0 && vals[k] !== sol[y][x]);
        c.setAttribute("aria-label", lab(y, x));
      }
    }
    function solved() { for (var k = 0; k < N * N; k++) if (vals[k] !== sol[Math.floor(k / N)][k % N]) return false; return true; }
    function changed() {
      draw(false);
      ctx.store({ vals: vals, done: ctx.done });
      if (!ctx.done && solved()) ctx.finish("solved");
    }
    ctx.tools({
      check: function () {
        draw(true);
        var wrong = 0, empty = 0;
        for (var k = 0; k < N * N; k++) { if (vals[k] < 0) empty++; else if (vals[k] !== sol[Math.floor(k / N)][k % N]) wrong++; }
        if (solved()) ctx.finish("solved");
        else ctx.say(wrong ? wrong + (wrong === 1 ? " cell is" : " cells are") + " wrong." : "No mistakes so far. " + empty + " to go.", wrong ? "warn" : "");
      },
      hint: function () {
        var pick = -1;
        for (var k = 0; k < N * N; k++) if (vals[k] >= 0 && vals[k] !== sol[Math.floor(k / N)][k % N]) { pick = k; break; }
        if (pick < 0) for (var k2 = 0; k2 < N * N; k2++) if (vals[k2] < 0) { pick = k2; break; }
        if (pick < 0) return;
        vals[pick] = sol[Math.floor(pick / N)][pick % N];
        ctx.say("Row " + (Math.floor(pick / N) + 1) + ", column " + (pick % N + 1) + " filled in.");
        changed();
      },
      reveal: function () { for (var k = 0; k < N * N; k++) vals[k] = sol[Math.floor(k / N)][k % N]; ctx.finish("revealed"); changed(); },
      clear: function () { for (var k = 0; k < N * N; k++) vals[k] = given[k] != null ? given[k] : -1; ctx.done = false; draw(false); }
    });
    var s = ctx.saved();
    if (s && s.vals && s.vals.length === N * N) {
      for (var k2 = 0; k2 < N * N; k2++) if (given[k2] == null) vals[k2] = s.vals[k2] === 0 || s.vals[k2] === 1 ? s.vals[k2] : -1;
      if (s.done === "revealed") ctx.finish("revealed");
      else if (solved()) ctx.finish("solved");
    }
    draw(false);
  }

  // ---------- the weekly (a bigger freeform crossword that lasts friday to thursday) ----------
  function weekly(root, st) {
    var ctx = shell(root, st), R = st.rows, C = st.cols, mask = st.mask, rows = ctx.sol;
    var words = [], nums = {}, helped = {}, scope = "word";
    ["across", "down"].forEach(function (d) {
      st[d].forEach(function (e) {
        words.push({ dir: d === "across" ? "a" : "d", cells: e.cells, num: e.num, clue: e.clue, d: d, len: e.len });
        nums[e.cells[0][0] + "," + e.cells[0][1]] = e.num;
      });
    });
    function lab(wi) { var w = words[wi]; return w.num + (w.d === "across" ? " Across" : " Down"); }
    var bar = h("p", { class: "pz-cluebar pz-wk-bar", "aria-live": "polite" });
    var clueBtns = [];
    var lists = h("div", { class: "pz-cluecols pz-wk-clues" });
    var g = letterGrid({
      rows: R, cols: C, label: "Weekly crossword grid, " + C + " by " + R, words: words, downWords: true,
      white: function (y, x) { return mask[y][x] === "."; },
      num: function (y, x) { return nums[y + "," + x]; },
      cellLabel: function (y, x) {
        var parts = [];
        words.forEach(function (w, i) {
          w.cells.forEach(function (c, j) { if (c[0] === y && c[1] === x) parts.push(lab(i) + " letter " + (j + 1) + " of " + w.len); });
        });
        return parts.join(", ");
      },
      onChange: changed,
      onWord: function (wi) {
        bar.textContent = "";
        bar.appendChild(h("b", { text: lab(wi).replace(" Across", "A").replace(" Down", "D") }));
        bar.appendChild(document.createTextNode(" " + words[wi].clue + " (" + words[wi].len + ")"));
        clueBtns.forEach(function (b, i) { b.classList.toggle("pz-on", i === wi); });
        // keep the clue in view when the list scrolls on its own (wide screens); never move the page
        var b = clueBtns[wi], box = b && b.closest(".pz-clues");
        if (box && box.scrollHeight > box.clientHeight + 2) {
          var top = b.offsetTop - box.offsetTop;
          if (top < box.scrollTop || top + b.offsetHeight > box.scrollTop + box.clientHeight) box.scrollTop = top - box.clientHeight / 3;
        }
      }
    });
    g.board.classList.add("pz-wk-board");
    ["across", "down"].forEach(function (d) {
      var ol = h("ol");
      words.forEach(function (w, i) {
        if (w.d !== d) return;
        var b = h("button", { type: "button", class: "pz-clue", "aria-label": lab(i) + ", " + w.len + " letters: " + w.clue },
          [h("b", { text: String(w.num) }), " " + w.clue + " ", h("span", { class: "pz-enum", text: "(" + w.len + ")" })]);
        b.addEventListener("click", function () { g.focusWord(i); });
        clueBtns[i] = b;
        ol.appendChild(h("li", {}, [b]));
      });
      lists.appendChild(h("div", { class: "pz-clues" }, [h("h4", { text: d === "across" ? "Across" : "Down" }), ol]));
    });
    var scopes = h("div", { class: "pz-scope", role: "group", "aria-label": "Check and reveal applies to" });
    [["square", "Square"], ["word", "Word"], ["grid", "Grid"]].forEach(function (s) {
      var b = h("button", { type: "button", class: "pz-seg", "data-scope": s[0], "aria-pressed": s[0] === scope ? "true" : "false", text: s[1] });
      b.addEventListener("click", function () {
        scope = s[0];
        scopes.querySelectorAll(".pz-seg").forEach(function (x) { x.setAttribute("aria-pressed", x === b ? "true" : "false"); });
      });
      scopes.appendChild(b);
    });
    var main = h("div", { class: "pz-xw-main" }, [bar, g.board,
      h("div", { class: "pz-scopebar" }, [h("span", { class: "pz-scope-label", text: "Check and reveal:" }), scopes])]);
    root.appendChild(h("div", { class: "pz-xw pz-wk" }, [main, lists]));
    bar.textContent = "Tap a square to start. Tap it again to switch direction.";

    function whites(fn) { for (var y = 0; y < R; y++) for (var x = 0; x < C; x++) if (mask[y][x] === ".") fn(y, x); }
    function solved() { var ok = true; whites(function (y, x) { if (g.get(y, x) !== rows[y][x]) ok = false; }); return ok; }
    function target() {
      var c = g.cur(), wi = g.word(), out = [];
      if (scope === "square") return c ? [c] : [];
      if (scope === "word") return wi != null ? words[wi].cells : [];
      whites(function (y, x) { out.push([y, x]); });
      return out;
    }
    function changed() {
      var v = [], hp = [], i = 0;
      whites(function (y, x) { v.push(g.get(y, x) || "."); if (helped[y + "," + x]) hp.push(i); i++; });
      words.forEach(function (w, wi) {
        clueBtns[wi].classList.toggle("pz-filled", w.cells.every(function (c) { return !!g.get(c[0], c[1]); }));
      });
      ctx.store({ cells: v.join(""), helped: hp, done: ctx.done });
      if (!ctx.done && solved()) ctx.finish("solved", "Solved! A new grid comes out on Friday.");
    }
    function show(y, x) {
      g.set(y, x, rows[y][x]);
      helped[y + "," + x] = 1;
      g.mark(y, x, "pz-hinted", true);
    }
    var where = { square: "this square", word: "this word", grid: "the grid" };
    ctx.tools({
      check: function () {
        var cs = target(), bad = 0, empty = 0;
        if (!cs.length) { ctx.say("Tap a square first."); return; }
        cs.forEach(function (c) {
          var v = g.get(c[0], c[1]);
          if (!v) empty++;
          else if (v !== rows[c[0]][c[1]]) { bad++; g.mark(c[0], c[1], "pz-bad", true); }
        });
        if (solved()) ctx.finish("solved", "Solved! A new grid comes out on Friday.");
        else ctx.say(bad ? bad + (bad === 1 ? " square is" : " squares are") + " wrong in " + where[scope] + "." :
          (empty ? "No mistakes in " + where[scope] + ". " + empty + " to fill." : "All correct in " + where[scope] + "."), bad ? "warn" : "");
      },
      hint: function () {
        var c = g.cur(), wi = g.word(), t = null;
        function wrong(y, x) { return g.get(y, x) !== rows[y][x]; }
        if (c && wrong(c[0], c[1])) t = c;
        if (!t && wi != null) words[wi].cells.forEach(function (cc) { if (!t && wrong(cc[0], cc[1])) t = cc; });
        if (!t) whites(function (y, x) { if (!t && wrong(y, x)) t = [y, x]; });
        if (!t) { ctx.say("Nothing left to hint."); return; }
        show(t[0], t[1]);
        ctx.say("One square filled in.");
        changed();
      },
      reveal: function () {
        var cs = target();
        if (!cs.length) { ctx.say("Tap a square first."); return; }
        cs.forEach(function (c) { if (g.get(c[0], c[1]) !== rows[c[0]][c[1]]) show(c[0], c[1]); });
        if (scope === "grid") ctx.finish("revealed", "Grid revealed. A new one comes out on Friday.");
        else ctx.say(scope === "word" ? "Word revealed." : "Square revealed.");
        changed();
      },
      clear: function () {
        helped = {};
        whites(function (y, x) { g.set(y, x, ""); g.mark(y, x, "pz-hinted", false); });
        ctx.done = false;
        changed();
      }
    });
    // buttons and status sit under the grid, before the long clue list on a phone
    main.appendChild(root.querySelector(":scope > .pz-tools"));
    main.appendChild(root.querySelector(":scope > .pz-status"));
    var s = ctx.saved();
    if (s && typeof s.cells === "string") {
      var i = 0, hp = {};
      (s.helped || []).forEach(function (k) { hp[k] = 1; });
      whites(function (y, x) {
        var ch = s.cells[i];
        g.set(y, x, ch && ch !== "." ? ch : "");
        if (hp[i]) { helped[y + "," + x] = 1; g.mark(y, x, "pz-hinted", true); }
        i++;
      });
      if (s.done === "revealed") ctx.finish("revealed", "Grid revealed. A new one comes out on Friday.");
      else if (solved()) ctx.finish("solved", "Solved! A new grid comes out on Friday.");
      words.forEach(function (w, wi) {
        clueBtns[wi].classList.toggle("pz-filled", w.cells.every(function (c) { return !!g.get(c[0], c[1]); }));
      });
    }
  }

  // ---------- game picker: on a phone the brief shows one game at a time ----------
  function picker(box) {
    var bar = box.querySelector(".pz-picker"), panels = box.querySelectorAll(".puzzle[data-game]");
    if (!bar || !panels.length) return;
    var key = "brief:game", btns = bar.querySelectorAll("[data-game]");
    function pick(game, save) {
      var found = false;
      panels.forEach(function (p) { var on = p.getAttribute("data-game") === game; p.classList.toggle("pz-shown", on); found = found || on; });
      if (!found) return false;
      btns.forEach(function (b) {
        var on = b.getAttribute("data-game") === game;
        b.setAttribute("aria-pressed", on ? "true" : "false");
        if (on && (b.offsetLeft < bar.scrollLeft || b.offsetLeft + b.offsetWidth > bar.scrollLeft + bar.clientWidth)) bar.scrollLeft = b.offsetLeft - 20;
      });
      if (save) try { window.localStorage.setItem(key, game); } catch (e) { /* fine */ }
      return true;
    }
    function marks() {
      btns.forEach(function (b) {
        var p = box.querySelector('.puzzle[data-game="' + b.getAttribute("data-game") + '"] .pz');
        b.classList.toggle("pz-pick-done", !!p && (p.classList.contains("pz-solved") || p.classList.contains("pz-revealed")));
      });
    }
    btns.forEach(function (b) {
      b.addEventListener("click", function () {
        pick(b.getAttribute("data-game"), true);
        var top = box.getBoundingClientRect().top;
        if (top < 0) box.scrollIntoView({ block: "start" });
      });
    });
    var last = null;
    try { last = window.localStorage.getItem(key); } catch (e) { /* fine */ }
    if (!last || !pick(last, false)) pick(panels[0].getAttribute("data-game"), false);
    box.classList.add("pz-tabbed");
    marks();
    if (window.MutationObserver) {
      new MutationObserver(marks).observe(box, { subtree: true, attributes: true, attributeFilter: ["class"] });
    }
  }

  var KINDS = { ladder: ladder, crossword: crossword, word: word, crowns: crowns, sunmoon: sunmoon, weekly: weekly };
  function hydrate(root) {
    if (root.getAttribute("data-ready")) return;
    try {
      var st = JSON.parse(root.querySelector("script.pz-state").textContent);
      if (!KINDS[st.kind]) return;
      KINDS[st.kind](root, st);
      root.setAttribute("data-ready", "1");
      (root.closest(".pz") || root).classList.add("pz-live");
    } catch (e) {
      // leave the print block showing; it is a complete puzzle on its own
      if (window.console) console.error("puzzle failed to start", e);
    }
  }
  function start() {
    document.querySelectorAll(".pz-play").forEach(hydrate);
    document.querySelectorAll(".pz-games").forEach(picker);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
