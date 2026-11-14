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
    querySelectorAll: (sel) => (sel === 'video' ? videos : []),
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
const progress = [4.0, 9.5, 13.2, 0.4]; // wraps from 13.2 -> 0.4 => 1 loop
for (const pos of progress) {
  fakeNow += 250;
  activeVid.currentTime = pos;
  tickFn();
}

// 4. Swipe to Short 2 while req1 is STILL in flight (concurrency race check!)
fakeNow += 250; // total visible dwell on Short 1 = 1.25s -> rounded 1.3s
locationObj.pathname = '/shorts/lMQJ2bHeP4c';
activeVid.currentTime = 0.2;
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
  throw new Error(`Loop/duration mismatch: ${JSON.stringify(req2Body.events[0])}`);
}
if (req2Body.watching?.video_id !== 'lMQJ2bHeP4c') {
  throw new Error(`Expected watching Short 2: ${requests[1].data}`);
}
requests[1].onload({ status: 202 });

// 5. Watch Short 2 for 2.0s visible, then lock phone (visibilityState = 'hidden') for 60s
for (let i = 0; i < 8; i += 1) {
  fakeNow += 250;
  activeVid.currentTime = 1.0 + i * 0.25;
  tickFn();
}
visibility = 'hidden';
listeners.visibilitychange.forEach((fn) => fn());
fakeNow += 60_000; // 60 seconds with locked screen must NOT count!

if (requests.length !== 3) throw new Error(`Expected visibility hide flush #3, got ${requests.length}`);
const req3Body = JSON.parse(requests[2].data);
if (req3Body.events.length !== 1 || Math.abs(req3Body.events[0].dwell_s - 2.0) > 0.15) {
  throw new Error(`Hidden screen time leaked into dwell: ${JSON.stringify(req3Body)}`);
}
if (req3Body.paused !== true || req3Body.watching !== null) {
  throw new Error(`Expected paused=true on hide: ${JSON.stringify(req3Body)}`);
}
requests[2].onload({ status: 202 });

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
    assert summary == {"ok": True, "requests": 3, "bufferRemaining": 0}
