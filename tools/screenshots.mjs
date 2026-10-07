// real screenshots of the demo pages through headless chrome's devtools protocol.
// node 22+ (global fetch and WebSocket), chrome or chromium, nothing to install.
//   node tools/screenshots.mjs [--board http://127.0.0.1:8740] [--brief http://127.0.0.1:8735] [--out docs/screenshots]
// start the demo first: python3 bin/daybook demo --fresh
import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync, writeFileSync, existsSync, mkdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const arg = (k, d) => { const i = process.argv.indexOf(k); return i > 0 ? process.argv[i + 1] : d; };
const BOARD = arg('--board', 'http://127.0.0.1:8740');
const BRIEF = arg('--brief', 'http://127.0.0.1:8735') + '/2026-04-14/';
const OUT = arg('--out', 'docs/screenshots');
const ONLY = arg('--only', '');

const CHROMES = [process.env.DAYBOOK_CHROME, '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/Applications/Chromium.app/Contents/MacOS/Chromium', '/usr/bin/google-chrome', '/usr/bin/chromium',
  '/usr/bin/chromium-browser'].filter(Boolean);
const chrome = CHROMES.find(existsSync);
if (!chrome) { console.error('no chrome found; set DAYBOOK_CHROME'); process.exit(1); }

const DESK = { width: 1440, height: 1000, mobile: false, scale: 1 };
const PHONE = { width: 390, height: 844, mobile: true, scale: 2 };
// name, url, device, scheme, full page, a script to run after load
const SHOTS = [
  ['board-desktop-light', BOARD + '/#today', DESK, 'light', true],
  ['board-desktop-dark', BOARD + '/#today', DESK, 'dark', true],
  ['board-phone-today-light', BOARD + '/#today', PHONE, 'light', false],
  ['board-phone-today-dark', BOARD + '/#today', PHONE, 'dark', false],
  ['board-phone-agent-light', BOARD + '/#agent', PHONE, 'light', false],
  ['board-phone-agent-dark', BOARD + '/#agent', PHONE, 'dark', false],
  ['board-phone-fleet-light', BOARD + '/#fleet', PHONE, 'light', false],
  ['board-phone-fleet-dark', BOARD + '/#fleet', PHONE, 'dark', false],
  ['board-panel-desktop', BOARD + '/#today', DESK, 'light', false,
    "(document.querySelector('.f-acts button, [data-handoff], .rk-btn') || {click(){}}).click()"],
  ['brief-desktop-light', BRIEF, DESK, 'light', false],
  ['brief-desktop-dark', BRIEF, DESK, 'dark', false],
  ['brief-desktop-full', BRIEF, DESK, 'light', true],
  ['brief-phone-light', BRIEF, PHONE, 'light', false],
  ['brief-phone-dark', BRIEF, PHONE, 'dark', false],
];

const prof = mkdtempSync(join(tmpdir(), 'daybook-shots-'));
const proc = spawn(chrome, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
  '--hide-scrollbars', '--disable-background-networking', '--disable-component-update', '--disable-sync',
  '--disable-default-apps', '--no-pings', '--metrics-recording-only', '--remote-debugging-port=0', `--user-data-dir=${prof}`, 'about:blank'], { stdio: 'ignore' });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let port;
for (let i = 0; i < 100 && !port; i++) {
  try { port = readFileSync(join(prof, 'DevToolsActivePort'), 'utf8').split('\n')[0]; } catch { await sleep(100); }
}
if (!port) { console.error('chrome did not open a debugging port'); proc.kill('SIGKILL'); process.exit(1); }

const target = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: 'PUT' })).json();
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener('open', r, { once: true }));
let seq = 0;
const waiting = new Map();
const events = [];
ws.addEventListener('message', (m) => {
  const d = JSON.parse(m.data);
  if (d.id && waiting.has(d.id)) { waiting.get(d.id)(d); waiting.delete(d.id); } else if (d.method) events.push(d.method);
});
const send = (method, params = {}) => new Promise((res, rej) => {
  const id = ++seq;
  waiting.set(id, (d) => (d.error ? rej(new Error(`${method}: ${d.error.message}`)) : res(d.result)));
  ws.send(JSON.stringify({ id, method, params }));
});

await send('Page.enable');
mkdirSync(OUT, { recursive: true });
for (const [name, url, dev, scheme, full, script] of SHOTS) {
  if (ONLY && !name.includes(ONLY)) continue;
  await send('Emulation.setDeviceMetricsOverride', { width: dev.width, height: dev.height, deviceScaleFactor: dev.scale, mobile: dev.mobile });
  await send('Emulation.setEmulatedMedia', { media: 'screen', features: [{ name: 'prefers-color-scheme', value: scheme }] });
  await send('Emulation.setTouchEmulationEnabled', { enabled: dev.mobile });
  events.length = 0;
  await send('Page.navigate', { url: 'about:blank' });
  await sleep(200);
  await send('Page.navigate', { url });
  for (let i = 0; i < 100 && !events.includes('Page.loadEventFired'); i++) await sleep(100);
  await sleep(2000);  // the board draws after its first /api/state
  if (script) { await send('Runtime.evaluate', { expression: script }); await sleep(800); }
  if (full) {
    // grow the viewport to the whole page, so fixed bars sit at the real bottom instead of mid-page
    const m = await send('Page.getLayoutMetrics');
    const h = Math.min(Math.ceil((m.cssContentSize || m.contentSize).height), 12000);
    await send('Emulation.setDeviceMetricsOverride', { width: dev.width, height: h, deviceScaleFactor: dev.scale, mobile: dev.mobile });
    await sleep(600);
  }
  const shot = await send('Page.captureScreenshot', { format: 'png' });
  writeFileSync(join(OUT, `${name}.png`), Buffer.from(shot.data, 'base64'));
  console.log(`${name}.png`);
}
ws.close();
proc.kill('SIGKILL');
await sleep(300);
rmSync(prof, { recursive: true, force: true });
