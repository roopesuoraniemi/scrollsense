"""Runtime behavioural tests for `web/scrollsense.user.js` executed in Node's `vm` sandbox."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
USERSCRIPT = ROOT / "web" / "scrollsense.user.js"

NODE_HARNESS = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const crypto = require('node:crypto');

const code = fs.readFileSync(process.argv[2], 'utf8');

function encodePair(obj) {
  const utf8 = unescape(encodeURIComponent(JSON.stringify(obj)));
  return Buffer.from(utf8, 'binary').toString('base64')
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

let fakeNow = 1_763_100_000_000;
const gmStore = {};
const menuCommands = {};
const requests = [];
const listeners = { visibilitychange: [], pagehide: [] };
const intervals = [];

const pairToken = encodePair({
  endpoint: 'http://tunnel-demo.trycloudflare.com/scrollsense.user.js',
  token: 'tok-secret-1',
  viewer: 'patient-01',
});

const locationObj = {
  pathname: '/shorts/Qo4PLQXRmUw',
  search: '',
  hash: `#scrollsense_pair=${pairToken}`,
};

let visibility = 'visible';
let domLinks = [];
let videos = [
  // Idle preloaded video first in DOM (classic YouTube Shorts pool trap)
  { paused: true, readyState: 0, videoWidth: 0, duration: NaN, currentTime: 0,
    getBoundingClientRect: () => ({ left: 0, top: -800, right: 360, bottom: -100 }) },
  // Active visible playing Short second in DOM
  { paused: false, readyState: 4, videoWidth: 480, duration: 14.0, currentTime: 0.5,
    getBoundingClientRect: () => ({ left: 0, top: 0, right: 360, bottom: 640 }) },
];

const sandbox = {
  Date: class extends Date {
    constructor(...args) { super(...(args.length ? args : [fakeNow])); }
    static now() { return fakeNow; }
    getTimezoneOffset() { return -120; }
  },
  crypto: { randomUUID: () => crypto.randomUUID() },
  atob: (s) => Buffer.from(s, 'base64').toString('binary'),
  btoa: (s) => Buffer.from(s, 'binary').toString('base64'),
  escape,
  unescape,
  encodeURIComponent,
  decodeURIComponent,
  isFinite,
  URL,
  URLSearchParams,
  innerWidth: 390,
  innerHeight: 844,
  location: locationObj,
  history: {
    replaceState: (_s, _t, url) => {
      const hashIdx = url.indexOf('#');
      locationObj.hash = hashIdx >= 0 ? url.slice(hashIdx) : '';
    },
  },
  confirm: () => true,
  prompt: () => '',
  alert: () => {},
  setTimeout: () => 1,
  setInterval: (fn, ms) => { intervals.push({ fn, ms }); return intervals.length; },
  document: {
    get visibilityState() { return visibility; },
    body: { appendChild: () => {} },
    createElement: () => ({ style: {}, remove: () => {} }),
    querySelectorAll: (sel) => (sel === 'video' ? videos : domLinks),
    addEventListener: (ev, fn) => { (listeners[ev] = listeners[ev] || []).push(fn); },
  },
  window: {
    addEventListener: (ev, fn) => { (listeners[ev] = listeners[ev] || []).push(fn); },
  },
  GM_getValue: (k, def) => (k in gmStore ? gmStore[k] : def),
  GM_setValue: (k, v) => { gmStore[k] = JSON.parse(JSON.stringify(v)); },
  GM_registerMenuCommand: (name, fn) => { menuCommands[name] = fn; },
  GM_xmlhttpRequest: (req) => { requests.push(req); },
};

vm.runInNewContext(code, sandbox);
const tickFn = intervals.find((i) => i.ms === 250).fn;

// 1. Pairing link parsed, upgraded to https origin without path, and scrubbed from location.hash
if (locationObj.hash !== '') throw new Error(`Hash not scrubbed: ${locationObj.hash}`);
if (gmStore.endpoint !== 'https://tunnel-demo.trycloudflare.com') {
  throw new Error(`Unexpected endpoint: ${gmStore.endpoint}`);
}
if (gmStore.viewer !== 'patient-01' || gmStore.token !== 'tok-secret-1') {
  throw new Error('Pairing credentials not stored');
}

// 2. Immediate live watching request fired on initial Short before swiping away
if (requests.length !== 1) throw new Error(`Expected 1 initial request, got ${requests.length}`);
const req1Body = JSON.parse(requests[0].data);
if (!req1Body.watching || req1Body.watching.video_id !== 'Qo4PLQXRmUw' || req1Body.events.length !== 0) {
  throw new Error(`Bad initial live payload: ${requests[0].data}`);
}
// Keep req1 in-flight while user watches, loops once, and swipes!

// 3. Visible playback + 1 loop wrap-around (4 * 250ms = 1.0s visible)
const activeVid = videos[1];
const progress = [4.0, 9.5, 13.2, 0.4, 10.5]; // wraps once (13.2 -> 0.4), then reaches 10.5s (>= 60%) before swipe
for (const pos of progress) {
  fakeNow += 250;
  activeVid.currentTime = pos;
  tickFn();
}

// 4. Swipe to Short 2 while req1 is STILL in flight: Short 2's <video> has duration=28s and currentTime=0.1s
// Must NOT falsely increment Short 1's loops to 2 or overwrite Short 1's duration to 28s!
fakeNow += 250;
locationObj.pathname = '/shorts/lMQJ2bHeP4c';
activeVid.duration = 28.0;
activeVid.currentTime = 0.1;
tickFn();
// Because req1 is still inFlight, no overlapping second XHR was launched yet
if (requests.length !== 1) throw new Error('inFlight mutex violated');

// Complete req1 now -> queued flush must immediately send Short 1 + live Short 2 without losing Short 1!
requests[0].onload({ status: 202 });
if (requests.length !== 2) throw new Error(`Expected queued flush #2, got ${requests.length}`);
const req2Body = JSON.parse(requests[1].data);
if (req2Body.events.length !== 1 || req2Body.events[0].video_id !== 'Qo4PLQXRmUw') {
  throw new Error(`Short 1 lost under concurrent flush: ${requests[1].data}`);
}
if (req2Body.events[0].loops !== 1 || req2Body.events[0].duration_s !== 14) {
  throw new Error(`Loop/duration corrupted by next video on swipe: ${JSON.stringify(req2Body.events[0])}`);
}
if (req2Body.watching?.video_id !== 'lMQJ2bHeP4c') {
  throw new Error(`Expected watching Short 2: ${requests[1].data}`);
}
requests[1].onload({ status: 202 });

// 5. Watch Short 2 for 2.0s visible (reaching 18s of 28s = 64%, 0 loops), then lock phone for 60s
for (let i = 0; i < 8; i += 1) {
  fakeNow += 250;
  activeVid.currentTime = 2.0 + i * 2.0;
  tickFn();
}
visibility = 'hidden';
listeners.visibilitychange.forEach((fn) => fn());
fakeNow += 60_000; // 60 seconds with locked screen must NOT count!

if (requests.length !== 3) throw new Error(`Expected visibility hide flush #3, got ${requests.length}`);
const req3Body = JSON.parse(requests[2].data);
if (req3Body.events.length !== 1 || Math.abs(req3Body.events[0].dwell_s - 2.0) > 0.15 || req3Body.events[0].loops !== 0) {
  throw new Error(`Hidden screen time or false loop leaked: ${JSON.stringify(req3Body)}`);
}
if (req3Body.paused !== true || req3Body.watching !== null) {
  throw new Error(`Expected paused=true on hide: ${JSON.stringify(req3Body)}`);
}
// Simulate timeout on req3 while another navigation happens via DOM fallback on /shorts
visibility = 'visible';
locationObj.pathname = '/shorts';
domLinks = [{ href: 'https://m.youtube.com/shorts/bPnRMwahAMA', getAttribute: () => '/shorts/bPnRMwahAMA' }];
fakeNow += 250;
tickFn(); // Queues flush while req3 is inFlight
requests[2].ontimeout(); // Timeout must clear inFlight and trigger queued flush #4!
if (requests.length !== 4) throw new Error(`Expected timeout recovery flush #4, got ${requests.length}`);
const req4Body = JSON.parse(requests[3].data);
if (req4Body.watching?.video_id !== 'bPnRMwahAMA' || req4Body.events.length !== 1) {
  throw new Error(`DOM fallback or buffered event missing after timeout: ${requests[3].data}`);
}
requests[3].onload({ status: 202 });

console.log(JSON.stringify({ ok: true, requests: requests.length, bufferRemaining: gmStore.buffer.length }));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node runtime not installed")
def test_userscript_pairing_live_arrival_loops_visibility_and_concurrency(tmp_path: Path) -> None:
    harness = tmp_path / "run_userscript_test.cjs"
    harness.write_text(NODE_HARNESS, encoding="utf-8")
    proc = subprocess.run(["node", str(harness), str(USERSCRIPT)],
                          capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"STDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
    summary = json.loads(proc.stdout.strip())
    assert summary == {"ok": True, "requests": 4, "bufferRemaining": 0}


CHROME_CDP_RUNNER = r"""
const { spawn } = require('node:child_process');

