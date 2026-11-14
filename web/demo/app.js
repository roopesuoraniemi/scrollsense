'use strict';

// ScrollSense web demo: a phone that scrolls a scripted Shorts feed (plus pasted Shorts), the
// same pipeline as the real phone (each Short shown is a view event), and the clinician's view.

const $ = (id) => document.getElementById(id);
const POLL_MS = 2000;
const HEARTBEAT_MS = 2000;   // an empty view batch, so a card that becomes due arrives within 2 s
const SWIPE_PX = 40;
const WHEEL_LOCK_MS = 650;
const DEFAULT_COOLDOWN_S = 900;
const state = {
  meta: null, viewer: null, script: [], playlist: [], at: -1, feed: [], clips: [], drift: null,
  nudges: [], cooldown: null, current: null, signature: '', card: null, answered: new Set(), onBreak: false,
  muted: true, paused: false, lastPost: 0, wheelUntil: 0, pointer: null,
};

function esc(text) {
  return String(text ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

const hhmm = (seconds) => new Date(seconds * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
const mmss = (seconds) => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;

// ---------------------------------------------------------------- token and demo viewer

// Open the page once with ?token=...; it is kept in localStorage and removed from the address bar.
const TOKEN = initialToken();

function initialToken() {
  const params = new URLSearchParams(location.search);
  const fromUrl = params.get('token');
  if (fromUrl !== null) {
    params.delete('token');
    const query = params.toString();
    history.replaceState(null, '', location.pathname + (query ? `?${query}` : '') + location.hash);
  }
  try {
    if (fromUrl) localStorage.setItem('scrollsense.token', fromUrl);
    return fromUrl || localStorage.getItem('scrollsense.token') || '';
  } catch {
    return fromUrl || '';
  }
}

// Every browser gets its own pseudonymous demo viewer, so visitors never share a feed.
// ?viewer=demo-... pins one (for a presenter or a screenshot).
function demoViewer() {
  const pinned = new URLSearchParams(location.search).get('viewer');
  if (/^demo-[a-z0-9-]{1,27}$/.test(pinned ?? '')) return pinned;
  const fresh = `demo-${crypto.randomUUID().slice(0, 8)}`;
  try {
    const kept = localStorage.getItem('scrollsense.demo.viewer');
    if (kept) return kept;
    localStorage.setItem('scrollsense.demo.viewer', fresh);
  } catch { /* the viewer then lasts for this page load only */ }
  return fresh;
}

async function api(path, options = {}) {
  const headers = { ...(TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {}), ...(options.body ? { 'Content-Type': 'application/json' } : {}) };
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || response.statusText);
  return response.status === 204 ? null : response.json();
}

function setStatus(text, isError = false) {
  $('status').textContent = text;
  $('status').className = isError ? 'err' : '';
}

async function init() {
  state.viewer = demoViewer();
  [state.meta, state.script] = await Promise.all([api('/api/meta'), fetch('demo-feed.json').then((r) => r.json())]);
  renderMode();
  renderHistory();
  state.playlist = [...state.script];
  show(0);
  setInterval(() => tick().catch((error) => setStatus(error.message, true)), POLL_MS);
  setInterval(onSecond, 1000);
}

function renderMode() {
  const { analyser } = state.meta;
  const name = analyser.mock ? 'Mock mode, no API calls' : analyser.name;
  $('mode').textContent = state.meta.live ? `${name}, live inference` : name;
  $('mode').classList.toggle('mock', analyser.mock);
}

// ---------------------------------------------------------------- the phone

function show(index) {
  if (index < 0 || index >= state.playlist.length || state.card || state.onBreak) return;
  state.at = index;
  state.paused = false;
  renderPlayer();
  renderPhoneChrome();
  postViews([viewEvent(state.playlist[index].id)]);
  tick().catch(() => {});
}

const step = (delta) => show(state.at + delta);

let playerDuration = 0, looping = false;

function renderPlayer() {
  const { id } = state.playlist[state.at];
  const query = `enablejsapi=1&rel=0&playsinline=1&autoplay=1&mute=1&controls=0&disablekb=1&fs=0&iv_load_policy=3&origin=${encodeURIComponent(location.origin)}`;
  playerDuration = 0;
  looping = false;
  $('screen').style.backgroundImage = `url('https://i.ytimg.com/vi/${id}/hqdefault.jpg')`;
  $('player').classList.add('loading');
  $('player').innerHTML = `<iframe src="https://www.youtube.com/embed/${id}?${query}" title="Short ${state.at + 1}" tabindex="-1" allow="autoplay; encrypted-media"></iframe>`;
  const frame = $('player').querySelector('iframe');
  frame.addEventListener('load', () => {
    [0, 250, 600].forEach((ms) => setTimeout(() => listenToPlayer(frame), ms));
    setTimeout(() => { if ($('player').contains(frame)) $('player').classList.remove('loading'); }, 800);
    if (!state.muted) [700, 1500].forEach((ms) => setTimeout(() => command('unMute'), ms));
  });
}

function listenToPlayer(frame) {
  if (!$('player').contains(frame)) return;
  frame.contentWindow?.postMessage(JSON.stringify({ event: 'listening', id: 1, channel: 'widget' }), '*');
}

function onPlayerMessage(event) {
  if (!String(event.origin).includes('youtube')) return;
  const frame = $('player').querySelector('iframe');
  if (!frame || event.source !== frame.contentWindow) return;
  let data;
  try { data = typeof event.data === 'string' ? JSON.parse(event.data) : event.data; } catch { return; }
  const info = data?.info;
  if (!info || typeof info !== 'object') return;
  if (typeof info.duration === 'number' && info.duration > 0) playerDuration = info.duration;
  if (info.playerState === 1) {
    $('player').classList.remove('loading');
    if (state.paused) command('pauseVideo');
  }
  if (typeof info.currentTime === 'number' && playerDuration > 0.6) {
    if (info.currentTime >= playerDuration - 0.3 && !looping) {
      looping = true;
      command('seekTo', [0, true]);
      if (!state.paused) command('playVideo');
    } else if (info.currentTime < playerDuration - 0.5) {
      looping = false;
    }
  }
  if (info.playerState === 0 && !state.paused) {
    command('seekTo', [0, true]);
    command('playVideo');
  }
}

function renderPhoneChrome() {
  $('pos').textContent = `${state.at + 1}/${state.playlist.length}`;
  $('up').disabled = state.at <= 0;
  $('down').disabled = state.at >= state.playlist.length - 1;
  $('screen').classList.toggle('paused', state.paused && !state.onBreak);
  $('paused').classList.toggle('on', state.paused && !state.card && !state.onBreak);
  $('sound').textContent = state.muted ? '\u{1F507}' : '\u{1F50A}';
  $('sound').setAttribute('aria-pressed', String(!state.muted));
}

// The embedded player takes commands by postMessage (enablejsapi=1).
function command(func, args = []) {
  const frame = $('player').querySelector('iframe');
  frame?.contentWindow.postMessage(JSON.stringify({ event: 'command', func, args, id: 1, channel: 'widget' }), '*');
}

function setPaused(paused) {
  state.paused = paused;
  command(paused ? 'pauseVideo' : 'playVideo');
  renderPhoneChrome();
}

function toggleSound() {
  state.muted = !state.muted;
  command(state.muted ? 'mute' : 'unMute');
  renderPhoneChrome();
}

function onWheel(event) {
  event.preventDefault();
  if (Math.abs(event.deltaY) < 8 || Date.now() < state.wheelUntil) return;
  state.wheelUntil = Date.now() + WHEEL_LOCK_MS;
  step(event.deltaY > 0 ? 1 : -1);
}

// One pointer handler for mouse and touch: a vertical drag is a swipe, anything else a tap.
function onPointerUp(event) {
  if (state.pointer == null) return;
  const dy = event.clientY - state.pointer;
  state.pointer = null;
  if (Math.abs(dy) >= SWIPE_PX) return step(dy < 0 ? 1 : -1);
  setPaused(!state.paused);
}

// ---------------------------------------------------------------- views and check-in cards

function viewEvent(videoId) {
  return {
    event_id: crypto.randomUUID(), video_id: videoId, seen_at: Date.now() / 1000,
    tz_offset_min: -new Date().getTimezoneOffset(), source: 'shorts_web', surface: 'shorts',
  };
}

async function postViews(events) {
  state.lastPost = Date.now();
  try {
    const receipt = await api('/api/views', { method: 'POST', body: JSON.stringify({ viewer: state.viewer, events }) });
    if (receipt?.nudge) offer(receipt.nudge);
  } catch (error) {
    setStatus(`Could not send the view: ${error.message}`, true);
  }
}

function onSecond() {
  if (state.card && state.card.expires_at * 1000 <= Date.now()) {
    state.card = null;
    $('overlay').innerHTML = '';
    setPaused(false);
    renderMap();
  }
  if (state.cooldown && !state.cooldown.done && Date.now() >= state.cooldown.untilMs) {
    state.cooldown.done = true;
    state.lastPost = 0;
  }
  renderTrendText();
  heartbeat();
}

function heartbeat() {
  const due = Date.now() - state.lastPost >= HEARTBEAT_MS;
  if (due && !state.card && !state.onBreak && state.at >= 0 && document.visibilityState === 'visible') postViews([]);
}

function offer(card) {
  if (state.card || state.onBreak || state.answered.has(card.id) || card.expires_at * 1000 <= Date.now()) return;
  state.card = card;
  setPaused(true);
  $('overlay').innerHTML = `<div class="veil"><div class="nudge" role="dialog" aria-modal="true" aria-labelledby="nudge-title">
    <h2 id="nudge-title">${esc(card.title)}</h2>${card.message ? `<p>${esc(card.message)}</p>` : ''}
    <div class="opts">${card.options.map((o, i) => `<button type="button" data-i="${i}">${esc(o.label)}</button>`).join('')}</div></div></div>`;
  $('overlay').querySelectorAll('[data-i]').forEach((b) => { b.onclick = () => choose(card.options[Number(b.dataset.i)]); });
  $('overlay').querySelector('button').focus();
  renderTrendText();
  renderMap();
}

async function choose(option) {
  const card = state.card;
  state.answered.add(card.id);
  state.card = null;
  $('overlay').innerHTML = '';
  if (option.action === 'leave') {
    takeBreak();
  } else {
    state.cooldown = { id: card.id, untilMs: Date.now() + DEFAULT_COOLDOWN_S * 1000, synced: false, done: false };
    setPaused(false);
    renderTrendText();
  }
  await api(`/api/viewers/${state.viewer}/nudges/${encodeURIComponent(card.id)}/response`,
    { method: 'POST', body: JSON.stringify({ choice: option.choice }) }).catch((error) => setStatus(`Answer not saved: ${error.message}`, true));
  tick().catch(() => {});
}

// "I want to take a break": on the phone the feed closes; here the screen goes blank.
function takeBreak() {
  state.onBreak = true;
  setPaused(true);
  $('player').innerHTML = '';
  $('screen').style.backgroundImage = 'none';
  $('overlay').innerHTML = `<div class="gone"><b>The feed is closed</b><span>On the phone, YouTube closes here. Enjoy the break.</span>
    <button type="button" id="gone-continue">Continue scrolling</button></div>`;
  $('gone-continue').onclick = continueScrolling;
}

// Back from the break: the same Short plays again (no new view is logged).
function continueScrolling() {
  state.onBreak = false;
  state.paused = false;
  $('overlay').innerHTML = '';
  renderPlayer();
  renderPhoneChrome();
  renderTrendText();
}

// ---------------------------------------------------------------- tabs: whose view the right side shows

function selectTab(tab) {
  document.querySelectorAll('[role="tab"]').forEach((t) => {
    const on = t === tab;
    t.setAttribute('aria-selected', String(on));
    t.tabIndex = on ? 0 : -1;
    $(t.getAttribute('aria-controls')).hidden = !on;
  });
  tab.focus();
}

function onTabKey(event) {
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  const next = tabs[(tabs.indexOf(event.target) + (event.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
  selectTab(next);
}

async function reset() {
  await api(`/api/viewers/${state.viewer}`, { method: 'DELETE' }).catch((error) => setStatus(error.message, true));
  Object.assign(state, {
    playlist: [...state.script], feed: [], clips: [], drift: null, nudges: [], cooldown: null,
    current: null, signature: '', card: null, onBreak: false,
  });
  state.answered.clear();
  resetArrow();
  $('overlay').innerHTML = '';
  addMessage('');
  show(0);
}

// ---------------------------------------------------------------- add a Short

async function addShort(event) {
  event.preventDefault();
  const url = $('add-url').value.trim();
  try {
    const added = await api('/api/demo/shorts', { method: 'POST', body: JSON.stringify({ viewer: state.viewer, url }) });
    state.playlist.splice(state.at + 1, 0, { id: added.video_id, title: null, added: true });
    $('add-url').value = '';
    addMessage(state.meta.live || added.state !== 'scored' ? 'Added as the next Short. Gemini starts watching it when it plays.' : 'Added as the next Short (already analysed).');
    renderPhoneChrome();
  } catch (error) {
    addMessage(error.message, true);
  }
}

function addMessage(text, isError = false) {
  $('add-msg').textContent = text;
  $('add-msg').className = isError ? 'err' : '';
}

// ---------------------------------------------------------------- clinician view

async function tick() {
  const viewer = state.viewer;
  const [feed, drift, nudges] = await Promise.all([
    api(`/api/viewers/${viewer}/feed?limit=200`),
    api(`/api/viewers/${viewer}/drift`).catch(() => null),
    api(`/api/viewers/${viewer}/nudges`).catch(() => []),
  ]);
  state.feed = feed;
  renderSignals(drift, nudges);
  await refreshClips();
  await refreshCurrent();
  renderMap();
}

async function refreshClips() {
  const signature = state.feed.map((item) => item.event.event_id + item.state).join('|');
  if (signature === state.signature) return;
  state.signature = signature;
  const scored = new Set(state.feed.filter((item) => item.state === 'scored').map((item) => item.event.video_id));
  state.clips = (await api('/api/clips')).filter((clip) => scored.has(clip.id));
  const seen = new Set(state.feed.map((item) => item.event.video_id)).size;
  const running = new Set(state.feed.filter((item) => item.state === 'queued').map((item) => item.event.video_id)).size;
  setStatus(`${seen} Shorts watched, ${scored.size} analysed${running ? `, ${running} being analysed` : ''}`);
}

// The text package appears only once this viewer's analysis of the Short is done: in live
// inference a stored result from an earlier run stays hidden while Gemini watches it again.
async function refreshCurrent() {
  const id = state.playlist[state.at]?.id;
  const item = state.feed.find((entry) => entry.event.video_id === id);
  if (!id || (state.current?.id === id && state.current.package && item?.state === 'scored')) return;
  state.current = item?.state === 'scored' ? await api(`/api/clips/${id}`).catch(() => ({ id })) : { id };
  if (state.current.package) renderPackage();
  renderWaiting();
}

// Until this viewer's analysis of the Short is done, the text panel says so; the phone stays clean.
function renderWaiting() {
  const id = state.playlist[state.at]?.id;
  if (!id || state.current?.id !== id || state.current.package) return;
  const item = state.feed.find((entry) => entry.event.video_id === id);
  const html = item?.state === 'failed' ? `<div class="empty">${esc(`Analysis failed: ${item.error}`)}</div>`
    : '<div class="empty analyzing" role="status">Analyzing</div>';
  if ($('pkg').innerHTML !== html) $('pkg').innerHTML = html;
}

const LEVEL_CLASS = { learning: 'quiet', normal: 'quiet', watch: 'watch', warning: 'warning' };
const LEVEL_TITLE = { normal: 'Normal range', watch: 'Watch', warning: 'Warning' };
const LEVEL_STROKE = { learning: 'var(--faint)', normal: 'var(--mut)', watch: 'var(--watch)', warning: 'var(--warn)' };

function renderSignals(drift, nudges) {
  state.drift = drift;
  state.nudges = nudges;
  syncCooldown(nudges);
  $('trend').className = `panel ${LEVEL_CLASS[drift?.level] ?? 'quiet'}`;
  const status = drift ? trendStatus(drift, nudges[0]) : 'No drift report yet';
  $('trend').innerHTML = `<div class="what"><b>Trend: drift towards low mood</b><span id="trend-status">${esc(status)}</span></div>${drift ? sparkline(drift, nudges) : ''}`;
  $('nudges').innerHTML = nudges.length ? nudges.map((n) => nudgeRow(n, drift)).join('') : `<div class="none">None yet. A check-in is sent when the drift passes the ${drift?.config.warn ?? 1} SD alarm.</div>`;
  $('tab-badge').hidden = !nudges.length;
  $('tab-badge').textContent = `${nudges.length} check-in${nudges.length === 1 ? '' : 's'}`;
}

function syncCooldown(nudges) {
  const latest = nudges[0];
  if (!latest || latest.cooldown_remaining_s <= 0) { state.cooldown = null; return; }
  if (state.cooldown?.id === latest.nudge.id && state.cooldown.synced) return;
  state.cooldown = { id: latest.nudge.id, untilMs: Date.now() + latest.cooldown_remaining_s * 1000, synced: true, done: false };
}

function cooldownSeconds() {
  if (!state.cooldown || state.onBreak) return 0;
  return Math.max(0, Math.ceil((state.cooldown.untilMs - Date.now()) / 1000));
}

function renderTrendText() {
  const node = $('trend-status');
  if (node && state.drift) node.textContent = trendStatus(state.drift, state.nudges[0]);
}

// One line that ties the drift to its consequence: past the alarm line, a check-in goes out.
function trendStatus(d, latest) {
  const n = d.recent.n;
  if (d.level === 'learning') return `Collecting Shorts: ${n} of ${Math.ceil(d.config.window / 2)} analysed`;
  const wait = cooldownSeconds();
  if (d.level !== 'warning') return `${LEVEL_TITLE[d.level]}, last ${n} Shorts${wait ? ` · check-in cooldown ${mmss(wait)}` : ''}`;
  if (wait) return latest ? `Warning: check-in sent ${hhmm(latest.nudge.created_at)} · cooldown ${mmss(wait)}` : `Warning: check-in cooldown ${mmss(wait)}`;
  if (state.card || latest?.state === 'open' || (state.onBreak && latest)) {
    const at = latest ? latest.nudge.created_at : Date.now() / 1000;
    return `Warning: check-in sent ${hhmm(at)}`;
  }
  return 'Warning: check-in on its way';
}

// Drift after each judged Short, the alarm line, and a dotted mark where each check-in was sent.
function sparkline(d, nudges) {
  const points = d.timeline.slice(-40);
  if (points.length < 2) return '<div></div>';
  const W = 400, H = 46, P = 5;
  const top = Math.max(d.config.warn * 2, ...points.map((p) => p.score));
  const x = (i) => P + i / (points.length - 1) * (W - 2 * P);
  const y = (v) => H - P - Math.min(v, top) / top * (H - 2 * P);
  const line = points.map((p, i) => `${x(i).toFixed(1)},${y(p.score).toFixed(1)}`).join(' ');
  const stroke = LEVEL_STROKE[d.level];
  const last = { x: x(points.length - 1), y: y(points[points.length - 1].score) };
  const marks = nudges.map((n) => points.findLastIndex((p) => p.seen_at <= n.nudge.created_at)).filter((i) => i >= 0)
    .map((i) => `<line x1="${x(i)}" x2="${x(i)}" y1="${P}" y2="${H - P}" stroke="var(--warn)" stroke-dasharray="2 3" vector-effect="non-scaling-stroke"><title>Check-in sent</title></line>`).join('');
  return `<div class="spark"><span class="lbl" style="top:${(y(d.config.warn) / H * 100).toFixed(0)}%">${d.config.warn} SD alarm</span><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Drift per Short; the dashed line is the ${d.config.warn} SD alarm; dotted lines mark check-ins">
    <line x1="${P}" x2="${W - P}" y1="${y(d.config.warn)}" y2="${y(d.config.warn)}" stroke="${stroke}" stroke-dasharray="5 4" opacity=".55" vector-effect="non-scaling-stroke"/>${marks}
    <polyline points="${line}" fill="none" stroke="${stroke}" stroke-width="2" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>
    <line x1="${last.x}" y1="${last.y}" x2="${last.x}" y2="${last.y}" stroke="${stroke}" stroke-width="7" stroke-linecap="round" vector-effect="non-scaling-stroke"/></svg></div>`;
}

// ---------------------------------------------------------------- example history (clinician tab)

// Illustrative only: one invented patient's check-ins over the last 14 days, so the clinician
// view shows what following a patient over time looks like. Never stored or sent anywhere.
const EXAMPLE_HISTORY = [
  { daysAgo: 13, at: '22:41', sd: 1.3, answer: 'Not now' },
  { daysAgo: 11, at: '23:05', sd: 1.6, answer: 'I want to take a break' },
  { daysAgo: 9, at: '21:52', sd: 1.2, answer: 'I am okay' },
  { daysAgo: 6, at: '00:14', sd: 2.1, answer: 'I want to take a break' },
  { daysAgo: 6, at: '00:58', sd: 2.4, answer: null },
  { daysAgo: 4, at: '23:37', sd: 1.8, answer: 'I want to take a break' },
  { daysAgo: 2, at: '22:20', sd: 1.4, answer: 'I am okay' },
  { daysAgo: 1, at: '23:49', sd: 2.6, answer: 'I want to take a break' },
];

function renderHistory() {
  const perDay = Array.from({ length: 14 }, (_, i) => EXAMPLE_HISTORY.filter((h) => h.daysAgo === 13 - i).length);
  const most = Math.max(...perDay);
  const breaks = EXAMPLE_HISTORY.filter((h) => h.answer === 'I want to take a break').length;
  const late = EXAMPLE_HISTORY.filter((h) => h.at >= '22:00' || h.at < '05:00').length;
  $('history').innerHTML = `<div class="hist-sum"><span><b>${EXAMPLE_HISTORY.length}</b>check-ins in 14 days</span><span><b>${breaks}</b>chose a break</span>
      <span><b>${late} of ${EXAMPLE_HISTORY.length}</b>after 22.00</span><span><b>${Math.max(...EXAMPLE_HISTORY.map((h) => h.sd)).toFixed(1)} SD</b>highest drift</span></div>
    <div class="days" role="img" aria-label="Check-ins per day over the last 14 days">${perDay.map((n) => `<i class="${n ? '' : 'zero'}" style="height:${n ? (n / most) * 100 : 3}%" title="${n} check-in${n === 1 ? '' : 's'}"></i>`).join('')}</div>
    <div class="day-labels"><span>${dayLabel(13)}</span><span>check-ins per day</span><span>${dayLabel(0)}</span></div>
    ${[...EXAMPLE_HISTORY].reverse().map(historyRow).join('')}`;
}

function dayLabel(daysAgo) {
  const day = new Date(Date.now() - daysAgo * 86400000);
  return day.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
}

function historyRow(h) {
  const outcome = h.answer ? `chose "${esc(h.answer)}"` : 'expired, no answer';
  return `<div class="row${h.answer ? '' : ' muted'}"><b>${dayLabel(h.daysAgo)} ${h.at.replace(':', '.')}</b> Drift ${h.sd.toFixed(1)} SD passed the 1 SD alarm → check-in sent → ${outcome}</div>`;
}

function nudgeRow({ nudge, response, state: status }, drift) {
  const chosen = nudge.card.options.find((o) => o.choice === response?.choice);
  const outcome = response ? `chose "${esc(chosen?.label ?? response.choice)}"` : status === 'open' ? 'no answer yet' : 'expired, no answer';
  const sd = nudge.reason.match(/([\d.]+) SD/)?.[1];
  const cause = sd ? `Drift ${sd} SD passed the ${drift?.config.warn ?? 1} SD alarm` : 'Drift passed the alarm';
  return `<div class="row"><b>${hhmm(nudge.created_at)}</b> ${cause} → check-in sent → ${outcome}</div>`;
}

function field(label, value) {
  return `<dt>${label}</dt><dd>${esc(value) || '<span style="color:var(--faint)">None</span>'}</dd>`;
}

function renderPackage() {
  const { package: p, analyser } = state.current;
  const mock = analyser.mock ? '<p class="mocknote">Mock output: no video was analysed.</p>' : '';
  $('pkg').innerHTML = `${mock}<h2>${esc(p.title)}</h2><div class="format">${esc(p.format.replaceAll('_', ' '))}</div>
    <blockquote>${esc(p.main_message)}</blockquote>
    <dl>${field('Meaning', p.intended_meaning)}${field('Cues', p.emotional_cues)}</dl>
    <details><summary>Details</summary><dl>${field('Transcript', p.transcript)}${field('On-screen text', p.on_screen_text)}${field('Visuals', p.visual_description)}${field('Audio', p.audio_description)}</dl></details>`;
}

// ---------------------------------------------------------------- affect map

const GEO = { W: 360, H: 330, L: 40, T: 12, PW: 308, PH: 282 };
const ELLIPSE_SD = 1;   // the ellipse is the 1 SD edge of the normal range
const affectX = (v) => GEO.L + (v - 0.5) / 5 * GEO.PW;
const affectY = (a) => GEO.T + GEO.PH - (a - 0.5) / 5 * GEO.PH;

function renderMap() {
  const points = state.clips.map(affectPoint);
  const shown = windowPoints(points);
  const current = points.find((p) => p.clip.id === state.current?.id);
  const extra = current && !shown.includes(current) ? [current] : [];
  $('map').innerHTML = axes() + normalOverlay() + [...shown, ...extra].map(dot).join('');
  animateArrow();
}

function axes() {
  const { L, T, PW, PH, H } = GEO;
  const ticks = [1, 2, 3, 4, 5].map((i) => `<text x="${affectX(i)}" y="${T + PH + 14}" text-anchor="middle">${i}</text><text x="${L - 8}" y="${affectY(i) + 4}" text-anchor="end">${i}</text>`).join('');
  const midY = T + PH / 2;
  return `<rect x="${L}" y="${T}" width="${PW}" height="${PH}" fill="none" stroke="var(--line)"/>${ticks}
    <text x="${L + PW / 2}" y="${H - 4}" text-anchor="middle">Valence</text>
    <text x="12" y="${midY}" transform="rotate(-90 12 ${midY})" text-anchor="middle">Arousal</text>`;
}

function affectPoint(clip) {
  const h = Math.abs(hash(clip.id));
  const jitter = (n) => ((n % 13) - 6) * 2.2;
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  return {
    clip,
    x: clamp(affectX(clip.valence) + jitter(h), GEO.L + 10, GEO.L + GEO.PW - 10),
    y: clamp(affectY(clip.arousal) + jitter(h >> 4), GEO.T + 10, GEO.T + GEO.PH - 10),
  };
}

function hash(text) {
  let h = 0;
  for (const c of text) h = (h * 31 + c.charCodeAt(0)) | 0;
  return h;
}

// Only the Shorts in the drift window: the ones the arrow averages.
function windowPoints(points) {
  const group = state.drift?.recent;
  if (group?.first_seen_at == null) return state.drift ? [] : points;
  const seen = new Map();
  for (const item of state.feed) seen.set(item.event.video_id, item.event.seen_at);
  return points.filter((p) => seen.get(p.clip.id) >= group.first_seen_at && seen.get(p.clip.id) <= group.last_seen_at);
}

function dot({ clip, x, y }) {
  const current = state.current?.id === clip.id;
  const ring = current ? `<circle cx="${x}" cy="${y}" r="11" fill="none" stroke="var(--acc)" stroke-width="2"/>` : '';
  return `<g><title>${esc(clip.title)}: valence ${clip.valence}, arousal ${clip.arousal}</title>${ring}
    <circle cx="${x}" cy="${y}" r="${current ? 6.5 : 5}" fill="${current ? 'var(--acc)' : 'var(--mut)'}" stroke="var(--card)" stroke-width="1.5" opacity="${current ? 1 : 0.7}"/></g>`;
}

function checkinActive() {
  if (state.card) return true;
  if (state.drift?.level !== 'warning' || !state.nudges.length) return false;
  const tl = state.drift.timeline;
  const calm = tl.findLastIndex((p) => p.level !== 'warning');
  const since = calm >= 0 ? tl[calm].seen_at - 2 : 0;
  return state.nudges.some((n) => n.nudge.created_at >= since);
}

function normalOverlay() {
  const n = state.drift?.affect_baseline;
  if (!n) return '';
  const cx = affectX(n.centre.valence), cy = affectY(n.centre.arousal);
  const rx = ELLIPSE_SD * n.sd.valence * GEO.PW / 5, ry = ELLIPSE_SD * n.sd.arousal * GEO.PH / 5;
  const active = checkinActive();
  const ellipse = `<ellipse cx="${cx}" cy="${cy}" rx="${rx}" ry="${ry}" fill="var(--card)" stroke="var(--mut)" stroke-dasharray="5 4"><title>Normal range: typical affect of English words (${esc(n.cite)}), centre plus or minus 1 SD</title></ellipse>
    <ellipse cx="${cx}" cy="${cy}" rx="${rx}" ry="${ry}" fill="var(--acc)" fill-opacity=".05" pointer-events="none"/>`;
  const label = `<text x="${cx}" y="${cy - ry - 5}" text-anchor="middle">typical</text>`;
  return lowMoodQuadrant(cx, cy, active) + ellipse + zoneForeground(cx, cy, rx, ry, active) + label + driftArrow(cx, cy);
}

// The warning zone: below the norm on both axes. The ellipse drawn over it leaves the part
// beyond 1 SD tinted, which is exactly where a drift counts as a warning.
function lowMoodQuadrant(cx, cy, active) {
  const { L, T, PH } = GEO;
  const bottom = T + PH;
  return `<g pointer-events="none"><title>Low-mood zone: lower valence and lower arousal than typical</title>
    <rect x="${L}" y="${cy}" width="${cx - L}" height="${bottom - cy}" fill="var(--warn)" fill-opacity="${active ? .22 : .07}"/>
    <line x1="${L}" y1="${cy}" x2="${cx}" y2="${cy}" stroke="var(--warn)" stroke-opacity="${active ? .85 : .55}" stroke-dasharray="2 4" stroke-width="1.5"/>
    <line x1="${cx}" y1="${cy}" x2="${cx}" y2="${bottom}" stroke="var(--warn)" stroke-opacity="${active ? .85 : .55}" stroke-dasharray="2 4" stroke-width="1.5"/></g>`;
}

// Drawn above the ellipse so the outline frames the exact region beyond 1 SD when a check-in is sent.
function zoneForeground(cx, cy, rx, ry, active) {
  const { L, T, PH } = GEO;
  const bottom = T + PH;
  const border = active
    ? `<path d="M ${L} ${cy} H ${cx - rx} A ${rx} ${ry} 0 0 0 ${cx} ${cy + ry} V ${bottom} H ${L} Z" fill="none" stroke="var(--warn)" stroke-width="2.5" stroke-linejoin="round" pointer-events="none"/>`
    : '';
  return `${border}<text x="${L + (active ? 8 : 6)}" y="${bottom - 8}" style="fill:var(--warn)${active ? ';font-weight:700' : ''}" pointer-events="none">depressive signal zone</text>`;
}

// The arrow glides from where it was drawn last to the new average (and fades to the new level's
// colour), instead of jumping, whenever a newly analysed Short moves it.
const ARROW_MS = 900;
const arrow = { origin: null, target: null, shown: null, colour: null, shownColour: null, frame: 0 };

function driftArrow(cx, cy) {
  const centroid = state.drift.recent.centroid;
  if (!centroid) return resetArrow();
  Object.assign(arrow, { origin: { x: cx, y: cy }, target: { x: affectX(centroid.valence), y: affectY(centroid.arousal) }, colour: LEVEL_STROKE[state.drift.level] });
  const colour = arrow.shownColour ?? arrow.colour;
  const ease = 'style="transition:stroke .6s ease,fill .6s ease"';
  return `<g><title>Average of the last ${state.drift.recent.n} Shorts</title><line id="arrow-line" x1="${cx}" y1="${cy}" x2="${cx}" y2="${cy}" stroke="${colour}" stroke-width="3" stroke-linecap="round" ${ease}/><polygon id="arrow-head" fill="${colour}" ${ease}/><circle cx="${cx}" cy="${cy}" r="3" fill="var(--mut)"/></g>`;
}

function resetArrow() {
  cancelAnimationFrame(arrow.frame);
  Object.assign(arrow, { target: null, shown: null, shownColour: null });
  return '';
}

function animateArrow() {
  cancelAnimationFrame(arrow.frame);
  if (!arrow.target || !$('arrow-line')) return;
  const from = arrow.shown ?? arrow.origin, to = arrow.target;
  const instant = matchMedia('(prefers-reduced-motion: reduce)').matches;
  placeArrow(from);
  $('arrow-line').getBoundingClientRect();   // commit the old colour so the change transitions
  ['arrow-line', 'arrow-head'].forEach((id, i) => $(id).setAttribute(i ? 'fill' : 'stroke', arrow.colour));
  arrow.shownColour = arrow.colour;
  let begin = null;   // the first frame's timestamp: rAF times can precede performance.now()
  const frame = (now) => {
    begin ??= now;
    const t = instant ? 1 : Math.min(1, Math.max(0, (now - begin) / ARROW_MS));
    const eased = 1 - (1 - t) ** 3;
    placeArrow({ x: from.x + (to.x - from.x) * eased, y: from.y + (to.y - from.y) * eased });
    if (t < 1) arrow.frame = requestAnimationFrame(frame);
  };
  arrow.frame = requestAnimationFrame(frame);
}

function placeArrow(tip) {
  const { x: cx, y: cy } = arrow.origin;
  arrow.shown = tip;
  $('arrow-line').setAttribute('x2', tip.x.toFixed(1));
  $('arrow-line').setAttribute('y2', tip.y.toFixed(1));
  const angle = Math.atan2(tip.y - cy, tip.x - cx);
  const wing = (turn) => `${(tip.x - 11 * Math.cos(angle + turn)).toFixed(1)},${(tip.y - 11 * Math.sin(angle + turn)).toFixed(1)}`;
  $('arrow-head').setAttribute('points', Math.hypot(tip.x - cx, tip.y - cy) > 5 ? `${tip.x.toFixed(1)},${tip.y.toFixed(1)} ${wing(0.45)} ${wing(-0.45)}` : '');
}

// ---------------------------------------------------------------- wiring

window.addEventListener('message', onPlayerMessage);
$('touch').addEventListener('wheel', onWheel, { passive: false });
$('touch').addEventListener('pointerdown', (event) => { state.pointer = event.clientY; });
$('touch').addEventListener('pointerup', onPointerUp);
$('touch').addEventListener('pointercancel', () => { state.pointer = null; });
$('up').onclick = () => step(-1);
$('down').onclick = () => step(1);
$('sound').onclick = toggleSound;
$('reset').onclick = reset;
$('add').onsubmit = addShort;
document.querySelectorAll('[role="tab"]').forEach((tab) => { tab.onclick = () => selectTab(tab); tab.onkeydown = onTabKey; });
if (location.hash === '#clinician') selectTab($('tab-clinician'));   // a link can open the clinician's view
document.addEventListener('keydown', (event) => {
  if (event.target.closest('input, textarea')) return;
  if (event.key === 'ArrowDown' || event.key === 'j') { event.preventDefault(); step(1); }
  if (event.key === 'ArrowUp' || event.key === 'k') { event.preventDefault(); step(-1); }
  if (event.key === ' ' && !event.target.closest('button, summary')) { event.preventDefault(); setPaused(!state.paused); }
});
init().catch((error) => { console.error(error); setStatus(`Server not reachable: ${error.message}`, true); });
