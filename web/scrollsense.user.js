// ==UserScript==
// @name         ScrollSense logger
// @namespace    scrollsense
// @version      0.7
// @description  Sends the IDs of the YouTube Shorts you watch (and how long you stayed) to your own ScrollSense server, and shows its occasional check-in cards.
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
  let showing = null;

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
      font: 17px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
    .card { --bg: #f6faf8; --ink: #20352f; --soft: #557069; --btn: #e3efea; --btn-ink: #1f3a33;
      --accent: #2f6b5c; --accent-ink: #fff; --edge: #b9d6cb;
      width: 100%; max-width: 440px; max-height: 88vh; overflow-y: auto; box-sizing: border-box;
      background: var(--bg); color: var(--ink); border: 2px solid var(--edge);
      border-radius: 20px; padding: 22px 18px 18px; box-shadow: 0 10px 40px rgba(0,0,0,.35); }
    @media (prefers-color-scheme: dark) {
      .card { --bg: #17241f; --ink: #e2efe9; --soft: #9db8ae; --btn: #23362f; --btn-ink: #e2efe9;
        --accent: #7fbfaa; --accent-ink: #10201c; --edge: #3a5c51; }
    }
    h2 { margin: 0 0 6px; font-size: 1.3rem; line-height: 1.3; }
    p { margin: 0 0 16px; color: var(--soft); }
    .options { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
    button { all: unset; box-sizing: border-box; display: block; width: 100%; min-height: 52px;
      padding: 13px 16px; border-radius: 14px; background: var(--btn); color: var(--btn-ink);
      font: inherit; font-weight: 600; text-align: center; cursor: pointer;
      display: flex; align-items: center; justify-content: center; line-height: 1.25; }
    button.primary { background: var(--accent); color: var(--accent-ink); }
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

  function button(label, primary, onTap) {
    const node = document.createElement('button');
    node.type = 'button';
    node.textContent = label;
    if (primary) node.className = 'primary';
    node.addEventListener('click', onTap);
    return node;
  }

  function renderCard(card) {
    const box = showing.box;
    box.replaceChildren();
    const title = document.createElement('h2');
    title.textContent = card.title;
    // All options side by side, equal width and equal weight: no answer is pushed.
    const row = Object.assign(document.createElement('div'), { className: 'options' });
    card.options.forEach((option) => row.appendChild(button(option.label, false, () => choose(card, option))));
    box.append(title);
    if (card.message) box.append(Object.assign(document.createElement('p'), { textContent: card.message }));
    box.append(row);
  }

  function showText(text) {
    const box = showing.box;
    box.replaceChildren();
    const body = document.createElement('p');
    body.textContent = text;
    box.append(body, button('OK', true, closeCard));
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
    closeCurrent(Date.now());
    current = null;
    flush();
    let gone = false;
    const go = () => { if (!gone) { gone = true; window.close(); location.replace('about:blank'); } };
    report(card, option.choice, go);
    setTimeout(go, 1500);
  }

  // Act inside the tap itself: a new tab or a dialler opened after the POST returns would no
  // longer count as a user gesture and gets blocked. The token never goes into a URL.
  function choose(card, option) {
    remember(card.id);
    if (option.action === 'leave') {
      closeCard();
      return leaveFeed(card, option);
    }
    report(card, option.choice);
    if (option.action === 'open') window.open(`${config().endpoint}/${option.href}`, '_blank', 'noopener');
    if (option.action === 'call') {
      const link = document.createElement('a');
      link.href = option.href;
      link.click();
    }
    if (option.action === 'message') return showText(option.text);
    closeCard();
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
