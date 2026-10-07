// runs web/modules/agent.js against a stub board (no dom, no network): revive, archive, copy ssh, copy requests
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert');

const SRC = fs.readFileSync(path.join(__dirname, '..', '..', 'web', 'modules', 'agent.js'), 'utf8');
const RC = 'https://' + 'claude.ai/code/' + 'session_' + 'TESTONLY';
const SSH = 'ssh -t tester@127.0.0.1 /usr/bin/tmux attach -t hd-run';

function el(tag, attrs, kids) {
  const e = { tag, attrs: {}, kids: [], text: '', listeners: {}, classList: { add() {} } };
  Object.keys(attrs || {}).forEach(k => {
    const v = attrs[k];
    if (v === null || v === undefined || v === false) return;
    if (k === 'text') e.text = v;
    else if (k.slice(0, 2) === 'on') e.listeners[k.slice(2)] = v;
    else e.attrs[k] = v === true ? '' : v;
  });
  (Array.isArray(kids) ? kids : kids == null ? [] : [kids]).forEach(c => { if (c) e.kids.push(c); });
  e.appendChild = c => e.kids.push(c);
  return e;
}
function all(root, fn, out) {
  out = out || [];
  if (root && typeof root === 'object') { if (fn(root)) out.push(root); (root.kids || []).forEach(k => all(k, fn, out)); }
  return out;
}
const byKey = (root, key) => all(root, e => e.attrs && e.attrs['data-key'] === key)[0];
const texts = root => all(root, () => true).map(e => [e.text].concat(e.kids.filter(k => typeof k === 'string')).join('|')).join('|');
const tick = () => new Promise(r => setImmediate(r));

