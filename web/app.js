// the board's client: state from /api/state, live updates over server-sent events, marks, the agent panel.
// the page keeps no state of its own; storage can throw (private mode, blocked), so every touch is wrapped
(function () {
  'use strict';
  var ZB = window.Board = { modules: {}, pending: {}, cfg: { agent: 'Agent', tz: 'UTC', location: '', now: '', prefix: 'hd-',
    transport: 'copy', actions: { dispatch: false } }, state: { seq: -1, modules: {}, marks: [], requests: [], layout: [] } };
  var tokenMeta = document.querySelector('meta[name="daybook-token"]');
  var token = tokenMeta ? tokenMeta.getAttribute('content') : '';

  // ---------- small helpers ----------

  // h('p', {class: 'x', text: 'hi', onclick: fn}, [kids]) builds dom without innerHTML
  function h(tag, attrs, kids) {
    var el = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      var v = attrs[k];
      if (v === null || v === undefined || v === false) return;
      if (k === 'text') el.textContent = v;
      else if (k === 'class') el.className = v;
      else if (k === 'style') Object.keys(v).forEach(function (p) { el.style.setProperty(p, v[p]); });
      else if (k.slice(0, 2) === 'on') el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? '' : v);
    });
    (Array.isArray(kids) ? kids : kids === undefined || kids === null ? [] : [kids]).forEach(function (c) {
      if (c === null || c === undefined || c === false) return;
      el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    });
    return el;
  }
  ZB.h = h;

  // svg in code. s(tag, attrs, kids) for drawings, ZB.icon(name) for the stroke icons
  var NS = 'http://www.w3.org/2000/svg';
  ZB.s = function (tag, attrs, kids) {
    var el = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (k) { if (attrs[k] !== null && attrs[k] !== undefined) el.setAttribute(k, attrs[k]); });
    (kids || []).forEach(function (c) { if (c) el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return el;
  };
  var ring = function (cx, cy, r) { return 'M' + (cx - r) + ' ' + cy + 'a' + r + ' ' + r + ' 0 1 0 ' + 2 * r + ' 0a' + r + ' ' + r + ' 0 1 0 ' + -2 * r + ' 0'; };
  var SPARK = 'M12 3c.6 4.2 2.8 6.4 7 7-4.2.6-6.4 2.8-7 7-.6-4.2-2.8-6.4-7-7 4.2-.6 6.4-2.8 7-7z';
  var ICONS = {
    arrow: ['M5 12h14M13 6l6 6-6 6', 2.2], out: ['M7 17 17 7M9 7h8v8', 2.2], chev: ['M6 9l6 6 6-6', 2.2],
    check: ['M5 12.5l4.5 4.5L19 7.5', 2.4], close: ['M6.5 6.5l11 11M17.5 6.5l-11 11', 2.2],
    spark: [SPARK, 0], clock: [ring(12, 12, 8.5) + 'M12 7.5V12l3 2', 2],
    msg: ['M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v8a2.5 2.5 0 0 1-2.5 2.5H11l-4.5 3.5V17A2.5 2.5 0 0 1 4 14.5z', 1.9],
    folder: ['M3.5 7.5a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z', 2],
    clash: [ring(9, 12, 6) + ring(15, 12, 6), 2],
    sun: [ring(12, 12, 4) + 'M12 2.5v2.5M12 19v2.5M2.5 12H5M19 12h2.5M5.3 5.3l1.8 1.8M16.9 16.9l1.8 1.8M5.3 18.7l1.8-1.8M16.9 7.1l1.8-1.8', 2],
    cloud: ['M7 18.5h10a4 4 0 0 0 .6-7.95A5.5 5.5 0 0 0 7.1 9.6 4.5 4.5 0 0 0 7 18.5z', 1.9],
    rain: ['M7 15.5h10a4 4 0 0 0 .6-7.95A5.5 5.5 0 0 0 7.1 6.6 4.5 4.5 0 0 0 7 15.5zM9 18.5l-1 2M13 18.5l-1 2M17 18.5l-1 2', 1.9],
    moon: ['M19.5 14.5A8 8 0 0 1 9.5 4.5a8 8 0 1 0 10 10z', 1.9],
    today: ['M3 17.5h18M7 17.5a5 5 0 0 1 10 0M12 6.5v2M5.8 9.8l1.4 1.4M18.2 9.8l-1.4 1.4', 1.9],
    agent: [SPARK + 'M18.5 15.5c.2 1.4.9 2.1 2.3 2.3-1.4.2-2.1.9-2.3 2.3-.2-1.4-.9-2.1-2.3-2.3 1.4-.2 2.1-.9 2.3-2.3z', 1.9],
    fleet: ['M6 4.5h12a2 2 0 0 1 2 2v2a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-2a2 2 0 0 1 2-2zM6 13.5h12a2 2 0 0 1 2 2v2a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-2a2 2 0 0 1 2-2zM7.5 7.5h.01M7.5 16.5h.01', 1.9]
  };
  ZB.icon = function (name, cls) {
    var i = ICONS[name];
    var path = ZB.s('path', { d: i[0] });
    if (i[1]) path.setAttribute('stroke-width', String(i[1]));
    return ZB.s('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true', focusable: 'false',
      class: 'ic ic-' + name + (i[1] ? '' : ' ic-fill') + (cls ? ' ' + cls : '') }, [path]);
  };

  ZB.store = {
    get: function (k) { try { return window.localStorage.getItem('daybook:' + k); } catch (e) { return null; } },
    set: function (k, v) {
      try { if (v === null) window.localStorage.removeItem('daybook:' + k); else window.localStorage.setItem('daybook:' + k, v); } catch (e) {}
    }
  };

  ZB.safeUrl = function (u) { return typeof u === 'string' && /^https:\/\/[^\s"'<>]+$/.test(u) ? u : ''; };

  // the configured zone's wall clock, whatever the device's zone. a frozen clock (demo, tests) stands still
  ZB.now = function () {
    var f = ZB.cfg.now ? new Date(ZB.cfg.now) : null;
    return f && !isNaN(f) ? f : new Date();
  };
  ZB.local = function () {
    var parts = {};
    try {
      new Intl.DateTimeFormat('en-CA', { timeZone: ZB.cfg.tz || 'UTC', year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(ZB.now()).forEach(function (p) { parts[p.type] = p.value; });
    } catch (e) { var d = ZB.now(); return { date: '', minutes: d.getHours() * 60 + d.getMinutes() }; }
    return { date: parts.year + '-' + parts.month + '-' + parts.day, minutes: (+parts.hour) * 60 + (+parts.minute) };
  };
  ZB.hm = function (s) { var m = /^(\d{1,2}):(\d{2})/.exec(s || ''); return m ? (+m[1]) * 60 + (+m[2]) : null; };

  ZB.clock = function (iso) {
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d)) return '';
    try { return d.toLocaleTimeString('en-US', { timeZone: ZB.cfg.tz || 'UTC', hour: 'numeric', minute: '2-digit' }); }
    catch (e) { return d.toLocaleTimeString(); }
  };
  ZB.ago = function (iso) {
    var d = new Date(iso);
    if (!iso || isNaN(d)) return '';
    var m = Math.round((ZB.now().getTime() - d.getTime()) / 60000);
    if (m < 1) return 'just now';
    if (m < 60) return m + 'm ago';
    var hrs = Math.floor(m / 60);
    if (hrs < 24) return hrs + 'h ' + (m % 60 ? (m % 60) + 'm ' : '') + 'ago';
    return Math.floor(hrs / 24) + 'd ago';
  };

  // one tile of the board: <section class="tile t-name" data-room> with a small uppercase heading
  ZB.tile = function (name, title, o) {
    o = o || {};
    var sec = h('section', { class: 'tile t-' + name + (o.cls ? ' ' + o.cls : ''), 'data-room': o.room || 'today',
      'aria-labelledby': 'h-' + name });
    sec.appendChild(h('div', { class: 'tile-head' }, [
      h('h2', { class: 'label' + (o.accent ? ' accent' : ''), id: 'h-' + name }, title),
      o.aside ? h('span', { class: 'tile-aside' }, o.aside) : null]));
    return sec;
  };
  ZB.dur = function (m) {
    m = Math.max(0, Math.round(m));
    var hh = Math.floor(m / 60), mm = m % 60;
    return hh ? hh + 'h' + (mm ? ' ' + mm + 'm' : '') : mm + ' min';
  };
  // minutes after midnight to "2 PM" or "3:15 PM"
  ZB.label = function (m) {
    m = ((Math.round(m) % 1440) + 1440) % 1440;
    var hh = Math.floor(m / 60), mm = m % 60;
    return (hh % 12 || 12) + (mm ? ':' + (mm < 10 ? '0' : '') + mm : '') + (hh < 12 ? ' AM' : ' PM');
  };
  ZB.nowClock = function () { return ZB.clock(ZB.now().toISOString()); };
  ZB.agent = function () { return ZB.cfg.agent || 'Agent'; };

  // ---------- api ----------

  function api(method, url, body, retried) {
    return send(method, url, body).then(function (res) {
      // the server restarted under an open page: take its new token and try once more
      if (res.status !== 403 || retried || body === undefined || !res.data || res.data.error !== 'stale token') return res;
      return fetch('/api/token', { credentials: 'same-origin', cache: 'no-store' }).then(function (r) { return r.json(); })
        .then(function (j) {
          if (!j || !j.token) return res;
          token = j.token;
          if (tokenMeta) tokenMeta.setAttribute('content', token);
          return api(method, url, body, true);
        }, function () { return res; });
    });
  }

  function send(method, url, body) {
    var opt = { method: method, credentials: 'same-origin', cache: 'no-store', headers: {} };
    if (body !== undefined) {
      opt.headers['Content-Type'] = 'application/json';
      opt.headers['X-Daybook-Token'] = token;
      opt.body = JSON.stringify(body);
    }
    return fetch(url, opt).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok, status: r.status, data: j }; });
    });
  }
  ZB.api = api;

  // ---------- state and drawing ----------

  var loading = false, again = false, lastOk = 0;

  function load(full) {
    if (loading) { again = true; return Promise.resolve(); }
    loading = true;
    var url = '/api/state' + (!full && ZB.state.seq >= 0 ? '?since=' + ZB.state.seq : '');
    return api('GET', url).then(function (res) {
      if (!res.ok) throw new Error('state ' + res.status);
      var d = res.data, changed = Object.keys(d.modules || {});
      if (full) ZB.state.modules = {};
      changed.forEach(function (k) { ZB.state.modules[k] = d.modules[k]; });
      ZB.state.seq = d.seq;
      ZB.state.marks = d.marks || [];
      ZB.state.requests = d.requests || [];
      ZB.state.layout = d.layout || ZB.state.layout;
      ZB.state.models = d.models || ZB.state.models;
      if (d.config) { ZB.cfg = d.config; names(); }
      lastOk = Date.now();
      draw(full ? null : changed);
      live(source && source.readyState === 1 ? 'on' : 'poll');
    }).catch(function () {
      live('off');
    }).then(function () {
      loading = false;
      if (again) { again = false; load(false); }
    });
  }
  ZB.load = load;

  // a module's wrapper is display: contents, so its tiles sit straight in the board grid
  function slot(m) {
    var id = 'mod-' + m.name, el = document.getElementById(id);
    if (!el) {
      el = h('div', { class: 'mod mod-' + m.name, id: id });
      document.getElementById('main').appendChild(el);
    }
    return el;
  }
  function failed(el, m, msg) {
    var t = ZB.tile('err-' + m.name, m.title, { room: m.room || m.name, cls: 't-error' });
    t.appendChild(h('p', { class: 'unavail', text: msg }));
    el.appendChild(t);
  }

  // keep focus on the same control across a redraw
  function focusKey() { var a = document.activeElement; return a && a.getAttribute ? a.getAttribute('data-key') : null; }
  function refocus(key) {
    if (!key) return;
    var el = document.querySelector('[data-key="' + key.replace(/"/g, '') + '"]');
    if (el) el.focus({ preventScroll: true });
  }

  function draw(only) {
    var key = focusKey();
    ZB.state.layout.forEach(function (m) {
      var mod = ZB.modules[m.name];
      // a module can draw from another one's data (today shows the focus's session from the agent)
      var dep = mod && mod.deps && only && mod.deps.some(function (n) { return only.indexOf(n) >= 0; });
      if (only && only.indexOf(m.name) < 0 && !dep && !ZB.dirty) return;
      var el = slot(m), data = ZB.state.modules[m.name];
      el.textContent = '';
      if (!data) return;
      if (data.error || !mod) {
        failed(el, m, data.error || 'unavailable: no drawing for this module');
        return;
      }
      try { mod.render(el, data, ZB); }
      catch (e) {
        el.textContent = '';
        failed(el, m, 'unavailable: the page could not draw this (' + e.message + ')');
      }
    });
    ZB.dirty = false;
    refocus(key);
    tabs();
    if (!document.body.classList.contains('arrived')) setTimeout(function () { document.body.classList.add('arrived'); }, 900);
  }
  ZB.redraw = function () { ZB.dirty = true; draw(null); };

  // ---------- live ----------

  var source = null, poller = null, liveState = '';
  function live(state) {
    var el = document.getElementById('live');
    if (!el) return;
    liveState = state;
    el.className = 'live ' + (state === 'on' ? 'on' : state === 'off' ? 'off' : '');
    var txt = el.querySelector('.live-text');
    var at = lastOk ? ZB.clock(new Date(lastOk).toISOString()) : '';
    var t = state === 'on' ? 'Live, ' + ZB.nowClock() : state === 'off' ? 'Offline' + (at ? ', last ' + at : '') : 'Updated ' + at;
    if (txt.textContent !== t) txt.textContent = t;
  }

  function connect() {
    if (!window.EventSource) { poll(); return; }
    if (source) source.close();
    source = new EventSource('/api/events?since=' + Math.max(0, ZB.state.seq));
    source.addEventListener('open', function () { live('on'); });
    source.addEventListener('seq', function (e) {
      var n = parseInt(e.data, 10);
      if (n > ZB.state.seq) load(false); else live('on');
    });
    source.addEventListener('error', function () { live(navigator.onLine === false ? 'off' : 'poll'); poll(); });
  }
  // a slow poll covers a dropped stream; the browser reconnects the stream on its own
  function poll() {
    if (poller) return;
    poller = setInterval(function () {
      if (source && source.readyState === 1) { clearInterval(poller); poller = null; return; }
      load(false);
    }, 20000);
  }

  // ---------- toast ----------

  var toastTimer = null;
  ZB.toast = function (msg, action, fn) {
    var t = document.getElementById('toast');
    t.textContent = '';
    t.appendChild(h('span', { text: msg }));
    if (action) t.appendChild(h('button', { type: 'button', text: action, onclick: function () { hide(); fn(); } }));
    t.hidden = false;
    requestAnimationFrame(function () { t.classList.add('on'); });
    clearTimeout(toastTimer);
    toastTimer = setTimeout(hide, action ? 6500 : 3500);
    function hide() { t.classList.remove('on'); setTimeout(function () { t.hidden = true; }, 250); }
  };

  // ---------- marks ----------

  var WORD = { done: 'Marked done.', snoozed: 'Snoozed till tomorrow.', dismissed: 'Dismissed.', open: 'Back on the list.' };
  // todoist's answer rides in the toast. "not connected" is said once, then the mark is just a mark
  function todoistWords(t) {
    if (!t || !t.message) return '';
    if (/not connected/.test(t.message)) {
      if (ZB.todoistNoted || ZB.store.get('todoist-noted')) return '';
      ZB.todoistNoted = true;
      ZB.store.set('todoist-noted', '1');
    }
    return t.message;
  }

  ZB.mark = function (item, state, quiet) {
    var said = '';
    ZB.pending[item.id] = state;
    ZB.redraw();
    return api('POST', '/api/marks', { item_id: item.id, title: item.title, source: item.source || '', ref: item.ref || '',
      state: state }).then(function (res) {
      if (!res.ok) throw new Error((res.data && res.data.error) || 'not saved');
      said = todoistWords(res.data && res.data.todoist);
      return load(false);
    }).then(function () {
      delete ZB.pending[item.id];
      ZB.redraw();
      if (!quiet || said) {
        ZB.toast(said ? WORD[state] + ' ' + said : WORD[state], state === 'open' ? null : 'Undo',
          function () { ZB.mark(item, 'open', true); });
      }
    }).catch(function (e) {
      delete ZB.pending[item.id];
      ZB.redraw();
      ZB.toast('Could not save that: ' + e.message + '.');
    });
  };

  // ---------- confirm dialog ----------

  // ZB.confirm({title, body, ok}) resolves true or false. escape and the scrim cancel; tab stays inside
  ZB.confirm = function (o) {
    return new Promise(function (resolve) {
      var sc = document.getElementById('scrim'), back = document.activeElement;
      var cancel = h('button', { type: 'button', class: 'btn', 'data-key': 'dlg-cancel', text: o.cancel || 'Cancel' });
      var ok = h('button', { type: 'button', class: 'btn primary', 'data-key': 'dlg-ok', text: o.ok || 'OK' });
      var dlg = h('div', { class: 'dialog', role: 'alertdialog', 'aria-modal': 'true', 'aria-labelledby': 'dlg-title',
        'aria-describedby': 'dlg-body' }, h('div', { class: 'dialog-in' }, [
        h('h2', { id: 'dlg-title', text: o.title }), h('p', { id: 'dlg-body', text: o.body }),
        h('div', { class: 'dialog-acts' }, [cancel, ok])]));
      function done(v) {
        document.removeEventListener('keydown', key, true);
        sc.removeEventListener('click', onScrim);
        dlg.classList.remove('on');
        if (!panelState) { sc.classList.remove('on'); document.body.classList.remove('locked'); }
        setTimeout(function () { dlg.remove(); if (!panelState) sc.hidden = true; }, 200);
        if (back && back.focus && document.contains(back)) back.focus({ preventScroll: true });
        resolve(v);
      }
      function key(e) {
        if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); done(false); }
        else if (e.key === 'Tab') {
          e.preventDefault();
          (document.activeElement === cancel ? ok : cancel).focus();
        }
      }
      function onScrim() { done(false); }
      cancel.addEventListener('click', function () { done(false); });
      ok.addEventListener('click', function () { done(true); });
      document.addEventListener('keydown', key, true);
      sc.addEventListener('click', onScrim);
      document.body.appendChild(dlg);
      sc.hidden = false;
      document.body.classList.add('locked');
      requestAnimationFrame(function () { sc.classList.add('on'); dlg.classList.add('on'); cancel.focus(); });
    });
  };

  // ---------- did you send it ----------

  // only a request you confirm as sent is ever matched to a session
  ZB.confirmSent = function (id, sent) {
    return api('POST', '/api/requests/sent', { id: id, sent: sent }).then(function (res) {
      if (!res.ok) throw new Error((res.data && res.data.error) || 'not saved');
      ZB.toast(sent ? 'Noted. Watching for the session.' : 'Noted as not sent.');
      return load(false);
    }).catch(function (e) { ZB.toast('Could not save that: ' + e.message + '.'); });
  };
  ZB.sentButtons = function (id, done) {
    return [h('button', { type: 'button', class: 'btn primary', 'data-key': 'sent:' + id, text: 'Sent it',
      onclick: function () { ZB.confirmSent(id, true).then(done); } }),
    h('button', { type: 'button', class: 'btn', 'data-key': 'unsent:' + id, text: 'Didn\u2019t send',
      onclick: function () { ZB.confirmSent(id, false).then(done); } })];
  };

  // ---------- the agent panel ----------

  function runners() { return [['claude', 'Claude Code'], ['codex', 'Codex'], ['agent', ZB.agent()]]; }
  // what the dispatch can start, from /api/state. an empty list means the agent picks, with the reason as a tooltip
  function modelsFor(runner) {
    var m = (ZB.state.models || {})[runner] || {};
    return { list: m.models || [], why: m.error || 'no models list' };
  }
  function defaultModel(runner) {
    var l = modelsFor(runner).list;
    var d = l.filter(function (m) { return m['default']; })[0] || l[0];
    return d ? d.id : '';
  }
  var REACH = [['draft', 'Draft', 'Write files only. Never submit, send or push.'],
    ['branch', 'Branch', 'Commit on a branch. Never push.'],
    ['ship', 'Ship', 'May push and deploy. For your own apps only.']];
  var GROUPS = ['Projects', 'Work roots', 'Classes'];
  var panelState = null;

  function apple() { return /iPhone|iPad|iPod|Macintosh|Mac OS X/.test(navigator.userAgent); }
  function smsUrl(u) { return !u || apple() ? u : u.replace('&body=', '?body='); }
  ZB.smsUrl = smsUrl;
  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
    var ta = h('textarea', { class: 'sr', readonly: true });
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    ta.setSelectionRange(0, text.length);  // ios ignores select() alone
    var ok = false;
    try { ok = document.execCommand('copy'); } catch (e) {}
    ta.remove();
    return ok ? Promise.resolve() : Promise.reject(new Error('copy blocked'));
  }

  ZB.copy = copyText;
  // a button that copies a request's text; the text itself sits beside it, so a blocked copy still leaves it readable
  ZB.copyButton = function (text, label, key) {
    return h('button', { type: 'button', class: 'btn', 'data-key': key || null, text: label || 'Copy the request',
      onclick: function (e) {
        var b = e.currentTarget;
        copyText(text).then(function () { b.textContent = 'Copied'; }, function () { b.textContent = 'Copy blocked'; });
      } });
  };

  function seg(name, opts, value, onchange) {
    var wrap = h('div', { class: 'seg', role: 'radiogroup' });
    opts.forEach(function (o) {
      var id = 'p-' + name + '-' + o[0];
      var input = h('input', { type: 'radio', name: name, id: id, value: o[0], 'data-key': 'seg:' + name + ':' + o[0],
        onchange: function () { onchange(o[0]); } });
      input.checked = o[0] === value;
      wrap.appendChild(input);
      wrap.appendChild(h('label', { for: id, text: o[1] }));
    });
    return wrap;
  }

  function closePanel() {
    var p = document.getElementById('panel'), sc = document.getElementById('scrim');
    if (!panelState) return;
    var opener = panelState.opener;
    panelState = null;
    p.classList.remove('on');
    sc.classList.remove('on');
    document.body.classList.remove('locked');
    setTimeout(function () { if (!panelState) { p.hidden = true; sc.hidden = true; p.textContent = ''; } }, 280);
    var back = opener && opener.getAttribute && document.querySelector('[data-key="' + opener.getAttribute('data-key') + '"]');
    if (back) back.focus({ preventScroll: true });
  }
  ZB.closePanel = closePanel;

  ZB.openPanel = function (item, choices) {
    var p = document.getElementById('panel'), sc = document.getElementById('scrim');
    var d = item.defaults || {}, who = ZB.agent();
    var orig = { runner: d.runner || 'agent', model: d.model || defaultModel(d.runner || 'agent'),
      where: d.where || '', reach: d.reach || 'draft' };
    var cur = Object.assign({}, orig);
    choices = choices || [];
    panelState = { item: item, opener: document.activeElement };

    var modelSel = h('select', { id: 'p-model', 'data-key': 'p-model', onchange: function () { cur.model = modelSel.value; } });
    var modelField = h('label', { class: 'field', for: 'p-model' }, [h('span', { text: 'Model' }), modelSel]);
    var whereSel = h('select', { id: 'p-where', 'data-key': 'p-where', onchange: function () { cur.where = whereSel.value; sync(); } });
    var known = {};
    choices.forEach(function (c) { known[c.path] = c; });
    whereSel.appendChild(h('option', { value: '', text: 'Let ' + who + ' choose' }));
    if (orig.where && !known[orig.where]) {
      whereSel.appendChild(h('option', { value: orig.where, text: 'Suggested: ' + (d.where_label || orig.where) }));
    }
    GROUPS.forEach(function (g) {
      var grp = h('optgroup', { label: g });
      choices.filter(function (c) { return c.group === g; }).forEach(function (c) {
        grp.appendChild(h('option', { value: c.path, text: c.label + (c.path === orig.where ? ' (suggested)' : '') }));
      });
      if (grp.children.length) whereSel.appendChild(grp);
    });
    whereSel.value = orig.where;
    var whereNote = h('p', { class: 'p-note', hidden: true,
      text: 'That folder is outside the allowed roots, so a click cannot start it. Send it to ' + who + ' yourself.' });
    var reachHelp = h('p', { class: 'seg-help' });
    var note = h('textarea', { id: 'p-note', rows: '3', maxlength: '2000', 'data-key': 'p-note',
      placeholder: 'Optional. ' + who + ' reads this with the request.' });
    var start = h('button', { type: 'submit', class: 'btn primary', 'data-key': 'p-start', text: 'Start' });
    var result = h('p', { class: 'p-result', role: 'status', 'aria-live': 'polite' });
    var follow = h('div', { class: 'p-follow', hidden: true });

    function okWhere(v) { return !v || !!known[v] || (v === orig.where && item.where_ok !== false); }
    function fillModels() {
      var ms = modelsFor(cur.runner), byProv = {};
      modelSel.textContent = '';
      modelSel.removeAttribute('title');
      if (!ms.list.length) {
        modelSel.appendChild(h('option', { value: '', text: who + ' picks' }));
        modelSel.setAttribute('title', ms.why);
      }
      ms.list.forEach(function (m) { (byProv[m.provider] = byProv[m.provider] || []).push(m); });
      var provs = Object.keys(byProv);
      provs.forEach(function (pv) {
        var host = provs.length > 1 ? h('optgroup', { label: pv }) : modelSel;
        byProv[pv].forEach(function (m) {
          host.appendChild(h('option', { value: m.id, text: m.label + (m['default'] ? ' (default)' : '') }));
        });
        if (host !== modelSel) modelSel.appendChild(host);
      });
      if (!ms.list.some(function (m) { return m.id === cur.model; })) {
        cur.model = cur.runner === orig.runner && ms.list.some(function (m) { return m.id === orig.model; }) ? orig.model
          : defaultModel(cur.runner);
      }
      modelSel.value = cur.model;
      modelField.hidden = cur.runner === 'agent';
    }
    function sync() {
      whereNote.hidden = okWhere(cur.where);
      start.textContent = okWhere(cur.where) ? 'Start' : 'Get the text';
      REACH.forEach(function (r) { if (r[0] === cur.reach) reachHelp.textContent = r[2]; });
    }

    var form = h('form', { class: 'p-form', novalidate: true, onsubmit: function (e) { e.preventDefault(); send(); } }, [
      h('fieldset', { class: 'field' }, [h('legend', { text: 'Runner' }),
        seg('runner', runners(), cur.runner, function (v) { cur.runner = v; fillModels(); sync(); })]),
      modelField,
      h('label', { class: 'field', for: 'p-where' }, [h('span', { text: 'Where' }), whereSel]),
      whereNote,
      h('fieldset', { class: 'field' }, [h('legend', { text: 'Reach' }),
        seg('reach', REACH, cur.reach, function (v) { cur.reach = v; sync(); }), reachHelp]),
      h('label', { class: 'field', for: 'p-note' }, [h('span', { text: 'Anything ' + who + ' should know?' }), note]),
      h('div', { class: 'p-actions' }, [start, result]),
      follow
    ]);

    function sentButtons(id) {
      ZB.sentButtons(id, function () {
        result.textContent = 'Thanks. The ' + who + ' list shows where it stands.';
        follow.querySelectorAll('[data-key^="sent:"], [data-key^="unsent:"]').forEach(function (b) { b.remove(); });
      }).forEach(function (b) { follow.appendChild(b); });
    }

    function after(res) {
      var dd = res.data || {};
      follow.textContent = '';
      var url = smsUrl(dd.sms_url || '');
      if (dd.status === 'sent') {
        result.className = 'p-result ok';
        result.textContent = cur.runner === 'agent' ? 'Sent to ' + who + ' to handle directly.'
          : 'Sent to ' + who + '. The session shows up here when it starts.';
      } else if (url) {
        result.className = 'p-result ok';
        result.textContent = dd.error === 'outside' ? dd.message + ' Messages opened with the request; tap send.'
          : 'Messages opened with the request; tap send.';
        follow.appendChild(h('a', { class: 'btn text', href: url }, ['Open Messages again', ZB.icon('out')]));
        if (dd.id) sentButtons(dd.id);
        window.location.href = url;
      } else if (dd.status === 'copy' || dd.error === 'outside') {
        // nothing sends it: the text is here to copy, then you say whether you sent it
        result.className = 'p-result ok';
        result.textContent = dd.message || 'Copy the request and send it to ' + who + ' yourself.';
        follow.appendChild(h('pre', { class: 'p-copytext', text: dd.text || '' }));
        if (dd.id) sentButtons(dd.id);
      } else {
        result.className = 'p-result err';
        result.textContent = dd.message || dd.error || 'Something went wrong.';
      }
      if (dd.text) follow.appendChild(ZB.copyButton(dd.text, 'Copy the request', 'p-copy'));
      follow.hidden = !follow.children.length;
      start.disabled = false;
      start.textContent = dd.status === 'sent' || url || dd.status === 'copy' ? 'Send again' : 'Try again';
    }

    function send() {
      start.disabled = true;
      start.textContent = 'Sending';
      result.className = 'p-result';
      result.textContent = '';
      var changed = ['runner', 'model', 'where', 'reach'].filter(function (k) { return cur[k] !== orig[k]; });
      api('POST', '/api/requests', { item_id: item.id, title: item.title, source: item.source || '', ref: item.ref || '',
        runner: cur.runner, model: cur.runner === 'agent' ? '' : cur.model, where: cur.where, reach: cur.reach,
        note: note.value.trim(), changed: changed, suggested_by: d.from || 'board' }).then(function (res) {
        after(res);
        load(false);
      }).catch(function () {
        start.disabled = false;
        start.textContent = 'Try again';
        result.className = 'p-result err';
        result.textContent = 'Could not reach the board.';
      });
    }

    function markBtn(state, label) {
      return h('button', { type: 'button', class: 'btn text', 'data-key': 'p-' + state, text: label,
        onclick: function () { closePanel(); ZB.mark(item, state); } });
    }
    var meta = [item.when, item.source].filter(Boolean).join(' · ');
    p.textContent = '';
    p.appendChild(h('div', { class: 'panel-in' }, [
      h('div', { class: 'grab', 'aria-hidden': 'true' }),
      h('header', { class: 'p-head' }, [
        h('p', { class: 'p-kick' }, [ZB.icon('spark'), 'Hand to ' + who]),
        h('h2', { id: 'panel-title', text: item.title }),
        meta ? h('p', { class: 'meta', text: meta }) : null,
        h('button', { type: 'button', class: 'p-close', 'aria-label': 'Close', 'data-key': 'p-close',
          onclick: closePanel }, ZB.icon('close'))]),
      form,
      h('div', { class: 'p-more' }, [markBtn('done', 'Mark done'), h('span', { class: 'sep', 'aria-hidden': 'true', text: '·' }),
        markBtn('snoozed', 'Snooze till tomorrow'), h('span', { class: 'sep', 'aria-hidden': 'true', text: '·' }),
        markBtn('dismissed', 'Dismiss')])
    ]));
    if (d.prompt) note.placeholder = 'Optional. The brief suggests: ' + d.prompt;
    fillModels();
    sync();
    p.hidden = false;
    sc.hidden = false;
    document.body.classList.add('locked');
    requestAnimationFrame(function () {
      p.classList.add('on');
      sc.classList.add('on');
      var first = p.querySelector('input[name="runner"]:checked');
      if (first) first.focus({ preventScroll: true });
    });
  };

  document.addEventListener('keydown', function (e) {
    if (!panelState) return;
    if (e.key === 'Escape') { e.preventDefault(); closePanel(); return; }
    if (e.key !== 'Tab') return;
    // keep tab inside the panel while it is open
    var f = Array.prototype.filter.call(document.getElementById('panel').querySelectorAll(
      'button, select, textarea, a[href], input:checked'), function (x) { return !x.disabled && x.offsetParent !== null; });
    if (!f.length) return;
    if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
    else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
  });
  document.addEventListener('click', function (e) { if (e.target && e.target.id === 'scrim') closePanel(); });

  // ---------- names from the config: the board's title and the agent's name ----------

  function names() {
    var brand = document.getElementById('brand'), tab = document.getElementById('tab-name-agent');
    if (brand && ZB.cfg.title && brand.textContent !== ZB.cfg.title) brand.textContent = ZB.cfg.title;
    if (ZB.cfg.title && document.title !== ZB.cfg.title) document.title = ZB.cfg.title;
    if (tab && tab.textContent !== ZB.agent()) tab.textContent = ZB.agent();
  }

  // ---------- rooms (phone): today, the agent, fleet behind a tab bar ----------

  var ROOMS = ['today', 'agent', 'fleet'];
  function setRoom(r, how) {
    if (ROOMS.indexOf(r) < 0) return;
    var changed = document.body.getAttribute('data-room') !== r;
    document.body.setAttribute('data-room', r);
    Array.prototype.forEach.call(document.querySelectorAll('#tabs button'), function (b) {
      if (b.getAttribute('data-tab') === r) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
    });
    ZB.store.set('room', r);
    if (how === 'init') return;
    // no scroll jump to an id: replaceState, not location.hash
    if (window.location.hash !== '#' + r) { try { history.replaceState(null, '', '#' + r); } catch (e) {} }
    if (changed) window.scrollTo(0, 0);
  }
  ZB.setRoom = setRoom;

  ZB.needy = function (q) { return q.status === 'prefilled' || q.status === 'copy' || q.status === 'no_session'; };

  function tabs() {
    var r = ZB.state.modules.agent, f = ZB.state.modules.fleet, who = ZB.agent();
    var need = 0;
    if (r && !r.error) need = (r.waiting || []).length + (r.requests || []).filter(ZB.needy).length;
    var badge = document.getElementById('tab-badge'), ag = document.querySelector('#tabs [data-tab="agent"]');
    badge.hidden = !need;
    badge.textContent = String(need);
    ag.setAttribute('aria-label', need ? who + ', ' + need + ' need' + (need === 1 ? 's' : '') + ' you' : who);
    var dot = document.getElementById('tab-dot'), fl = document.querySelector('#tabs [data-tab="fleet"]');
    var sv = f && !f.error ? f.services || {} : {};
    // a device nobody checked is not down
    var downDev = f && !f.error ? (f.devices || []).filter(function (d) { return d.up === false; }).length : 0;
    var bad = (sv.down || 0) + downDev, warn = sv.drift || 0;
    dot.hidden = !bad && !warn;
    dot.className = 'tab-dot ' + (bad ? 'bad' : 'warn');
    fl.setAttribute('aria-label', bad ? 'Fleet, ' + bad + ' down' : warn ? 'Fleet, ' + warn + ' drifting' : 'Fleet');
  }

  function initRooms() {
    [['today', 'tab-ic-today'], ['agent', 'tab-ic-agent'], ['fleet', 'tab-ic-fleet']].forEach(function (p) {
      var el = document.getElementById(p[1]);
      el.insertBefore(ZB.icon(p[0]), el.firstChild);
    });
    var nav = document.getElementById('tabs');
    nav.addEventListener('click', function (e) {
      var b = e.target.closest && e.target.closest('button[data-tab]');
      if (b) setRoom(b.getAttribute('data-tab'));
    });
    nav.addEventListener('keydown', function (e) {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
      var i = ROOMS.indexOf(document.body.getAttribute('data-room'));
      var n = ROOMS[(i + (e.key === 'ArrowRight' ? 1 : ROOMS.length - 1)) % ROOMS.length];
      e.preventDefault();
      setRoom(n);
      nav.querySelector('[data-tab="' + n + '"]').focus();
    });
    window.addEventListener('hashchange', function () { setRoom(window.location.hash.slice(1)); });
    var want = window.location.hash.slice(1);
    setRoom(ROOMS.indexOf(want) >= 0 ? want : ZB.store.get('room') || 'today', 'init');
  }

  // ---------- boot ----------

  // once a minute, on the minute: the now line, the sun, the ages, the live clock
  ZB.tick = function () {
    if (panelState || document.querySelector('.dialog')) return;
    ZB.redraw();
    if (liveState === 'on') live('on');
  };
  function everyMinute() {
    setTimeout(function () { ZB.tick(); everyMinute(); }, 60000 - Date.now() % 60000 + 50);
  }

  function boot() {
    initRooms();
    load(true).then(connect);
    document.addEventListener('visibilitychange', function () { if (!document.hidden) load(false); });
    window.addEventListener('online', function () { load(false); connect(); });
    window.addEventListener('offline', function () { live('off'); });
    everyMinute();
  }
  // deferred module scripts run before DOMContentLoaded, so they are all registered by then
  if (document.readyState === 'complete') boot(); else document.addEventListener('DOMContentLoaded', boot);
})();
