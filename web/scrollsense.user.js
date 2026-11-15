// ==UserScript==
// @name         ScrollSense logger
// @namespace    scrollsense
// @version      0.13
// @description  Sends the IDs of the YouTube Shorts you watch to your own ScrollSense server, and shows its occasional check-in cards.
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
  const CONSENT = 'ScrollSense research prototype.\n\nWhile you watch YouTube Shorts in this browser, it sends each video ID and the time to the server you choose. Nothing else (no account, comments or messages).\n\nPause anytime from the Violentmonkey menu. Agree?';
  let current = null;
  let buffer = GM_getValue('buffer', []);
  let showing = null;
  let lastSent = 0;
  let sending = false;
  const HEARTBEAT_MS = 2000;

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

  // A view is logged and sent the moment a Short opens, so the server analyses it while it plays
  // (no dwell time: waiting for the swipe would delay the analysis and any check-in card).
  function logView(id, now) {
    buffer.push({
      event_id: crypto.randomUUID(), video_id: id, seen_at: now / 1000,
      tz_offset_min: -new Date().getTimezoneOffset(), source: 'shorts_web', surface: 'shorts',
    });
    GM_setValue('buffer', buffer);
  }

  function tick() {
    const match = GM_getValue('paused', false) ? null : location.pathname.match(SHORT);
    const id = match ? match[1] : null;
    if (id === (current && current.id)) return;
    current = id ? { id } : null;
    if (!id) return;
    logView(id, Date.now());
    flush();
    toast(`ScrollSense ✓ ${id}`);
  }

  function onSent(response, sent) {
    if (response.status !== 202) return toast(`ScrollSense: send failed (${response.status}) → ${config().endpoint}/api/views`);
    buffer = buffer.slice(sent);
    GM_setValue('buffer', buffer);
    let receipt = null;
    try { receipt = JSON.parse(response.responseText); } catch (error) { return; }
    if (!receipt || !receipt.nudge) return;
    try {
      offer(receipt.nudge);
    } catch (error) {  // never fail silently: a missing card is invisible otherwise
      if (showing) showing.host.remove();
      showing = null;
      toast(`ScrollSense: check-in card failed (${error.message})`);
    }
  }

  // ---- Check-in cards ("nudges"): research prototype, not a medical device. ----
  // Same card as the web demo (web/demo), which is the master: it slides up from the bottom while
  // the page dims and pauses the video while open. "Take a break" shows a calm screen that stays
  // until the page is reloaded (no way back into the feed from the card itself). The server sends at most one open card per receipt; it is shown once,
  // closes only through its options, and an answered card is never shown again on this phone.
  const FONT = '15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';
  const CARD_CSS = `
    :host { all: initial; }
    .veil { position: fixed; inset: 0; z-index: 2147483646; display: flex; align-items: flex-end;
      justify-content: center; padding: 12px; background: rgba(20, 30, 28, .5); font: ${FONT};
      animation: veil-in .3s ease-out both; }
    .nudge { box-sizing: border-box; width: 100%; max-width: 440px; background: #f6faf8; color: #20352f;
      border: 2px solid #b9d6cb; border-radius: 18px; padding: 18px 14px 14px;
      box-shadow: 0 10px 40px rgba(0, 0, 0, .35); animation: card-up .5s cubic-bezier(.2, .85, .25, 1) .05s both; }
    @keyframes veil-in { from { background: rgba(20, 30, 28, 0); } }
    @keyframes card-up { from { transform: translateY(calc(100% + 16px)); } }
    h2 { margin: 0 0 4px; font-size: 18px; line-height: 1.3; }
    p { margin: 0 0 12px; color: #557069; font-size: 14px; }
    .opts { display: grid; grid-template-columns: 1fr; gap: 6px; }
    .nudge button { all: unset; box-sizing: border-box; display: flex; align-items: center; justify-content: center;
      min-height: 48px; padding: 8px 6px; border-radius: 12px; background: #e3efea; color: #1f3a33;
      font-weight: 700; font-size: 13px; line-height: 1.2; text-align: center; cursor: pointer; }
    button:focus-visible { outline: 3px solid #2f6b5c; outline-offset: 2px; }
    .gone { position: fixed; inset: 0; z-index: 2147483646; display: flex; flex-direction: column;
      align-items: center; justify-content: center; gap: 12px; padding: 24px; text-align: center;
      background: #f6faf8; color: #20352f; font: ${FONT}; }
    .gone b { font-size: 18px; }
    .gone span { font-size: 14px; color: #557069; }
    @media (prefers-reduced-motion: reduce) { .veil, .nudge { animation: none; } }
`;

  function answeredIds() { return GM_getValue('answered', []); }

  function remember(id) {
    GM_setValue('answered', answeredIds().concat(id).slice(-50));
  }

  function pauseVideos() { document.querySelectorAll('video').forEach((video) => video.pause()); }

  function resumeVideo() {
    const video = document.querySelector('video');
    if (video) video.play().catch(() => {});   // the tap on the card counts as the user gesture
  }

  // Built with DOM calls, not innerHTML: YouTube enforces Trusted Types, which rejects HTML
  // strings and would make the card fail silently.
  function el(tag, props = {}, children = []) {
    const node = Object.assign(document.createElement(tag), props);
    node.append(...children);
    return node;
  }

  function show(id, layer) {
    const host = document.createElement('div');
    host.attachShadow({ mode: 'closed' }).append(el('style', { textContent: CARD_CSS }), layer);
    document.documentElement.appendChild(host);
    showing = { id, host };
  }

  function closeCard() {
    if (showing) showing.host.remove();
    showing = null;
  }

  function button(label, onTap) {
    const node = el('button', { type: 'button', textContent: label });
    node.addEventListener('click', onTap);
    return node;
  }

  function offer(card) {
    if (showing || answeredIds().includes(card.id) || card.expires_at * 1000 <= Date.now()) return;
    pauseVideos();
    // All options stacked, full width and equal weight: no answer is pushed.
    const opts = el('div', { className: 'opts' }, card.options.map((o) => button(o.label, () => choose(card, o))));
    const parts = [el('h2', { textContent: card.title }), ...(card.message ? [el('p', { textContent: card.message })] : []), opts];
    const box = el('div', { className: 'nudge' }, parts);
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-modal', 'true');
    show(card.id, el('div', { className: 'veil' }, [box]));
    setTimeout(() => { if (showing && showing.id === card.id) { closeCard(); resumeVideo(); } },
      card.expires_at * 1000 - Date.now());
  }

  function report(card, choice) {
    const { endpoint, token, viewer } = config();
    GM_xmlhttpRequest({
      method: 'POST', url: `${endpoint}/api/viewers/${viewer}/nudges/${encodeURIComponent(card.id)}/response`,
      data: JSON.stringify({ choice }),
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      onload: (response) => {
        if (response.status !== 204 && response.status !== 409) toast(`ScrollSense: answer not saved (${response.status})`);
      },
      onerror: () => toast('ScrollSense: answer not saved (server unreachable)'),
    });
  }

  // "I want to take a break": the feed stays paused behind a calm full screen. There is no button
  // back into the feed; reloading YouTube ends the break.
  function takeBreak() {
    pauseVideos();
    show('break', el('div', { className: 'gone' }, [el('b', { textContent: 'The feed is closed' }),
      el('span', { textContent: 'Enjoy the break.' })]));
  }

  function choose(card, option) {
    remember(card.id);
    closeCard();
    report(card, option.choice);
    if (option.action === 'leave') return takeBreak();
    resumeVideo();
  }

  // An empty batch is a heartbeat: an analysis finishes a few seconds after the Short opens, so a
  // card that becomes due then still arrives (in the receipt) within HEARTBEAT_MS.
  function heartbeatDue() {
    return !showing && !GM_getValue('paused', false) && document.visibilityState === 'visible'
      && SHORT.test(location.pathname) && Date.now() - lastSent >= HEARTBEAT_MS;
  }

  // One request at a time: onSent drops the first `sent` events, which must be the ones it sent.
  function flush() {
    if (sending || (!buffer.length && !heartbeatDue())) return;
    const { endpoint, token, viewer } = config();
    const sent = buffer.length;
    sending = true;
    lastSent = Date.now();
    GM_xmlhttpRequest({
      method: 'POST', url: `${endpoint}/api/views`, data: JSON.stringify({ viewer, events: buffer.slice(0, sent) }),
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      timeout: 15000,
      onload: (response) => { sending = false; onSent(response, sent); },
      onerror: () => { sending = false; if (sent) toast('ScrollSense: server unreachable'); },
      ontimeout: () => { sending = false; },
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
  setInterval(flush, 1000);
})();