const baseUrl = process.argv[2];
const chromeBin = process.argv[3];
const profileDir = process.argv[4];

async function run() {
  const chrome = spawn(chromeBin, [
    '--headless=new',
    '--no-sandbox',
    '--disable-gpu',
    '--disable-dev-shm-usage',
    '--remote-debugging-port=0',
    `--user-data-dir=${profileDir}`,
    'about:blank',
  ]);

  const wsUrl = await new Promise((resolve, reject) => {
    let stderr = '';
    const timer = setTimeout(() => reject(new Error(`Chrome startup timeout: ${stderr}`)), 10000);
    chrome.stderr.on('data', (chunk) => {
      stderr += chunk.toString();
      const m = stderr.match(/DevTools listening on (ws:\/\/[^\s]+)/);
      if (m) {
        clearTimeout(timer);
        resolve(m[1]);
      }
    });
    chrome.on('exit', (code) => reject(new Error(`Chrome exited early (${code}): ${stderr}`)));
  });

  const debugBase = wsUrl.replace(/^ws:\/\/([^/]+)\/.*$/, 'http://$1');
  const targets = await fetch(`${debugBase}/json/list`).then((r) => r.json());
  const pageTarget = targets.find((t) => t.type === 'page');
  const ws = new WebSocket(pageTarget.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });

  let nextId = 1;
  const pending = new Map();
  const pageErrors = [];
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.method === 'Runtime.exceptionThrown') {
      pageErrors.push(msg.params.exceptionDetails.text || 'Runtime exception');
    }
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) reject(new Error(msg.error.message));
      else resolve(msg.result);
    }
  };

  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = nextId++;
    pending.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params }));
  });

  const evaluate = async (expression) => {
    const res = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (res.exceptionDetails) {
      throw new Error(`Eval error: ${JSON.stringify(res.exceptionDetails)}`);
    }
    return res.result.value;
  };

  try {
    await send('Page.enable');
    await send('Runtime.enable');
    await send('Page.navigate', { url: baseUrl });

    // Wait for init() to connect and render Mock mode badge
    for (let i = 0; i < 60; i += 1) {
      const modeText = await evaluate(`document.getElementById('mode')?.textContent || ''`);
      if (modeText.includes('Mock mode')) break;
      await new Promise((r) => setTimeout(r, 100));
    }

    // 1. Click "Sample feed" and wait for all seeded clips to score
    await evaluate(`document.getElementById('btnSeed').click()`);
    let uiState = null;
    for (let i = 0; i < 80; i += 1) {
      uiState = await evaluate(`({
        status: document.getElementById('status')?.textContent || '',
        pills: document.querySelectorAll('#list .clip-pill.scored').length,
        hasDriftArrow: Boolean(document.querySelector('#map #driftArrow')),
        pkgTitle: document.querySelector('#pkg')?.textContent || '',
        dsmRows: document.querySelectorAll('#dsm .dsm-row').length,
      })`);
      if (uiState.pills >= 9 && uiState.dsmRows === 9 && uiState.hasDriftArrow) break;
      await new Promise((r) => setTimeout(r, 100));
    }
    if (!uiState || uiState.pills < 9 || !uiState.hasDriftArrow || uiState.dsmRows !== 9) {
      throw new Error(`Inspector UI incomplete: ${JSON.stringify(uiState)}`);
    }

    // 2. Toggle to Semantic 2-D PCA map and confirm drift arrow & points render
    await evaluate(`document.getElementById('tSem').click()`);
    const semState = await evaluate(`({
      dots: document.querySelectorAll('#map g[data-id]').length,
      hasDriftArrow: Boolean(document.querySelector('#map #driftArrow')),
      note: document.getElementById('mapnote')?.textContent || '',
    })`);
    if (semState.dots < 9 || !semState.hasDriftArrow || !semState.note.includes('dispersion')) {
      throw new Error(`Semantic PCA map incomplete: ${JSON.stringify(semState)}`);
    }

    // 3. Switch to "Drift & home loop" tab and click flagged semantic_dispersion row
    await evaluate(`document.getElementById('tabLoop').click()`);
    await evaluate(`document.querySelector('tr.flagged-row[data-metric="semantic_dispersion"]')?.click()`);
    const loopState = await evaluate(`({
      clusters: document.querySelectorAll('#clusterStrip .cluster-card').length,
      flaggedRows: document.querySelectorAll('#metricsTable tr.flagged-row').length,
      nightFlagged: Boolean(document.querySelector('tr.flagged-row[data-metric="night_share"]')),
      resets: document.querySelectorAll('#loopPanel .reset-card').length,
      trajPaths: document.querySelectorAll('#trajChart path').length,
      filteredEvidenceCards: document.querySelectorAll('#evidenceList .ev-card').length,
    })`);
    if (
      loopState.clusters !== 3 ||
      loopState.flaggedRows < 6 ||
      !loopState.nightFlagged ||
      loopState.resets < 3 ||
      loopState.trajPaths < 3 ||
      loopState.filteredEvidenceCards < 3
    ) {
      throw new Error(`Loop tab or evidence filter failed: ${JSON.stringify(loopState)}`);
    }

    // 4. Open Pair Phone modal and verify one-tap link generation
    await evaluate(`document.getElementById('btnPair').click()`);
    const pairLink = await evaluate(`document.getElementById('pairLink')?.value || ''`);
    if (!pairLink.startsWith('https://m.youtube.com/shorts#scrollsense_pair=')) {
      throw new Error(`Bad pairLink: ${pairLink}`);
    }
    await evaluate(`document.getElementById('pairModal').close()`);

    // 5. Log mockA9safet clip and verify deterministic global safety banner activates
    await evaluate(`
      const inp = document.getElementById('urlInput');
      inp.value = 'mockA9safet';
      document.getElementById('urlForm').dispatchEvent(new Event('submit', { cancelable: true }));
    `);
    let safetyVisible = false;
    let safetyText = '';
    for (let i = 0; i < 60; i += 1) {
      const s = await evaluate(`({
        hidden: document.getElementById('safetyGlobal').classList.contains('hidden'),
        text: document.getElementById('safetyGlobal').textContent || '',
      })`);
      if (!s.hidden && s.text.includes('09 2525 0111') && s.text.includes('988')) {
        safetyVisible = true;
        safetyText = s.text;
        break;
      }
      await new Promise((r) => setTimeout(r, 100));
    }
    if (!safetyVisible) {
      throw new Error(`Global A9 safety banner did not activate: ${safetyText}`);
    }
    if (pageErrors.length) {
      throw new Error(`Page runtime exceptions: ${pageErrors.join('; ')}`);
    }

    console.log(JSON.stringify({ ok: true, pills: uiState.pills, flaggedRows: loopState.flaggedRows, filteredEvidence: loopState.filteredEvidenceCards }));
  } finally {
    ws.close();
    chrome.kill('SIGKILL');
  }
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
"""


@pytest.mark.skipif(
    shutil.which("node") is None or shutil.which("google-chrome") is None,
    reason="node or google-chrome not installed",
)
def test_webapp_ui_end_to_end_in_headless_chrome(tmp_path: Path) -> None:
    import socket
    from threading import Thread
    import uvicorn
    from scrollsense.composition import QueueConfig, Settings
    from scrollsense.gemini import GeminiConfig
    from scrollsense.server import create_app

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    settings = Settings(
        mock=True,
        gemini=GeminiConfig(model="gemini-4-hydrogen", embed_model="gemini-embedding-2"),
        data_dir=tmp_path / "clips",
        views_dir=tmp_path / "views",
        token=None,
        queue=QueueConfig(workers=4, rpm=0.0),
    )
    app = create_app(settings)
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = Thread(target=server.run, daemon=True)
    thread.start()
    try:
        runner = tmp_path / "chrome_e2e.cjs"
        runner.write_text(CHROME_CDP_RUNNER, encoding="utf-8")
        proc = subprocess.run(
            ["node", str(runner), f"http://127.0.0.1:{port}", str(shutil.which("google-chrome")), str(tmp_path / "chrome-profile")],
            capture_output=True, text=True, check=False, timeout=25,
        )
        assert proc.returncode == 0, f"STDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
        result = json.loads(proc.stdout.strip().splitlines()[-1])
        assert result["ok"] is True
        assert result["pills"] >= 9 and result["filteredEvidence"] >= 3
    finally:
        server.should_exit = True
        thread.join(timeout=3.0)
