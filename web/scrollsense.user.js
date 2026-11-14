// ==UserScript==
// @name         ScrollSense logger
// @namespace    scrollsense
// @version      0.11
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
  // The server sends at most one open card per receipt; it is shown once, closes only
  // through its options, and an answered card is never shown again on this phone.
  const CARD_CSS = `
    :host { all: initial; }
    .veil { position: fixed; inset: 0; z-index: 2147483646; display: flex; align-items: flex-end;
      justify-content: center; padding: 16px; background: rgba(20, 30, 28, 0.45);
      font: 17px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
      animation: veil-in .3s ease-out both; }
    .card { --bg: #f6faf8; --ink: #20352f; --soft: #557069; --btn: #e3efea; --btn-ink: #1f3a33;
      --accent: #2f6b5c; --accent-ink: #fff; --edge: #b9d6cb;
      width: 100%; max-width: 440px; max-height: 88vh; overflow-y: auto; box-sizing: border-box;
      background: var(--bg); color: var(--ink); border: 2px solid var(--edge);
      border-radius: 20px; padding: 22px 18px 18px; box-shadow: 0 10px 40px rgba(0,0,0,.35);
      animation: card-up .5s cubic-bezier(.2, .85, .25, 1) .05s both; }
    /* the card rises from below the bottom edge of the screen while the page dims */
    @keyframes veil-in { from { background: rgba(20, 30, 28, 0); } }
    @keyframes card-up { from { transform: translateY(calc(100% + 24px)); } }
    @media (prefers-reduced-motion: reduce) { .veil, .card { animation: none; } }
    @media (prefers-color-scheme: dark) {
      .card { --bg: #17241f; --ink: #e2efe9; --soft: #9db8ae; --btn: #23362f; --btn-ink: #e2efe9;
        --accent: #7fbfaa; --accent-ink: #10201c; --edge: #3a5c51; }
    }
    h2 { margin: 0 0 6px; font-size: 1.3rem; line-height: 1.3; }
    p { margin: 0 0 16px; color: var(--soft); }
    .options { display: grid; grid-template-columns: 1fr; gap: 8px; }
    button { all: unset; box-sizing: border-box; display: block; width: 100%; min-height: 52px;
      padding: 13px 16px; border-radius: 14px; background: var(--btn); color: var(--btn-ink);
      font: inherit; font-weight: 600; text-align: center; cursor: pointer;
      display: flex; align-items: center; justify-content: center; line-height: 1.25; }
    button:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }
`;

  function answeredIds() { return GM_getValue('answered', []); }

  function remember(id) {
    GM_setValue('answered', answeredIds().concat(id).slice(-50));
  }

  function offer(card) {
    if (showing || answeredIds().includes(card.id) || card.expires_at * 1000 <= Date.now()) return;
    showing = { card, host: document.createElement('div') };
    showing.box = cardShell(showing.host.attachShadow({ mode: 'closed' }));
    renderCard(card);
    document.documentElement.appendChild(showing.host);
    const id = card.id;
    setTimeout(() => { if (showing && showing.card.id === id) closeCard(); }, card.expires_at * 1000 - Date.now());
  }

  // Built with DOM calls, not innerHTML: YouTube enforces Trusted Types, which rejects HTML
  // strings and would make the card fail silently.
  function cardShell(root) {
    const style = Object.assign(document.createElement('style'), { textContent: CARD_CSS });
    const veil = Object.assign(document.createElement('div'), { className: 'veil' });
    const box = Object.assign(document.createElement('div'), { className: 'card' });
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-modal', 'true');
    veil.append(box);
    root.append(style, veil);
    return box;
  }

  function closeCard() {
    if (showing) showing.host.remove();
    showing = null;
  }

  function button(label, onTap) {
    const node = document.createElement('button');
    node.type = 'button';
    node.textContent = label;
    node.addEventListener('click', onTap);
    return node;
  }

  function renderCard(card) {
    const box = showing.box;
    box.replaceChildren();
    const title = document.createElement('h2');
    title.textContent = card.title;
    // All options stacked, full width and equal weight: no answer is pushed.
    const row = Object.assign(document.createElement('div'), { className: 'options' });
    card.options.forEach((option) => row.appendChild(button(option.label, () => choose(card, option))));
    box.append(title);
    if (card.message) box.append(Object.assign(document.createElement('p'), { textContent: card.message }));
    box.append(row);
  }

  function report(card, choice, then = () => {}) {
    const { endpoint, token, viewer } = config();
    GM_xmlhttpRequest({
      method: 'POST', url: `${endpoint}/api/viewers/${viewer}/nudges/${encodeURIComponent(card.id)}/response`,
      data: JSON.stringify({ choice }),
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      onload: (response) => {
        if (response.status !== 204 && response.status !== 409) toast(`ScrollSense: answer not saved (${response.status})`);
        then();
      },
      onerror: () => { toast('ScrollSense: answer not saved (server unreachable)'); then(); },
    });
  }

  // "I want to take a break": a page may not close a tab it didn't open, and browsers don't let
  // pages open the browser's home page, so pause, try to close, else switch to a blank page.
  function leaveFeed(card, option) {
    document.querySelectorAll('video').forEach((video) => video.pause());
    current = null;
    let gone = false;
    const go = () => { if (!gone) { gone = true; window.close(); location.replace('about:blank'); } };
    report(card, option.choice, go);
    setTimeout(go, 1500);
  }

  function choose(card, option) {
    remember(card.id);
    closeCard();
    if (option.action === 'leave') return leaveFeed(card, option);
    report(card, option.choice);
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