function setup(opts) {
  opts = opts || {};
  const calls = { api: [], toast: [], load: 0, redraw: 0, open: [], copy: [] };
  let copyOk = true;
  const store = {};
  const pending = [];
  const ZB = {
    modules: {}, h: el, icon: () => null,
    cfg: { agent: 'Wren', actions: { dispatch: opts.dispatch !== false } },
    agent: () => 'Wren',
    needy: q => q.status === 'prefilled' || q.status === 'copy' || q.status === 'no_session',
    smsUrl: u => u,
    tile: (name) => el('section', { class: 'tile t-' + name }),
    safeUrl: u => (typeof u === 'string' && /^https:\/\/[^\s"'<>]+$/.test(u) ? u : ''),
    ago: () => 'a while ago',
    store: { get: k => store[k], set: (k, v) => { store[k] = v; } },
    api: (m, u, b) => { calls.api.push([m, u, b]); return new Promise((res, rej) => pending.push({ res, rej })); },
    toast: (msg, action, fn) => calls.toast.push({ msg, action, fn }),
    load: () => { calls.load++; return Promise.resolve(); },
    redraw: () => { calls.redraw++; },
    confirm: () => Promise.resolve(false),
    sentButtons: id => [el('button', { 'data-key': 'sent:' + id, text: 'Sent it' }), el('button', { 'data-key': 'unsent:' + id, text: 'Didn\u2019t send' })],
    copyButton: (text, label, key) => el('button', { 'data-key': key, text: label, 'data-copy': text }),
    copy: text => { calls.copy.push(text); return copyOk ? Promise.resolve() : Promise.reject(new Error('blocked')); },
  };
  const win = { open: (u, t, f) => calls.open.push([u, t, f]), Board: ZB };
  vm.runInNewContext(SRC, { navigator: { userAgent: 'iPhone' }, window: win });
  const data = {
    running: [{ name: 'hd-run', title: 'Run', task: 'wire the marks', cwd: '~/projects/notes-site', url: RC, report: [], started: '',
      attach: SSH }, { name: 'hd-cx', title: 'Cx', task: 'codex thing', cwd: '~/projects/notes-site', url: '', report: [], started: '',
      attach: '' }],
    waiting: [{ name: 'hd-wait', title: 'Wait', task: 'needs a yes', cwd: '~/projects/notes-site', url: '', report: [], started: '',
      why: 'needs permission', attach: SSH.replace('hd-run', 'hd-wait') }],
    finished: [{ name: 'hd-old', title: 'Old', task: 'tidy the old thing', cwd: '~/projects/notes-site', url: RC, report: [], ended: '',
      attach: '' }],
    requests: opts.requests || [],
  };
  const draw = () => { const root = el('div'); ZB.modules.agent.render(root, data); return root; };
  return { ZB, calls, store, pending, draw, failCopy: () => { copyOk = false; } };
}

async function main() {
  // finished card: open and revive; running card keeps open and archive
  let t = setup();
  t.ZB.store.set('agent-seg', 'finished');
  let root = t.draw();
  let btn = byKey(root, 'revive:hd-old');
  assert.ok(btn, 'finished card has a revive button');
  assert.strictEqual(btn.text, 'Revive');
  assert.strictEqual(btn.attrs.disabled, undefined);
  assert.ok(all(root, e => e.tag === 'a' && e.attrs['aria-label'] === 'Open hd-old').length, 'open stays beside it');
  assert.ok(!byKey(root, 'archive:hd-old'), 'no archive on a finished card');
  t.ZB.store.set('agent-seg', 'running');
  root = t.draw();
  assert.ok(byKey(root, 'archive:hd-run'), 'running card keeps archive');
  assert.ok(!byKey(root, 'revive:hd-run'), 'no revive on a running card');
  assert.ok(texts(root).indexOf('Wren') >= 0, 'the room carries the agent name');

  // no dispatch command: no archive, no revive anywhere; open and copy ssh stay
  t = setup({ dispatch: false });
  root = t.draw();
  assert.ok(!byKey(root, 'archive:hd-run') && !byKey(root, 'archive:hd-wait'), 'no archive without a dispatch command');
  assert.ok(byKey(root, 'ssh:hd-run'), 'copy ssh needs no dispatch command');
  t.ZB.store.set('agent-seg', 'finished');
  root = t.draw();
  assert.ok(!byKey(root, 'revive:hd-old'), 'no revive without a dispatch command');

  // success: one request, pending while it runs, repeated clicks ignored, then running tab, toast with open, reload
  t = setup();
  t.ZB.store.set('agent-seg', 'finished');
  btn = byKey(t.draw(), 'revive:hd-old');
  btn.listeners.click();
  btn.listeners.click();
  assert.strictEqual(t.calls.api.length, 1);
  assert.strictEqual(JSON.stringify(t.calls.api[0]), JSON.stringify(['POST', '/api/sessions/revive', { name: 'hd-old' }]));
  let again = byKey(t.draw(), 'revive:hd-old');
  assert.strictEqual(again.attrs.disabled, '', 'disabled across a redraw');
  assert.strictEqual(again.text, 'Reviving');
  again.listeners.click();
  assert.strictEqual(t.calls.api.length, 1, 'a click on the redrawn button does nothing');
  t.pending[0].res({ ok: true, status: 200, data: { ok: true, message: 'resumed: tidy the old thing', url: RC } });
  await tick(); await tick();
  assert.strictEqual(t.store['agent-seg'], 'running');
  assert.strictEqual(t.calls.load, 1);
  assert.strictEqual(t.calls.toast[0].msg, 'Revived. resumed: tidy the old thing');
  assert.strictEqual(t.calls.toast[0].action, 'Open');
  t.calls.toast[0].fn();
  assert.strictEqual(JSON.stringify(t.calls.open), JSON.stringify([[RC, '_blank', 'noopener,noreferrer']]));
  t.ZB.store.set('agent-seg', 'finished');
  btn = byKey(t.draw(), 'revive:hd-old');
  assert.strictEqual(btn.text, 'Revive', 'pending clears');

  // success with no link yet: no open action, nothing made up
  t = setup();
  t.ZB.store.set('agent-seg', 'finished');
  byKey(t.draw(), 'revive:hd-old').listeners.click();
  t.pending[0].res({ ok: true, status: 200, data: { ok: true, message: 'resumed: x', url: 'javascript:alert(1)' } });
  await tick(); await tick();
  assert.strictEqual(t.calls.toast[0].action, null);

  // conflicts and failures are said as they are, and the button comes back
  for (const [status, data, want] of [
    [409, { ok: false, message: 'at the 10-session cap on hub. running: hd-a. stop one first.' },
      'Not revived: at the 10-session cap on hub. running: hd-a. stop one first..'],
    [404, { ok: false, error: 'hd-old is not an archived session' }, 'Not revived: hd-old is not an archived session.'],
    [403, { ok: false, error: 'actions are off' }, 'Not revived: actions are off.'],
    [502, { ok: false, message: 'the dispatch command did not answer in 150 s' }, 'Not revived: the dispatch command did not answer in 150 s.'],
  ]) {
    t = setup();
    t.ZB.store.set('agent-seg', 'finished');
    byKey(t.draw(), 'revive:hd-old').listeners.click();
    t.pending[0].res({ ok: false, status, data });
    await tick(); await tick();
    assert.strictEqual(t.calls.toast[0].msg, want);
    assert.strictEqual(t.store['agent-seg'], 'finished', 'a failure stays on finished');
    assert.strictEqual(t.calls.load, 1);
    assert.strictEqual(byKey(t.draw(), 'revive:hd-old').attrs.disabled, undefined);
  }

  // network failure
  t = setup();
  t.ZB.store.set('agent-seg', 'finished');
  byKey(t.draw(), 'revive:hd-old').listeners.click();
  t.pending[0].rej(new Error('offline'));
  await tick(); await tick();
  assert.strictEqual(t.calls.toast[0].msg, 'Not revived: could not reach the board.');
  assert.strictEqual(byKey(t.draw(), 'revive:hd-old').text, 'Revive');

  // copy ssh: on live cards (running, waiting, needs you) whatever the provider; never on finished ones
  t = setup();
  t.ZB.store.set('agent-seg', 'running');
  root = t.draw();
  btn = byKey(root, 'ssh:hd-run');
  assert.ok(btn, 'running card has copy ssh');
  assert.strictEqual(btn.text, 'Copy SSH');
  assert.ok(!byKey(root, 'ssh:hd-cx'), 'no command, no button');
  assert.ok(byKey(root, 'ssh:hd-wait'), 'the needs-you card has it too');
  const acts = all(root, e => e.attrs && e.attrs.class === 'acts').find(a => a.kids.indexOf(btn) >= 0);
  assert.strictEqual(acts.kids.map(k => k.text).join(','), 'Open,Copy SSH,Archive');
  btn.listeners.click();
  await tick();
  assert.strictEqual(JSON.stringify(t.calls.copy), JSON.stringify([SSH]));
  assert.strictEqual(t.calls.toast[0].msg, 'Copied. Paste it in a terminal.');
  assert.strictEqual(t.calls.api.length, 0, 'copying calls no api');
  t.failCopy();
  btn.listeners.click();
  await tick();
  assert.strictEqual(t.calls.toast[1].msg, 'Copy blocked. The command is ' + SSH);
  t.ZB.store.set('agent-seg', 'finished');
  assert.ok(!byKey(t.draw(), 'ssh:hd-old'), 'no copy ssh on a finished card');

  // a copy request needs you: its text, a copy button and the sent buttons, no messages link
  const text = 'From Daybook, Sam asks: start a Claude Code session (model opus) for "Wire the marks".';
  t = setup({ requests: [{ id: 7, title: 'Wire the marks', runner: 'claude', model: 'opus', reach: 'branch', status: 'copy',
    at: '', text, sms_url: '' }] });
  root = t.draw();
  assert.ok(byKey(root, 'sent:7') && byKey(root, 'unsent:7'), 'sent buttons on a copy request');
  assert.strictEqual(byKey(root, 'copy:7').attrs['data-copy'], text);
  assert.ok(all(root, e => e.tag === 'pre' && e.text === text).length, 'the text is on the card');
  assert.ok(!all(root, e => e.tag === 'a' && /^sms:/.test(e.attrs.href || '')).length, 'no sms link');
  assert.ok(texts(root).indexOf('send it to Wren') >= 0);
  console.log('agent actions: ok');
}

main().catch(e => { console.error(e); process.exit(1); });
