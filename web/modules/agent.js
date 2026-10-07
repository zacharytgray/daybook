// the agent: what needs you (sessions waiting on you, requests to confirm), then the sessions
// behind a running / waiting / finished switch, and what the board asked the agent for lately
(function () {
  'use strict';
  var ZB = window.Board, h = ZB.h, I = ZB.icon;
  var DOT = { sent: 'warn', prefilled: 'warn', copy: 'warn', not_sent: 'idle', started: 'running', waiting: 'waiting',
    done: 'finished', failed: 'bad', no_session: 'bad' };
  var SEGS = [['running', 'Running'], ['waiting', 'Waiting'], ['finished', 'Finished']];
  var showAll = false;

  function who() { return ZB.agent(); }
  function runner(r) { return { claude: 'Claude Code', codex: 'Codex', agent: who() }[r] || r; }
  function status(s) {
    return { sent: 'Sent to ' + who(), prefilled: 'Opened in Messages', copy: 'Ready to copy', not_sent: 'Not sent',
      started: 'Running', waiting: 'Waiting on you', done: 'Done', failed: 'Failed', no_session: 'No session started' }[s] || s;
  }
  function needy(r) { return ZB.needy(r); }
  function name(s) { return s.title || s.task || s.name; }
  function actions() { return !!(ZB.cfg.actions && ZB.cfg.actions.dispatch); }

  function open(url, label, cls) {
    url = ZB.safeUrl(url);
    return url ? h('a', { class: 'btn ' + (cls || ''), href: url, target: '_blank', rel: 'noopener noreferrer', 'aria-label': 'Open ' + label,
      text: 'Open' }) : null;
  }

  // the ssh line that opens the session's tmux from any machine; the server builds it from the device registry
  function sshBtn(s) {
    if (!s.attach) return null;
    var b = h('button', { type: 'button', class: 'btn ghost', 'data-key': 'ssh:' + s.name, title: s.attach,
      'aria-label': 'Copy the SSH command for ' + s.name, text: 'Copy SSH', onclick: function () {
        ZB.copy(s.attach).then(function () { ZB.toast('Copied. Paste it in a terminal.'); },
          function () { ZB.toast('Copy blocked. The command is ' + s.attach); });
      } });
    return b;
  }

  // archive asks first in a page dialog, then the dispatch command stops the session; its report is kept.
  // only drawn when a dispatch command is set
  function archive(s, btn) {
    ZB.confirm({ title: 'Archive \u201c' + name(s) + '\u201d?', body: 'The session stops. Its report is kept and it can be revived.',
      ok: 'Archive' }).then(function (yes) {
      if (!yes) return;
      btn.disabled = true;
      btn.textContent = 'Archiving';
      ZB.api('POST', '/api/sessions/archive', { name: s.name }).then(function (res) {
        var d = res.data || {};
        ZB.toast(res.ok ? 'Archived. ' + (d.message || '') : 'Not archived: ' + (d.message || d.error || 'no answer') + '.');
        ZB.load(false);
      }, function () {
        ZB.toast('Not archived: could not reach the board.');
      }).then(function () { btn.disabled = false; btn.textContent = 'Archive'; });
    });
  }
  function archiveBtn(s) {
    if (!actions()) return null;
    var b = h('button', { type: 'button', class: 'btn ghost', 'data-key': 'archive:' + s.name, 'aria-haspopup': 'dialog',
      'aria-label': 'Archive ' + s.name, text: 'Archive', onclick: function () { archive(s, b); } });
    return b;
  }

  // revive reopens an archived session in its own conversation, same handle and folder. the dispatch does the checks.
  // pending names live outside the card, so a redraw mid-request keeps the button disabled
  var reviving = {};
  function revive(s) {
    if (reviving[s.name]) return;
    reviving[s.name] = true;
    ZB.redraw();
    ZB.api('POST', '/api/sessions/revive', { name: s.name }).then(function (res) {
      var d = res.data || {}, url = res.ok && ZB.safeUrl(d.url);
      if (res.ok) {
        ZB.store.set('agent-seg', 'running');
        ZB.toast('Revived. ' + (d.message || ''), url ? 'Open' : null, url ? function () {
          window.open(url, '_blank', 'noopener,noreferrer');
        } : null);
      } else {
        ZB.toast('Not revived: ' + (d.message || d.error || 'no answer') + '.');
      }
    }, function () {
      ZB.toast('Not revived: could not reach the board.');
    }).then(function () { delete reviving[s.name]; ZB.redraw(); return ZB.load(false); });
  }
  function reviveBtn(s) {
    if (!actions()) return null;
    var busy = !!reviving[s.name];
    return h('button', { type: 'button', class: 'btn ghost', 'data-key': 'revive:' + s.name, disabled: busy,
      'aria-busy': busy ? 'true' : 'false', 'aria-label': 'Revive ' + s.name, text: busy ? 'Reviving' : 'Revive',
      onclick: function () { revive(s); } });
  }

  function report(s) {
    if (s.report && s.report.length) return h('div', { class: 'report' }, h('p', { class: 'clamp2', text: s.report.join(' ') }));
    return h('p', { class: 'report empty', text: s.report_hidden ? 'Report hidden.' : 'No report yet.' });
  }
  function whereLine(s) {
    return h('p', { class: 'where' }, [I('folder'), h('span', { class: 'mono path', text: s.cwd || 'no folder' }),
      s.model ? h('span', { class: 'chip', text: s.model }) : null]);
  }

  // ---------- needs you ----------

  function waitingCard(s) {
    return h('article', { class: 'need' }, [
      h('div', { class: 'need-top' }, [h('span', { class: 'tag warn' }, [h('span', { class: 'sdot waiting', 'aria-hidden': 'true' }), cap(s.why)]),
        h('span', { class: 'mono muted', text: 'started ' + ZB.ago(s.started) })]),
      h('h3', { class: 'need-title', text: name(s) }),
      h('p', { class: 'mono need-name', text: s.name }),
      whereLine(s),
      report(s),
      h('div', { class: 'acts' }, [open(s.url, s.name, 'primary'), sshBtn(s), archiveBtn(s)].filter(Boolean))]);
  }

  function requestCard(r) {
    var sms = ZB.smsUrl(r.sms_url || '');
    var chips = [runner(r.runner), r.model && r.model !== 'default' ? r.model : '', r.reach].filter(Boolean);
    var line = r.status === 'no_session' ? 'No session started. Ask ' + who() + ' to check.'
      : r.status === 'copy' ? 'Not sent yet. Copy it, send it to ' + who() + ', then say if you did.'
        : 'Opened in Messages. Did you send it?';
    var acts = ZB.sentButtons(r.id, function () {});
    if (sms) acts.push(h('a', { class: 'btn text', href: sms }, [r.status === 'no_session' ? 'Ask ' + who() : 'Open Messages', I('out')]));
    else if (r.text) acts.push(ZB.copyButton(r.text, 'Copy', 'copy:' + r.id));
    return h('article', { class: 'need' }, [
      h('div', { class: 'need-top' }, [h('span', { class: 'tag accent', text: 'From the board' }), h('span', { class: 'mono muted', text: ZB.ago(r.at) })]),
      h('h3', { class: 'need-title', text: r.title }),
      h('p', { class: 'chips' }, chips.map(function (c) { return h('span', { class: 'chip', text: c }); })),
      h('p', { class: 'asks' }, [I('msg'), line]),
      r.status === 'copy' && r.text ? h('pre', { class: 'need-text', text: r.text }) : null,
      r.error ? h('p', { class: 'muted small', text: r.error }) : null,
      h('div', { class: 'acts even' }, acts)]);
  }

  function cap(s) { s = String(s || ''); return s.charAt(0).toUpperCase() + s.slice(1); }

  function needsTile(d) {
    var reqs = d.requests.filter(needy), n = d.waiting.length + reqs.length;
    var sec = ZB.tile('needs', ['Needs you', n ? h('span', { class: 'count', text: String(n) }) : null], { room: 'agent' });
    if (!n) {
      sec.classList.add('is-empty');
      sec.appendChild(h('div', { class: 'calm' }, [h('p', { class: 'calm-1', text: 'Nothing needs you.' }),
        h('p', { class: 'muted', text: d.running.length ? who() + ' has ' + d.running.length + ' running.' : 'Nothing is running.' })]));
      return sec;
    }
    var list = h('div', { class: 'needs' });
    d.waiting.forEach(function (s) { list.appendChild(waitingCard(s)); });
    reqs.forEach(function (r) { list.appendChild(requestCard(r)); });
    sec.appendChild(list);
    return sec;
  }

  // ---------- sessions ----------

  function sessionCard(s, kind) {
    var when = kind === 'finished' ? 'finished ' + ZB.ago(s.ended) : 'started ' + ZB.ago(s.started);
    var acts = [open(s.url, s.name, 'soft')];
    if (kind !== 'finished') acts.push(sshBtn(s));
    acts.push(kind === 'finished' ? reviveBtn(s) : archiveBtn(s));
    acts = acts.filter(Boolean);
    return h('article', { class: 'sess' }, [
      h('div', { class: 'sess-top' }, [h('span', { class: 'sdot ' + kind, 'aria-hidden': 'true' }), h('span', { class: 'mono strong sess-name', text: s.name }),
        h('span', { class: 'mono muted sess-ago', text: when })]),
      h('h4', { class: 'sess-title', text: name(s) }),
      s.task && s.task !== s.title ? h('p', { class: 'sess-task', title: s.task, text: s.task }) : null,
      kind === 'waiting' && s.why ? h('p', { class: 'small warn-t', text: cap(s.why) }) : null,
      whereLine(s),
      report(s),
      acts.length ? h('div', { class: 'acts' }, acts) : null]);
  }

  function seg(d) {
    var cur = ZB.store.get('agent-seg');
    if (!SEGS.some(function (x) { return x[0] === cur; })) cur = d.running.length || !d.waiting.length ? 'running' : 'waiting';  // needs you already shows the waiting ones
    return cur;
  }

  function requestRow(r) {
    var word = r.runner === 'agent' && r.status === 'sent' ? 'Sent to ' + who() + ' to handle directly.' : status(r.status);
    var meta = [runner(r.runner) + (r.model && r.model !== 'default' ? ', ' + r.model : ''), r.reach, ZB.ago(r.at)];
    var url = ZB.safeUrl(r.url);
    return h('li', { class: 'asked' }, [h('span', { class: 'sdot ' + (DOT[r.status] || 'idle'), 'aria-hidden': 'true' }),
      h('div', { class: 'asked-b' }, [h('p', { class: 'asked-t', text: r.title }),
        h('p', { class: 'muted small' }, [h('b', { text: word }), ' · ' + meta.join(' · '),
          r.session ? h('span', {}, [' · ', h('span', { class: 'mono', text: r.session })]) : null]),
        r.error ? h('p', { class: 'muted small', text: r.error }) : null]),
      url ? h('a', { class: 'btn soft', href: url, target: '_blank', rel: 'noopener noreferrer', 'aria-label': 'Open ' + (r.session || r.title),
        text: 'Open' }) : null]);
  }

  function agentTile(d) {
    var sec = ZB.tile('agent', [I('spark', 'head-ic'), who()], { room: 'agent', aside: 'Sessions' });
    var asked = d.requests.filter(function (r) { return !needy(r); }).slice(0, 4);
    if (asked.length) {
      sec.appendChild(h('h3', { class: 'label sub', text: 'Asked from the board' }));
      sec.appendChild(h('ul', { class: 'asked-list' }, asked.map(requestRow)));
    }
    var cur = seg(d), lists = { running: d.running, waiting: d.waiting, finished: d.finished };
    var bar = h('div', { class: 'seg seg-btns', role: 'group', 'aria-label': 'Sessions' });
    SEGS.forEach(function (x) {
      var n = lists[x[0]].length;
      bar.appendChild(h('button', { type: 'button', 'aria-pressed': x[0] === cur ? 'true' : 'false', 'data-key': 'seg:' + x[0],
        onclick: function () { ZB.store.set('agent-seg', x[0]); showAll = false; ZB.redraw(); } }, [
        x[0] === 'running' && n ? h('span', { class: 'sdot running', 'aria-hidden': 'true' }) : null, x[1] + ' ',
        x[0] === 'waiting' && n ? h('span', { class: 'count', text: String(n) }) : h('span', { class: 'n', text: String(n) })]));
    });
    sec.appendChild(bar);
    var list = lists[cur], limit = cur === 'finished' && !showAll ? 4 : list.length;
    if (!list.length) {
      sec.appendChild(h('p', { class: 'quiet', text: d.sessions_on === false ? 'No sessions folder is set.' :
        { running: 'Nothing running. Hand ' + who() + ' a to-do.', waiting: 'Nothing is waiting on you.',
          finished: 'Nothing finished in the last day and a half.' }[cur] }));
    }
    list.slice(0, limit).forEach(function (s) { sec.appendChild(sessionCard(s, cur)); });
    if (cur === 'finished' && list.length > 4) {
      sec.appendChild(h('button', { type: 'button', class: 'btn more', 'data-key': 'agent-more', 'aria-expanded': showAll ? 'true' : 'false',
        onclick: function () { showAll = !showAll; ZB.redraw(); } }, [showAll ? 'Show fewer' : 'Show ' + (list.length - 4) + ' more',
        I('chev', showAll ? 'up' : '')]));
    }
    return sec;
  }

  function render(el, d) {
    var parts = [d.running.length + ' running', d.waiting.length ? d.waiting.length + ' waiting on you' : '',
      d.finished.length + ' finished'].filter(Boolean);
    el.appendChild(h('div', { class: 'room-head', 'data-room': 'agent' }, [h('p', { class: 'room-title', text: who() }),
      h('p', { class: 'room-sub', text: parts.join(', ') + '.' })]));
    el.appendChild(needsTile(d));
    el.appendChild(agentTile(d));
  }

  ZB.modules.agent = { render: render };
})();
