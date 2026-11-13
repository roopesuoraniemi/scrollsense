// ==UserScript==
// @name         ScrollSense logger
// @namespace    scrollsense
// @version      0.2
// @description  Sends the IDs of the YouTube Shorts you watch (and how long you stayed) to your own ScrollSense server.
// @match        https://m.youtube.com/*
// @match        https://www.youtube.com/*
// @grant        GM_xmlhttpRequest
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_registerMenuCommand
// @connect      trycloudflare.com
// @connect      *
// ==/UserScript==
(function () {
  'use strict';
  const SHORT = /^\/shorts\/([\w-]{11})/;
  const CONSENT = 'ScrollSense research prototype.\n\nWhile you watch YouTube Shorts in this browser, it sends each video ID, the time and how long you stayed to the server you choose. Nothing else (no account, comments or messages).\n\nPause anytime from the Violentmonkey menu. Agree?';
  let current = null;
  let buffer = GM_getValue('buffer', []);

  function setting(key, question) {
    let value = GM_getValue(key, '');
    if (!value) {
      value = (prompt(question) || '').trim();
      GM_setValue(key, value);
    }
    return value;
  }

  // Keep only https://host: a pasted path (e.g. /scrollsense.user.js) or http:// makes the POST
  // land on the static file server or turn into a GET after Cloudflare's redirect, both 405.
  function origin(text) {
    try {
      return new URL(/^https?:\/\//.test(text) ? text : `https://${text}`).origin.replace(/^http:/, 'https:');
    } catch (error) {
      return text;
    }
  }

  function config() {
    return {
      endpoint: origin(setting('endpoint', 'ScrollSense server URL (https://….trycloudflare.com)')),
      token: setting('token', 'ScrollSense token'),
      viewer: setting('viewer', 'Your pseudonym (e.g. patient-01)'),
    };
  }

  function reconfigure() {
    ['endpoint', 'token', 'viewer'].forEach((key) => GM_setValue(key, ''));
    config();
  }

  function toast(text) {
    const box = document.createElement('div');
    box.textContent = text;
    box.style.cssText = 'position:fixed;top:48px;left:8px;z-index:2147483647;background:#000c;color:#7f7;padding:4px 8px;border-radius:6px;font:12px monospace';
    document.body.appendChild(box);
    setTimeout(() => box.remove(), 1500);
  }

  function closeCurrent(now) {
    if (!current) return;
    const video = document.querySelector('video');
    buffer.push({
      event_id: crypto.randomUUID(), video_id: current.id, seen_at: current.started / 1000,
      tz_offset_min: -new Date().getTimezoneOffset(), dwell_s: (now - current.started) / 1000,
      duration_s: video && isFinite(video.duration) ? video.duration : null,
      source: 'shorts_web', surface: 'shorts',
    });
    GM_setValue('buffer', buffer);
  }

  function tick() {
    const match = GM_getValue('paused', false) ? null : location.pathname.match(SHORT);
    const id = match ? match[1] : null;
    if (id === (current && current.id)) return;
    const now = Date.now();
    closeCurrent(now);
    current = id ? { id, started: now } : null;
    if (id) toast(`ScrollSense ✓ ${id} (${buffer.length} waiting)`);
  }

  function onSent(response, sent) {
    if (response.status !== 202) return toast(`ScrollSense: send failed (${response.status}) → ${config().endpoint}/api/views`);
    buffer = buffer.slice(sent);
    GM_setValue('buffer', buffer);
  }

  function flush() {
    if (!buffer.length) return;
    const { endpoint, token, viewer } = config();
    const sent = buffer.length;
    GM_xmlhttpRequest({
      method: 'POST', url: `${endpoint}/api/views`, data: JSON.stringify({ viewer, events: buffer.slice(0, sent) }),
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      onload: (response) => onSent(response, sent),
      onerror: () => toast('ScrollSense: server unreachable'),
    });
  }

  function togglePause() {
    GM_setValue('paused', !GM_getValue('paused', false));
    toast(GM_getValue('paused', false) ? 'ScrollSense paused' : 'ScrollSense resumed');
  }

  if (!GM_getValue('consented', false)) {
    if (!confirm(CONSENT)) return;
    GM_setValue('consented', true);
  }
  GM_registerMenuCommand('Pause / resume', togglePause);
  GM_registerMenuCommand('Change server, token or pseudonym', reconfigure);
  config();
  setInterval(tick, 500);
  setInterval(flush, 5000);
})();
