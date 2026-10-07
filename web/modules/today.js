// today: the masthead line, now (sky, now line, next), the one thing, ranked to-dos, the day in numbers,
// the day (ribbon and timeline), the brief and tomorrow. one tile each, all in the today room
(function () {
  'use strict';
  var ZB = window.Board, h = ZB.h, I = ZB.icon;
  var KIND = { school: 'school', ta: 'TA', research: 'research', project: 'project', pr: 'PR', email: 'email', task: 'Todoist',
    personal: 'personal' };
  var EV_KIND = { ta: 'TA', 'class': 'class', meeting: 'meeting', personal: 'personal', deadline: 'deadline' };
  var CODE = /^([A-Z]{2,5}[- ]?\d{3,4})\s+/;
  var NUM = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine'];
  var data = null, showMarked = false, showTimeline = false;

  function hides(id, server) {
    var p = ZB.pending[id];
    return p ? p !== 'open' : server;
  }
  function day(d) { return new Date(d + 'T12:00:00'); }
  function fmt(d, o) { return day(d).toLocaleDateString('en-US', o); }
  function plus1(d) { var x = day(d); x.setDate(x.getDate() + 1); return x.toISOString().slice(0, 10); }
  function cap(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1) : s; }
  // "CS-1300 Office Hours (Room 2)" reads as "Office Hours"; the class code goes in the meta line
  function bare(t) { return String(t || '').replace(CODE, '').replace(/\s*\([^)]*\)\s*$/, '').trim() || t; }
  function code(t) { var m = CODE.exec(t || ''); return m ? m[1].toUpperCase() : ''; }
  function acronym(t) {
    var w = bare(t).split(/\s+/).filter(function (x) { return x && !/^(of|and|the|for|to|in|a)$/i.test(x); });
    return w.length > 1 ? w.map(function (x) { return x.charAt(0).toUpperCase(); }).join('') : bare(t);
  }

  function clockNow() { return ZB.local(); }
  function isToday(d) { return !d.stale && clockNow().date === d.date; }
  function timed(d) {
    return d.events.filter(function (e) { return !e.all_day; }).map(function (e) {
      return { e: e, s: ZB.hm(e.start), f: ZB.hm(e.end) };
    }).sort(function (a, b) { return a.s - b.s || a.f - b.f; });
  }
  function bounds(d) {
    var rb = d.ribbon, ev = timed(d);
    var lo = rb ? rb.lo : 480, hi = rb ? rb.hi : 1260;
    var first = Math.min.apply(null, [Infinity].concat(d.free.map(function (f) { return ZB.hm(f.start); }),
      ev.map(function (x) { return x.s; })));
    return { lo: lo, hi: hi, start: isFinite(first) ? first : lo };
  }

  // ---------- the masthead line and the brief link ----------

  function briefUrl(d) {
    return ZB.safeUrl(d.brief_url) || (/^http:\/\/[\d.]+(:\d+)?\//.test(d.brief_url || '') ? d.brief_url : '');
  }
  function briefLabel(d) {
    if (isToday(d)) return 'Read today\u2019s brief';
    return 'Brief for ' + fmt(d.date, { weekday: 'short', month: 'short', day: 'numeric' }).replace(',', '');
  }
  function weatherIcon(line) {
    var l = String(line).toLowerCase();
    return /rain|shower|storm|drizzle|thunder/.test(l) ? 'rain' : /cloud|overcast|fog|haze/.test(l) ? 'cloud' : 'sun';
  }

  function almanac(d) {
    var el = document.getElementById('almanac');
    if (!el) return;
    var today = ZB.local().date;
    el.textContent = '';
    var dot = function () { return h('span', { class: 'dot', 'aria-hidden': 'true', text: '·' }); };
    // the date on the masthead is today's in the configured zone, whatever brief is on disk
    var td = today || d.date;
    el.appendChild(h('time', { datetime: td }, [
      h('span', { class: 'd-short', text: fmt(td, { weekday: 'short', month: 'short', day: 'numeric' }) }),
      h('span', { class: 'd-long', text: fmt(td, { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' }) })]));
    if (ZB.cfg.location) {
      el.appendChild(dot());
      el.appendChild(h('span', { text: ZB.cfg.location }));
    }
    if (d.weather_line && !d.stale) {
      el.appendChild(dot());
      el.appendChild(h('span', { class: 'wx' }, [I(weatherIcon(d.weather_line), 'wx-ic'), d.weather_line]));
    }
    ['Sunrise ' + d.sunrise, 'Sunset ' + d.sunset].forEach(function (t) {
      el.appendChild(h('span', { class: 'wide-only dot', 'aria-hidden': 'true', text: '·' }));
      el.appendChild(h('span', { class: 'wide-only mono', text: t }));
    });
    var link = document.getElementById('brief-link'), url = briefUrl(d);
    link.hidden = !url;
    if (url) {
      link.setAttribute('href', url);
      link.textContent = '';
      link.appendChild(document.createTextNode(briefLabel(d)));
      link.appendChild(I('arrow'));
    }
  }

  // ---------- the mini sky ----------

  // a small seeded random, so a date always draws the same hills
  function rng(seed) {
    var a = 0;
    for (var i = 0; i < seed.length; i++) a = (a * 31 + seed.charCodeAt(i)) | 0;
    return function () {
      a = (a + 0x6D2B79F5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function dotPath(cx, cy, r) {
    return 'M' + (cx - r).toFixed(2) + ',' + cy.toFixed(2) + ' a' + r.toFixed(2) + ',' + r.toFixed(2) + ' 0 1,0 ' +
      (2 * r).toFixed(2) + ',0 a' + r.toFixed(2) + ',' + r.toFixed(2) + ' 0 1,0 ' + (-2 * r).toFixed(2) + ',0 Z ';
  }

  function sky(d, n, today) {
    var S = ZB.s, W = 512, H = 220, R = rng(d.date);
    var rise = ZB.hm(d.sun && d.sun.rise) || 442, set = ZB.hm(d.sun && d.sun.set) || 1142;
    var night = n < rise || n > set;
    var hor = H * 0.6;
    var xOf = function (m) { return (m - 360) / 960 * W; };
    var arcY = function (m) { return hor - Math.sin(Math.PI * (m - rise) / (set - rise)) * (hor - H * 0.13); };
    var kids = [S('rect', { width: W, height: H, class: 'top' })];
    // five sky bands
    for (var i = 1; i <= 5; i++) {
      var y0 = hor * 1.04 * Math.pow(i / 6, 0.85), amp = H * (0.01 + 0.007 * (i % 3)), ph = i * 1.9 + R() * 2, f = 1.3 + (i % 3) * 0.6;
      var p = '';
      for (var j = 0; j <= 24; j++) p += (j ? ' L' : 'M') + (j * W / 24).toFixed(1) + ',' + (y0 + amp * Math.sin(ph + f * j / 24 * 6.283)).toFixed(1);
      kids.push(S('path', { d: p + ' L' + W + ',' + H + ' L0,' + H + ' Z', class: 'b' + i }));
    }
    var ev = today ? timed(d) : [];
    // three ridges; the near one swells at each event
    var N = 72, ridges = [];
    for (i = 0; i < 3; i++) {
      var base = hor + (H - hor) * (i * 0.27 - 0.06), am = H * 0.11 * (1 - i * 0.22), ph2 = 0.7 + i * 2.1 + R() * 3,
        f1 = 1.1 + i * 0.45, f2 = 4 + i;
      var ys = [];
      for (j = 0; j <= N; j++) {
        var x = j * W / N, u = j / N * 6.283;
        var y = base - am * (0.6 * Math.sin(ph2 + f1 * u) + 0.25 * Math.sin(ph2 * 1.7 + f2 * u) + 0.06 * Math.sin(f2 * 3.1 * u));
        if (i === 2) {
          var lifts = ev.map(function (q) {
            var cx = xOf((q.s + q.f) / 2), w = Math.max(W * 0.05, xOf(q.f) - xOf(q.s));
            return (H * 0.05 + (q.f - q.s) * H * 0.0011) * Math.exp(-Math.pow((x - cx) / (w * 0.85), 2));
          });
          var mx = Math.max.apply(null, [0].concat(lifts)), sm = lifts.reduce(function (a, b) { return a + b; }, 0);
          y = base + am * (0.3 + 0.2 * Math.sin(ph2 + f1 * u)) - Math.min(H * 0.22, mx + 0.22 * (sm - mx));
        }
        ys.push(y);
      }
      ridges.push(ys);
    }
    var ry = function (k, x) {
      var fx = x / W * N, jj = Math.min(N - 1, Math.max(0, Math.floor(fx))), t = fx - jj;
      return ridges[k][jj] * (1 - t) + ridges[k][jj + 1] * t;
    };
    var sr = H * 0.065;
    if (night) {
      // stars and the moon instead of the sun
      var stars = '';
      for (i = 0; i < 34; i++) stars += dotPath(R() * W, R() * hor * 0.85, 0.5 + R() * 1.1);
      kids.push(S('path', { d: stars, class: 'star' }));
      var mxm = Math.min(W * 0.9, Math.max(W * 0.1, xOf(n)));
      var my = H * 0.24;
      kids.push(S('circle', { cx: mxm.toFixed(1), cy: my.toFixed(1), r: (sr * 2.2).toFixed(1), class: 'glow', opacity: '0.12' }));
      // a crescent: the moon's disc with an offset disc masked out
      kids.push(S('mask', { id: 'db-moon' }, [S('rect', { width: W, height: H, fill: '#fff' }),
        S('circle', { cx: (mxm + sr * 0.42).toFixed(1), cy: (my - sr * 0.22).toFixed(1), r: (sr * 0.78).toFixed(1), fill: '#000' })]));
      kids.push(S('circle', { cx: mxm.toFixed(1), cy: my.toFixed(1), r: (sr * 0.9).toFixed(1), class: 'moon', mask: 'url(#db-moon)' }));
    } else {
      var arc = '';
      for (var m = rise; m <= set; m += 8) arc += (arc ? ' L' : 'M') + xOf(m).toFixed(1) + ',' + arcY(m).toFixed(1);
      kids.push(S('path', { d: arc, class: 'arc' }));
      var sx = xOf(n), sy = Math.min(arcY(n), ry(0, sx) - sr);
      var ringd = function (k) {
        var rr = sr + k * sr * 0.48, c = Math.round(2 * Math.PI * rr / (sr * 0.36)), out = '';
        for (var a = 0; a < c; a++) out += dotPath(sx + rr * Math.cos(a * 2 * Math.PI / c), sy + rr * Math.sin(a * 2 * Math.PI / c),
          Math.max(0.35, sr * 0.075 * (1 - k / 7)));
        return out;
      };
      kids.push(S('circle', { cx: sx.toFixed(1), cy: sy.toFixed(1), r: (sr * 3.2).toFixed(1), class: 'glow', opacity: '0.12' }));
      kids.push(S('circle', { cx: sx.toFixed(1), cy: sy.toFixed(1), r: (sr * 2).toFixed(1), class: 'glow', opacity: '0.2' }));
      kids.push(S('path', { d: ringd(1) + ringd(2), class: 'glow', opacity: '0.7' }));
      kids.push(S('path', { d: ringd(3) + ringd(4) + ringd(5), class: 'glow', opacity: '0.35' }));
      kids.push(S('circle', { cx: sx.toFixed(1), cy: sy.toFixed(1), r: sr.toFixed(1), class: 'sun' }));
    }
    for (i = 0; i < 3; i++) {
      kids.push(S('path', { class: 'h' + (i + 1), d: 'M0,' + H + ' L' + ridges[i].map(function (yy, jj) {
        return (jj * W / N).toFixed(1) + ',' + yy.toFixed(1);
      }).join(' L') + ' L' + W + ',' + H + ' Z' }));
    }
    // lamps: past ones dim, the next one glows
    var past = '', later = '', next = null;
    ev.forEach(function (q, k) {
      var cx = xOf((q.s + q.f) / 2) + (k && ev[k - 1].s === q.s ? 5 : 0), cy = ry(2, cx) + 7;
      if (q.f <= n) past += dotPath(cx, cy, 2.6);
      else if (!next) next = [cx, cy];
      else later += dotPath(cx, cy, 2.6);
    });
    if (past) kids.push(S('path', { d: past, class: 'lamp', opacity: '0.4' }));
    if (later) kids.push(S('path', { d: later, class: 'lamp', opacity: '0.85' }));
    if (next) {
      kids.push(S('circle', { cx: next[0].toFixed(1), cy: next[1].toFixed(1), r: '10', class: 'lamp', opacity: '0.22' }));
      kids.push(S('circle', { cx: next[0].toFixed(1), cy: next[1].toFixed(1), r: '3.6', class: 'lamp' }));
    }
    // hour ticks along the bottom: labels at 9, 12, 3, 6, 9
    var tp = '';
    for (m = 420; m <= 1320; m += 60) tp += 'M' + xOf(m).toFixed(1) + ',' + (H - 20) + ' v' + (m % 180 ? -3 : -6) + ' ';
    kids.push(S('path', { d: tp, class: 'tick' }));
    [540, 720, 900, 1080, 1260].forEach(function (mm) {
      kids.push(S('text', { x: xOf(mm).toFixed(1), y: H - 6, class: 'tick-l', 'text-anchor': 'middle' }, [String((mm / 60) % 12 || 12)]));
    });
    var upcoming = ev.filter(function (q) { return q.s > n; })[0];
    var label = (night ? 'The night sky: moon at ' : 'The day\u2019s sky: sun at ') + ZB.label(n) + ', ' + ev.length + ' event' +
      (ev.length === 1 ? '' : 's') + (upcoming ? ', next at ' + ZB.label(upcoming.s) : ev.length ? ', none left' : '');
    return S('svg', { viewBox: '0 0 ' + W + ' ' + H, class: 'sky' + (night ? ' night' : ''), role: 'img', 'aria-label': label,
      preserveAspectRatio: 'xMidYMid slice' }, kids);
  }

  // ---------- now ----------

  // where the day stands: in an event, in an open stretch, before the day or after it
  function where(d) {
    var t = clockNow(), n = t.minutes, b = bounds(d), ev = timed(d);
    if (!isToday(d)) {
      return { stale: true, line: 'From the ' + fmt(d.date, { weekday: 'short', month: 'short', day: 'numeric' }) + ' brief.',
        sub: 'Today\u2019s is not out yet.' };
    }
    var inside = ev.filter(function (x) { return x.s <= n && n < x.f; }).sort(function (a, c) { return c.s - a.s; })[0];
    var next = ev.filter(function (x) { return x.s > n; })[0];
    if (inside) return { line: 'In ' + bare(inside.e.title), sub: 'until ' + inside.e.end_label, a: inside.s, b: inside.f, next: next };
    if (n < b.start) return { line: 'Day starts at ' + ZB.label(b.start), next: next };
    if (n >= b.hi) return { line: 'Evening. Nothing left today.' };
    var prev = Math.max.apply(null, [b.start].concat(ev.filter(function (x) { return x.f <= n; }).map(function (x) { return x.f; })));
    if (!next) return { line: 'Open until ' + ZB.label(b.hi), a: prev, b: b.hi };
    return { line: 'Open until ' + ZB.label(next.s), a: prev, b: next.s, next: next };
  }

  function nowTile(d) {
    var t = clockNow(), today = isToday(d), w = where(d);
    var sec = ZB.tile('now', 'Now', { room: 'today', aside: h('span', { class: 'mono',
      text: (ZB.cfg.location ? ZB.cfg.location + ', ' : '') + ZB.label(t.minutes) }) });
    sec.appendChild(h('div', { class: 'sky-wrap' }, sky(d, t.minutes, today)));
    sec.appendChild(h('div', { class: 'sun-row mono' }, [h('span', { text: 'Sunrise ' + d.sunrise }), h('span', { text: 'Sunset ' + d.sunset })]));
    var main = h('div', { class: 'now-main' }, [h('p', { class: 'now-line' + (w.stale || w.line.length > 22 ? ' small' : ''), text: w.line }),
      w.sub ? h('p', { class: 'now-sub', text: w.sub }) : null]);
    if (w.a !== undefined) {
      var fill = h('span', { class: 'bar-fill' });
      fill.style.width = Math.min(100, Math.max(0, (t.minutes - w.a) / Math.max(1, w.b - w.a) * 100)).toFixed(1) + '%';
      main.appendChild(h('div', { class: 'bar', role: 'img', 'aria-label': ZB.dur(w.b - t.minutes) + ' left of this stretch' }, fill));
      main.appendChild(h('div', { class: 'bar-labels mono', 'aria-hidden': 'true' }, [h('span', { text: ZB.label(w.a) }),
        h('span', { text: ZB.dur(w.b - t.minutes) + ' left' }), h('span', { text: ZB.label(w.b) })]));
    }
    var card = null;
    if (w.next) {
      var e = w.next.e, c = code(e.title);
      card = h('div', { class: 'next k-' + (e.kind || 'other') }, [h('span', { class: 'next-bar', 'aria-hidden': 'true' }), h('div', {}, [
        h('p', { class: 'next-when', text: 'Next, in ' + ZB.dur(w.next.s - t.minutes) }),
        h('p', { class: 'next-title', text: bare(e.title) }),
        h('p', { class: 'next-meta' }, [h('span', { class: 'mono', text: e.start_label + ' to ' + e.end_label }),
          [c, EV_KIND[e.kind]].filter(Boolean).map(function (x) { return ' · ' + x; }).join('')])])]);
    } else if (today && !w.stale && w.a !== undefined) {
      card = h('div', { class: 'next quiet-card' }, h('p', { text: 'Nothing else on the calendar today.' }));
    }
    sec.appendChild(h('div', { class: 'now-body' }, [main, card]));
    return sec;
  }

  // ---------- the one thing ----------

  function title(item) {
    var url = ZB.safeUrl(item.url);
    return url ? h('a', { href: url, target: '_blank', rel: 'noopener noreferrer', text: item.title }) : item.title;
  }

  function handBtn(item, label, cls) {
    return h('button', { type: 'button', class: 'btn ' + (cls || 'soft ag'), 'data-key': 'ag:' + item.id + (label ? ':f' : ''),
      'aria-label': 'Hand to ' + ZB.agent() + ': ' + item.title, 'aria-haspopup': 'dialog',
      onclick: function () { ZB.openPanel(item, data.where_choices); } }, [I('spark'), label || ZB.agent()]);
  }

  function longestLeft(d) {
    var n = isToday(d) ? clockNow().minutes : -1, best = null;
    d.free.forEach(function (f) {
      var s = Math.max(ZB.hm(f.start), n), e = ZB.hm(f.end);
      if (e - s > 0 && (!best || e - s > best[1] - best[0])) best = [s, e];
    });
    return best;
  }
  function span(a, b) {
    var l = ZB.label(a), r = ZB.label(b);
    if (l.slice(-2) === r.slice(-2)) l = l.slice(0, -3);
    return l + ' to ' + r;
  }

  function sessionFor(f) {
    var ag = ZB.state.modules.agent, pre = String(ZB.cfg.prefix || 'hd-').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    var m = new RegExp('(?:^|[^a-z0-9-])(' + pre + '[a-z0-9-]+)').exec((f.source || '') + ' ' + (f.ref || ''));
    if (!m || !ag || ag.error) return null;
    var pick = function (list, kind) {
      var s = (list || []).filter(function (x) { return x.name === m[1]; })[0];
      return s ? { s: s, kind: kind } : null;
    };
    return pick(ag.waiting, 'waiting') || pick(ag.running, 'running') || pick(ag.finished, 'finished');
  }

  function focusTile(d, f, done) {
    var sec = ZB.tile('focus', 'The one thing', { room: 'today', accent: true });
    if (!f) {
      sec.classList.add('is-empty');
      sec.appendChild(h('p', { class: 'f-title calm', text: done ? 'The one thing is done.' : 'No one thing today.' }));
      sec.appendChild(h('p', { class: 'f-why', text: done ? 'Pick the next to-do when you are ready.' :
        'The brief did not pick a focus. The list below is ranked.' }));
      return sec;
    }
    sec.appendChild(h('h3', { class: 'f-title' }, title(f)));
    if (f.why) sec.appendChild(h('p', { class: 'f-why', text: f.why }));
    if (f.when) sec.appendChild(h('p', { class: 'f-when' }, [I('clock'), f.when]));
    var w = f.window, t = clockNow();
    if (w && isToday(d) && t.minutes >= ZB.hm(w.end)) {
      var lb = longestLeft(d);
      sec.appendChild(h('p', { class: 'f-passed' }, ['That window has passed.'].concat(lb && lb[1] - lb[0] >= 60 ?
        [' The next long open block is ', h('span', { class: 'mono', text: span(lb[0], lb[1]) }), '.'] : [])));
    }
    var ss = sessionFor(f);
    if (ss) {
      var s = ss.s;
      sec.appendChild(h('div', { class: 'f-sess' }, [h('div', { class: 'f-sess-top' }, [
        h('span', { class: 'sdot ' + ss.kind, 'aria-hidden': 'true' }), h('span', { class: 'mono strong', text: s.name }),
        h('span', { class: 'f-sess-st', text: ss.kind === 'running' ? 'running, waits on this' : ss.kind === 'waiting' ?
          'waiting on you' : 'finished' })]),
      s.report && s.report.length ? h('p', { class: 'clamp2', text: s.report.join(' ') }) : null]));
    } else if (f.source) {
      sec.appendChild(h('p', { class: 'f-src' }, [h('span', { class: 'sdot good', 'aria-hidden': 'true' }), f.source]));
    }
    var mark = h('button', { type: 'button', class: 'btn', 'data-key': 'tick:' + f.id, 'aria-label': 'Mark done: ' + f.title,
      onclick: function () { sec.classList.add('is-done'); setTimeout(function () { ZB.mark(f, 'done'); }, 280); } },
    [I('check'), 'Mark done']);
    sec.appendChild(h('div', { class: 'f-acts' }, [handBtn(f, 'Hand to ' + ZB.agent(), 'primary'), mark]));
    return sec;
  }

  // ---------- to do ----------

  function tick(item, n, row) {
    return h('button', { type: 'button', class: 'tick', 'data-key': 'tick:' + item.id, 'aria-label': 'Mark done: ' + item.title,
      onclick: function () {
        row.classList.add('is-done');
        setTimeout(function () { ZB.mark(item, 'done'); }, 280);
      } }, h('span', { class: 'box', 'aria-hidden': 'true' }, [n ? h('span', { class: 'num', text: String(n) }) : null,
      I('check', 'ck')]));
  }

  function holdsNow(item, d) {
    var w = item.window;
    if (!w || !isToday(d)) return false;
    var n = clockNow().minutes;
    return ZB.hm(w.start) <= n && n < ZB.hm(w.end);
  }

  function actRow(item, n, d) {
    var li = h('li', { class: 'act' });
    var kind = KIND[item.kind] || '';
    var meta = [item.overdue ? null : item.when, kind && kind.toLowerCase() !== String(item.source).toLowerCase() ? kind : '',
      item.source].filter(Boolean);
    li.appendChild(tick(item, n, li));
    li.appendChild(h('div', { class: 'act-main' }, [h('p', { class: 'act-title' }, title(item)),
      item.why ? h('p', { class: 'act-why', text: item.why }) : null]));
    li.appendChild(h('p', { class: 'act-meta' }, [holdsNow(item, d) ? h('span', { class: 'now-chip', text: 'Now' }) : null,
      h('span', {}, [item.overdue ? h('b', { class: 'late', text: item.when }) : null,
        (item.overdue && meta.length ? ' · ' : '') + meta.join(' · ')])]));
    li.appendChild(handBtn(item));
    return li;
  }

  function markedFoot(list) {
    var done = list.filter(function (i) { return (ZB.pending[i.id] || (i.mark && i.mark.state)) === 'done'; }).length;
    var other = list.length - done;
    var label = done + ' done today' + (other ? ', ' + other + ' snoozed or dismissed' : '');
    if (!list.length) {
      return h('div', { class: 'marked' }, h('div', { class: 'marked-row' }, h('p', { class: 'muted' }, [label,
        h('span', { class: 'wide-only', text: '. Ticked items land here, with Undo.' })])));
    }
    var ul = h('ul', { class: 'marked-list', id: 'marked-list', hidden: !showMarked });
    list.forEach(function (i) {
      var st = ZB.pending[i.id] || (i.mark && i.mark.state) || '';
      ul.appendChild(h('li', {}, [h('span', { class: 't', text: i.title }), h('span', { class: 'st', text: st }),
        h('button', { type: 'button', class: 'btn text', 'data-key': 'undo:' + i.id, 'aria-label': 'Undo: ' + i.title, text: 'Undo',
          onclick: function () { ZB.mark(i, 'open'); } })]));
    });
    return h('div', { class: 'marked' }, [h('div', { class: 'marked-row' }, [h('p', { class: 'muted', text: label }),
      h('button', { type: 'button', class: 'btn text fold' + (showMarked ? ' open' : ''), 'aria-expanded': showMarked ? 'true' : 'false',
        'aria-controls': 'marked-list', 'data-key': 'marked-toggle', onclick: function () { showMarked = !showMarked; ZB.redraw(); } },
      [showMarked ? 'Hide' : 'Show', I('chev')])]), ul]);
  }

  function todoTile(d, items, marked) {
    var sec = ZB.tile('todo', 'To do', { room: 'today', aside: items.length ? items.length + ' open, ranked' : '' });
    if (items.length) {
      var ol = h('ol', { class: 'todo-list' });
      items.forEach(function (i, n) { ol.appendChild(actRow(i, n + 1, d)); });
      sec.appendChild(ol);
    } else {
      sec.appendChild(h('p', { class: 'quiet', text: 'Nothing left on the list.' }));
    }
    sec.appendChild(markedFoot(marked));
    return sec;
  }

  // ---------- the day in numbers ----------

  function bookedMinutes(d) {
    var out = 0, cur = null;
    timed(d).forEach(function (x) {
      if (cur && x.s <= cur[1]) { cur[1] = Math.max(cur[1], x.f); return; }
      if (cur) out += cur[1] - cur[0];
      cur = [x.s, x.f];
    });
    return out + (cur ? cur[1] - cur[0] : 0);
  }

  function clashState(d) {
    var n = isToday(d) ? clockNow().minutes : -1;
    var past = d.clashes.filter(function (c) { return ZB.hm(c.at) + c.minutes <= n; }).length;
    return { n: d.clashes.length, past: past };
  }

  function numbers(d, todo, done, cls) {
    return h('dl', { class: cls }, [['booked', d.booked], ['open', d.open], ['to do', String(todo)],
      [cls.indexOf('row') >= 0 ? 'done' : 'done today', String(done)]]
      .map(function (p) { return h('div', {}, [h('dt', { text: p[0] }), h('dd', { text: p[1] })]); }));
  }

  function numbersTile(d, todo, done) {
    var sec = ZB.tile('numbers', ['The day', h('span', { class: 'sr', text: ' in numbers' })],
      { room: 'today', aside: h('span', { class: 'label accent', text: d.shape }) });
    sec.appendChild(numbers(d, todo, done, 'nums big'));
    var cs = clashState(d), b = bounds(d);
    var clashWord = !cs.n ? 'none' : cs.n + (cs.past === cs.n ? cs.n === 1 ? ', past' : cs.n === 2 ? ', both past' : ', all past'
      : cs.past ? ', ' + cs.past + ' past' : '');
    sec.appendChild(h('dl', { class: 'facts' }, [['Events', String(timed(d).length)], ['Open blocks', String(d.free.length)],
      ['Clashes', clashWord]].map(function (p) { return h('div', {}, [h('dt', { text: p[0] }), h('dd', { class: 'mono', text: p[1] })]); })));
    var bm = bookedMinutes(d), om = d.free.reduce(function (a, f) { return a + f.minutes; }, 0);
    var booked = h('span', { class: 'bk' });
    booked.style.width = (bm + om ? bm / (bm + om) * 100 : 0).toFixed(1) + '%';
    var foot = h('div', { class: 'num-foot' }, [
      h('div', { class: 'split', role: 'img', 'aria-label': d.booked + ' booked, ' + d.open + ' open' }, [booked, h('span', { class: 'op' })]),
      h('div', { class: 'split-l', 'aria-hidden': 'true' }, [h('span', { text: 'booked' }),
        h('span', { text: 'open, ' + ZB.label(b.lo) + ' to ' + ZB.label(b.hi) })])]);
    var lb = longestLeft(d);
    foot.appendChild(h('p', { class: 'longest' }, lb ? ['Longest open block left: ', h('span', { class: 'mono strong', text: span(lb[0], lb[1]) }),
      ', ' + ZB.dur(lb[1] - lb[0]).replace(' min', 'm') + '.'] : ['No open time left today.']));
    sec.appendChild(foot);
    return sec;
  }

  // ---------- the day ----------

  function ribbon(d) {
    var rb = d.ribbon, today = isToday(d), n = clockNow().minutes;
    var pct = function (m) { return Math.min(100, Math.max(0, (m - rb.lo) / (rb.hi - rb.lo) * 100)); };
    var track = h('div', { class: 'rb' });
    track.style.setProperty('--lanes', rb.lanes);
    var dusk = h('span', { class: 'rb-dusk' });
    track.appendChild(dusk);
    if (rb.daylight) {
      var light = h('span', { class: 'rb-light' });
      light.style.left = rb.daylight[0] + '%';
      light.style.width = Math.max(0, rb.daylight[1] - rb.daylight[0]) + '%';
      track.appendChild(light);
    }
    rb.free.forEach(function (f) {
      var el = h('span', { class: 'rb-free' }, f.width >= 9 ? h('i', {}, [f.label, h('span', { class: 'wide-only', text: ' open' })])
        : f.width >= 5 ? h('i', { class: 'wide-only', text: f.label }) : null);
      el.style.left = f.left + '%';
      el.style.width = f.width + '%';
      track.appendChild(el);
    });
    rb.events.forEach(function (e) {
      var el = h('span', { class: 'rb-ev k-' + e.kind, title: e.title, 'data-full': e.title }, h('span', { class: 'rb-lab', text: bare(e.title) }));
      el.style.left = 'calc(' + e.left + '% + 1px)';
      el.style.width = 'calc(' + e.width + '% - 2px)';
      el.style.setProperty('--lane', e.lane);
      track.appendChild(el);
    });
    if (today && n >= rb.lo && n <= rb.hi) {
      var past = h('span', { class: 'rb-past' }), line = h('span', { class: 'rb-now' }),
        dot = h('span', { class: 'rb-now-dot' }), lab = h('span', { class: 'rb-now-l mono', text: ZB.label(n).replace(/ [AP]M$/, '') });
      past.style.width = pct(n) + '%';
      [line, dot, lab].forEach(function (x) { x.style.left = pct(n) + '%'; });
      if (pct(n) > 88) lab.classList.add('flip');
      [past, line, dot, lab].forEach(function (x) { track.appendChild(x); });
    }
    var scale = h('div', { class: 'rb-hours mono', 'aria-hidden': 'true' });
    rb.ticks.forEach(function (t, i) {
      var el = h('span', { class: (i % 2 ? 'odd' : '') + (t.left === 0 ? ' first' : t.left === 100 ? ' last' : ''),
        text: (t.hour % 12 || 12) + (t.hour < 12 || t.hour === 24 ? 'a' : 'p') });
      el.style.left = t.left + '%';
      scale.appendChild(el);
    });
    var nev = rb.events.length;
    return h('div', { class: 'ribbon', role: 'img', 'aria-label': 'Day ribbon, ' + ZB.label(rb.lo) + ' to ' + ZB.label(rb.hi) + ': ' + nev +
      ' event' + (nev === 1 ? '' : 's') + ', ' + rb.free.length + ' open block' + (rb.free.length === 1 ? '' : 's') +
      (rb.lanes > 1 ? ', some overlap' : '') + (today ? '. Now is ' + ZB.label(n) + '.' : '.') }, [track, scale]);
  }

  // long event names turn into their initials when the bar is too short for them
  function fitLabels() {
    Array.prototype.forEach.call(document.querySelectorAll('.rb-ev .rb-lab'), function (l) {
      if (l.scrollWidth > l.clientWidth + 1) l.textContent = acronym(l.parentNode.getAttribute('data-full'));
    });
  }

  function timeline(d) {
    var t = clockNow(), today = isToday(d), n = t.minutes;
    var rows = [];
    d.events.filter(function (e) { return e.all_day; }).forEach(function (e) {
      rows.push(h('li', { class: 'slot allday' }, [h('span', { class: 'st mono', text: 'all day' }), h('span', { class: 'chip-k k-' + (e.kind || 'other') }),
        h('div', { class: 'sb' }, h('p', { class: 'stt', text: e.title })), h('span', { class: 'sk' })]));
    });
    var items = d.events.filter(function (e) { return !e.all_day; }).map(function (e) { return ['e', e.start, e]; })
      .concat(d.free.map(function (f) { return ['f', f.start, f]; }));
    items.sort(function (a, b) { return a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : (a[0] === 'e') - (b[0] === 'e'); });
    items.forEach(function (r) {
      var x = r[2], s = ZB.hm(x.start), e = ZB.hm(x.end);
      var past = today && e <= n, now = today && s <= n && n < e;
      var cls = 'slot' + (past ? ' past' : '') + (now ? ' now' : '') + (r[0] === 'f' ? ' free' : '');
      var tag = now ? h('span', { class: 'now-chip', text: 'Now' }) : r[0] === 'e' && EV_KIND[x.kind] ?
        h('span', { class: 'sk k-' + x.kind, text: EV_KIND[x.kind] }) : h('span', { class: 'sk' });
      if (r[0] === 'f') {
        rows.push(h('li', { class: cls }, [h('span', { class: 'st mono', text: x.start_label }), h('span', { class: 'chip-k open' }),
          h('div', { class: 'sb' }, [h('p', { class: 'stt', text: 'Open until ' + x.end_label }),
            h('p', { class: 'ssub', text: x.label + (now ? ', ' + ZB.dur(e - n) + ' left' : '') })]), tag]));
        return;
      }
      var sub = ['until ' + x.end_label].concat(x.where ? [x.where] : []).concat(x.source === 'school' ? ['from the school folder'] : []);
      var url = ZB.safeUrl(x.url);
      rows.push(h('li', { class: cls }, [h('span', { class: 'st mono', text: x.start_label }),
        h('span', { class: 'chip-k k-' + (x.kind || 'other'), 'aria-hidden': 'true' }),
        h('div', { class: 'sb' }, [h('p', { class: 'stt' }, url ? h('a', { href: url, target: '_blank', rel: 'noopener noreferrer', text: x.title })
          : x.title), h('p', { class: 'ssub', text: sub.join('; ') })]), tag]));
    });
    return h('ol', { class: 'timeline', id: 'timeline' }, rows);
  }

  function clashNote(d) {
    if (!d.clashes.length) return null;
    var cs = clashState(d), today = isToday(d), n = clockNow().minutes;
    var head = cap(NUM[cs.n] || String(cs.n)) + ' clash' + (cs.n === 1 ? '' : 'es') +
      (cs.past === cs.n ? cs.n === 1 ? ', past.' : cs.n === 2 ? ', both past.' : ', all past.' : '.');
    var parts = d.clashes.map(function (c) {
      var gone = today && ZB.hm(c.at) + c.minutes <= n;
      return bare(c.a) + ' and ' + bare(c.b) + (gone ? ' overlapped ' : ' overlap ') + c.minutes + ' min at ' + c.at_label + '.';
    });
    return h('p', { class: 'clash' }, [I('clash'), h('span', { text: head + ' ' + parts.join(' ') })]);
  }

  function dayTile(d, todo, done) {
    var tn = timed(d).length;
    var sec = ZB.tile('day', 'The day', { room: 'today', aside: [h('span', { class: 'label accent phone-only', text: d.shape }),
      h('span', { class: 'wide-only', text: tn + ' on the calendar, ' + d.free.length + ' open block' + (d.free.length === 1 ? '' : 's') })] });
    sec.appendChild(numbers(d, todo, done, 'nums row phone-only'));
    if (d.ribbon) sec.appendChild(ribbon(d));
    var has = d.events.length || d.free.length;
    if (has) {
      var tl = timeline(d);
      tl.classList.toggle('shut', !showTimeline);
      sec.appendChild(tl);
    } else {
      sec.appendChild(h('p', { class: 'quiet', text: 'Nothing on the calendar today.' }));
    }
    var cn = clashNote(d);
    if (cn) sec.appendChild(cn);
    if (has) {
      sec.appendChild(h('button', { type: 'button', class: 'btn tl-toggle phone-only' + (showTimeline ? ' open' : ''), 'data-key': 'tl-toggle',
        'aria-expanded': showTimeline ? 'true' : 'false', 'aria-controls': 'timeline',
        onclick: function () { showTimeline = !showTimeline; ZB.redraw(); } },
      [h('span', { text: showTimeline ? 'Hide timeline' : 'Show timeline' }),
        h('span', { class: 'tl-n' }, [(d.events.length + d.free.length) + ' entries', I('chev')])]));
    }
    return sec;
  }

  // ---------- the brief and tomorrow ----------

  function briefTile(d) {
    var url = briefUrl(d);
    var kick = isToday(d) ? 'This morning\u2019s brief' : 'The ' + fmt(d.date, { weekday: 'short', month: 'short', day: 'numeric' }) + ' brief';
    var sec = ZB.tile('brief', kick, { room: 'today' });
    if (d.headline) sec.appendChild(h('blockquote', { class: 'headline', text: d.headline }));
    if (d.opening) sec.appendChild(h('p', { class: 'opening', text: d.opening }));
    if (d.tomorrow) {
      sec.appendChild(h('div', { class: 'tmr-in phone-only' }, [h('div', { class: 'tmr-head' }, [h('h3', { class: 'label', text: 'Tomorrow' }),
        h('span', { class: 'mono muted', text: fmt(plus1(d.date), { weekday: 'short', month: 'short', day: 'numeric' }) })]),
      h('p', { text: d.tomorrow })]));
    }
    if (url) sec.appendChild(h('a', { class: 'btn brief-btn', href: url }, [briefLabel(d), I('arrow')]));
    return sec;
  }

  function tomorrowTile(d) {
    var sec = ZB.tile('tomorrow', 'Tomorrow', { room: 'today' });
    sec.appendChild(h('p', { class: 'tmr-date', text: fmt(plus1(d.date), { weekday: 'short', month: 'short', day: 'numeric' }) }));
    sec.appendChild(h('p', { class: 'tmr-text', text: d.tomorrow }));
    return sec;
  }

  // ---------- render ----------

  function render(el, d) {
    data = d;
    almanac(d);
    var focusDone = d.focus && hides(d.focus.id, false);
    var serverDone = !d.focus && d.hidden.some(function (i) { return i.origin === 'focus' && i.mark && i.mark.state === 'done'; });
    var focus = d.focus && !focusDone ? d.focus : null;
    var items = d.items.filter(function (i) { return !hides(i.id, false); });
    // an undo brings a hidden item straight back while the server catches up
    d.hidden.forEach(function (i) { if (ZB.pending[i.id] === 'open') items.push(i); });
    var marked = d.hidden.filter(function (i) { return ZB.pending[i.id] !== 'open'; })
      .concat(d.items.concat(d.focus ? [d.focus] : []).filter(function (i) { return hides(i.id, false); }));
    var todo = items.length + (focus ? 1 : 0);
    var done = marked.filter(function (i) { return (ZB.pending[i.id] || (i.mark && i.mark.state)) === 'done'; }).length;

    el.appendChild(nowTile(d));
    el.appendChild(focusTile(d, focus, focusDone || serverDone));
    el.appendChild(numbersTile(d, todo, done));
    el.appendChild(dayTile(d, todo, done));
    el.appendChild(todoTile(d, items, marked));
    el.appendChild(briefTile(d));
    if (d.tomorrow) el.appendChild(tomorrowTile(d));
    setTimeout(fitLabels, 0);
  }

  ZB.modules.today = { render: render, deps: ['agent'] };
})();
