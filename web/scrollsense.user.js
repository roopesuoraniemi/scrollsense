// ==UserScript==
// @name         ScrollSense logger
// @namespace    scrollsense
// @version      0.3.0
// @description  Streams YouTube Shorts view events (live arrival, visible dwell, duration, loops) to your ScrollSense server.
// @match        https://m.youtube.com/*
// @match        https://www.youtube.com/*
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_registerMenuCommand
// @connect      trycloudflare.com
// @connect      ts.net
// @connect      localhost
// @connect      127.0.0.1
// @connect      *
// ==/UserScript==
(function () {
  'use strict';

  const SHORT_PATH = /^\/shorts\/([\w-]{11})/;
  const PSEUDONYM = /^[a-z0-9-]{3,32}$/;
  const PAIR_PARAM = 'scrollsense_pair';
  const MAX_BUFFER = 500;
  const TICK_MS = 250;
  const RETRY_MS = 5000;
  const CONSENT = [
    'ScrollSense research prototype.',
    '',
    'While you watch YouTube Shorts in this browser, it sends only:',
    '• the public 11-character Short video ID',
    '• timestamp + timezone offset',
    '• visible watch duration, clip length, and loop count',
    'to the ScrollSense server you configure.',
    '',
    'No account names, handles, comments, searches, camera, or audio are collected.',
    'Pause or reconfigure any time from the userscript menu. Agree?',
  ].join('\n');

  let current = null;
  let buffer = loadBuffer();
  let inFlight = false;
  let flushQueued = false;

  function loadBuffer() {
    const raw = GM_getValue('buffer', []);
    return Array.isArray(raw) ? raw.slice(-MAX_BUFFER) : [];
  }

  function saveBuffer() {
    if (buffer.length > MAX_BUFFER) buffer = buffer.slice(-MAX_BUFFER);
    GM_setValue('buffer', buffer);
  }

  // Preserve http:// on loopback for local desktop testing; upgrade remote tunnels to https://.
  function normalizeOrigin(text) {
    const trimmed = String(text || '').trim();
    if (!trimmed) return '';
    try {
      const hasScheme = /^https?:\/\//i.test(trimmed);
      const isLocal = /^(https?:\/\/)?(localhost|127\.0\.0\.1|\[::1\])(?::\d+)?(\/|$)/i.test(trimmed);
      const parsed = new URL(hasScheme ? trimmed : `${isLocal ? 'http' : 'https'}://${trimmed}`);
      return isLocal ? parsed.origin : parsed.origin.replace(/^http:/i, 'https:');
    } catch {
      return trimmed;
    }
  }

  function toast(text, isError = false) {
    if (GM_getValue('quiet_hud', false) && !isError) return;
    if (!document.body) return;
    const box = document.createElement('div');
    box.textContent = text;
    box.style.cssText = [
      'position:fixed;top:52px;left:10px;z-index:2147483647;pointer-events:none',
      `background:${isError ? 'rgba(92,16,22,0.92)' : 'rgba(13,24,28,0.88)'}`,
      `color:${isError ? '#ffd4d8' : '#7ef0dc'}`,
      'border:1px solid rgba(255,255,255,0.14);padding:5px 10px;border-radius:7px',
      'font:500 12px/1.3 ui-monospace,SFMono-Regular,Menlo,monospace;box-shadow:0 4px 14px rgba(0,0,0,0.3)',
    ].join(';');
    document.body.appendChild(box);
    setTimeout(() => box.remove(), isError ? 2800 : 1400);
  }

  function decodeBase64Url(encoded) {
    const base64 = encoded.replace(/-/g, '+').replace(/_/g, '/');
    const padded = base64 + '==='.slice((base64.length + 3) % 4);
    return JSON.parse(decodeURIComponent(escape(atob(padded))));
  }

  // One-tap pairing: reads #scrollsense_pair=<base64url> once and strips it immediately from URL.
  function tryPairFromUrl() {
    const hashParams = new URLSearchParams(location.hash.replace(/^#/, ''));
    const raw = hashParams.get(PAIR_PARAM);
    if (!raw) return false;
    hashParams.delete(PAIR_PARAM);
    const restHash = hashParams.toString();
    history.replaceState(null, '', location.pathname + location.search + (restHash ? `#${restHash}` : ''));
    try {
      const payload = decodeBase64Url(raw);
      const endpoint = normalizeOrigin(payload.endpoint);
      const viewer = String(payload.viewer || '').trim().toLowerCase();
      if (!endpoint || !PSEUDONYM.test(viewer)) throw new Error('Invalid pairing link');
      if (!ensureConsent()) return false;
      GM_setValue('endpoint', endpoint);
      GM_setValue('token', String(payload.token || '').trim());
      GM_setValue('viewer', viewer);
      GM_setValue('paused', false);
      setTimeout(() => toast(`ScrollSense paired ✓ ${viewer}`), 350);
      return true;
    } catch (err) {
      setTimeout(() => toast(`ScrollSense pair error: ${err.message}`, true), 350);
      return false;
    }
  }

  function ensureConsent() {
    if (GM_getValue('consented', false)) return true;
    if (!confirm(CONSENT)) return false;
    GM_setValue('consented', true);
    return true;
  }

  function promptSetting(key, question, validate) {
    let value = String(GM_getValue(key, '') || '').trim();
    if (!value) {
      const entered = (prompt(question) || '').trim();
      value = validate ? validate(entered) : entered;
      if (value) GM_setValue(key, value);
    }
    return value;
  }

  function readConfig(interactive = false) {
    if (!interactive) {
      return {
        endpoint: normalizeOrigin(GM_getValue('endpoint', '')),
        token: String(GM_getValue('token', '') || '').trim(),
        viewer: String(GM_getValue('viewer', '') || '').trim(),
      };
    }
    const endpoint = normalizeOrigin(
      promptSetting('endpoint', 'ScrollSense server URL (e.g. https://….trycloudflare.com or http://127.0.0.1:8765)', normalizeOrigin)
    );
    const token = promptSetting('token', 'ScrollSense Bearer token (leave blank if server has none)');
    const viewer = promptSetting('viewer', 'Viewer pseudonym ([a-z0-9-]{3,32}, e.g. patient-01)', (v) => v.toLowerCase());
    return { endpoint, token, viewer };
  }

  function isConfigured(cfg) {
    return Boolean(cfg.endpoint && PSEUDONYM.test(cfg.viewer));
  }

  function reconfigure() {
    ['endpoint', 'token', 'viewer'].forEach((k) => GM_setValue(k, ''));
    const cfg = readConfig(true);
    if (isConfigured(cfg)) {
      toast(`ScrollSense → ${cfg.viewer} @ ${cfg.endpoint}`);
      flush();
    } else {
      toast('ScrollSense: valid URL and pseudonym [a-z0-9-]{3,32} required', true);
    }
  }

  // YouTube Shorts keeps multiple <video> nodes in a pool; pick the playing or most-visible one.
  function activeVideo() {
    const videos = [...document.querySelectorAll('video')];
    const playing = videos.find((v) => !v.paused && v.readyState > 0 && v.videoWidth > 0);
    if (playing) return playing;
    let best = null;
    let bestArea = 0;
    for (const v of videos) {
      const r = v.getBoundingClientRect();
      const w = Math.max(0, Math.min(r.right, innerWidth) - Math.max(r.left, 0));
      const h = Math.max(0, Math.min(r.bottom, innerHeight) - Math.max(r.top, 0));
      if (w * h > bestArea) {
        bestArea = w * h;
        best = v;
      }
    }
    return best;
  }

  function samplePlayback(now) {
    if (!current) return;
    const dt = Math.max(0, Math.min(now - current.lastTick, TICK_MS * 4));
    current.lastTick = now;
    if (document.visibilityState !== 'visible') return;
    current.dwellMs += dt;
    const video = activeVideo();
    if (!video) return;
    if (isFinite(video.duration) && video.duration > 0) {
      current.duration = Math.round(video.duration * 10) / 10;
    }
    const t = video.currentTime;
    if (!isFinite(t)) return;
    const loopGate = Math.max(2.5, (current.duration || 8) * 0.6);
    if (current.maxTime >= loopGate && t + 1.5 < current.lastTime) {
      current.loops += 1;
      current.maxTime = t;
    } else if (t > current.maxTime) {
      current.maxTime = t;
    }
    current.lastTime = t;
  }

  function closeCurrent(now) {
    if (!current) return false;
    samplePlayback(now);
    const dwellS = Math.round((current.dwellMs / 1000) * 10) / 10;
    const closed = current;
    current = null;
    if (dwellS < 0.15) return false;
    buffer.push({
      event_id: crypto.randomUUID(),
      video_id: closed.id,
      seen_at: Math.round((closed.started / 1000) * 100) / 100,
      tz_offset_min: -new Date().getTimezoneOffset(),
      dwell_s: dwellS,
      duration_s: closed.duration,
      loops: closed.loops,
      source: 'shorts_web',
      surface: 'shorts',
    });
    saveBuffer();
    return true;
  }

  function currentShortId() {
    if (GM_getValue('paused', false)) return null;
    if (document.visibilityState !== 'visible') return null;
    const match = location.pathname.match(SHORT_PATH);
    return match ? match[1] : null;
  }

  function tick() {
    const now = Date.now();
    const id = currentShortId();
    if (id && current && id === current.id) {
      samplePlayback(now);
      return;
    }
    const hadOpen = closeCurrent(now);
    if (id) {
      current = {
        id,
        started: now,
        lastTick: now,
        dwellMs: 0,
        duration: null,
        lastTime: 0,
        maxTime: 0,
        loops: 0,
      };
      toast(`ScrollSense ● ${id}`);
      flush();
    } else if (hadOpen) {
      flush({ paused: true });
    }
  }

  function buildPayload(extra = {}) {
    const watching = current
      ? {
          video_id: current.id,
          started_at: Math.round((current.started / 1000) * 100) / 100,
          tz_offset_min: -new Date().getTimezoneOffset(),
        }
      : null;
    return {
      events: buffer.slice(),
      watching,
      paused: Boolean(extra.paused || GM_getValue('paused', false) || !watching),
    };
  }

  function flush(extra = {}) {
    const cfg = readConfig(false);
    if (!isConfigured(cfg)) return;
    if (inFlight) {
      flushQueued = true;
      return;
    }
    const payload = buildPayload(extra);
    if (!payload.events.length && !payload.watching && !extra.paused) return;
    const sentIds = new Set(payload.events.map((e) => e.event_id));
    inFlight = true;
    GM_xmlhttpRequest({
      method: 'POST',
      url: `${cfg.endpoint}/api/views`,
      data: JSON.stringify({ viewer: cfg.viewer, ...payload }),
      headers: {
        'Content-Type': 'application/json',
        ...(cfg.token ? { Authorization: `Bearer ${cfg.token}` } : {}),
      },
      onload: (response) => {
        inFlight = false;
        if (response.status === 202) {
          if (sentIds.size) {
            buffer = buffer.filter((e) => !sentIds.has(e.event_id));
            saveBuffer();
          }
        } else {
          toast(`ScrollSense ${response.status} → ${cfg.endpoint}`, true);
        }
        if (flushQueued) {
          flushQueued = false;
          flush();
        }
      },
      onerror: () => {
        inFlight = false;
        toast('ScrollSense: server unreachable (buffered offline)', true);
      },
    });
  }

  function togglePause() {
    const next = !GM_getValue('paused', false);
    GM_setValue('paused', next);
    if (next) {
      closeCurrent(Date.now());
      flush({ paused: true });
    }
    toast(next ? 'ScrollSense paused' : 'ScrollSense resumed');
  }

  function toggleHud() {
    const next = !GM_getValue('quiet_hud', false);
    GM_setValue('quiet_hud', next);
    alert(next ? 'ScrollSense swipe toasts hidden (errors still show).' : 'ScrollSense swipe toasts enabled.');
  }

  const paired = tryPairFromUrl();
  if (!paired && !ensureConsent()) return;

  GM_registerMenuCommand('Pause / resume logging', togglePause);
  GM_registerMenuCommand('Change server, token or pseudonym', reconfigure);
  GM_registerMenuCommand('Toggle swipe toast HUD', toggleHud);

  if (!isConfigured(readConfig(false))) readConfig(true);

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState !== 'visible') {
      if (closeCurrent(Date.now())) flush({ paused: true });
    } else {
      tick();
    }
  });
  window.addEventListener('pagehide', () => {
    if (closeCurrent(Date.now())) flush({ paused: true });
  });

  setInterval(tick, TICK_MS);
  setInterval(() => { if (buffer.length) flush(); }, RETRY_MS);
  tick();
})();
