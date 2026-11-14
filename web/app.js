'use strict';

// ScrollSense web demo: a phone that scrolls a scripted Shorts feed (plus pasted Shorts), the
// same pipeline as the real phone (each Short shown is a view event), and the clinician's view.

const $ = (id) => document.getElementById(id);
const POLL_MS = 2000;
const HEARTBEAT_MS = 2000;   // an empty view batch, so a card that becomes due arrives within 2 s
const SWIPE_PX = 40;
const WHEEL_LOCK_MS = 650;
const state = {
  meta: null, viewer: null, script: [], playlist: [], at: -1, feed: [], clips: [], drift: null,
  current: null, signature: '', card: null, answered: new Set(), onBreak: false,
  muted: true, paused: false, lastPost: 0, wheelUntil: 0, pointer: null, firstShown: new Map(),
};

function esc(text) {
  return String(text ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

const hhmm = (seconds) => new Date(seconds * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

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
  state.playlist = [...state.script];
  show(0);
  setInterval(() => tick().catch((error) => setStatus(error.message, true)), POLL_MS);
  setInterval(() => { heartbeat(); renderWaiting(); }, 1000);
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
  const { id } = state.playlist[index];
  if (!state.firstShown.has(id)) state.firstShown.set(id, Date.now());
  renderPlayer();
  renderPhoneChrome();
  postViews([viewEvent(state.playlist[index].id)]);
  tick().catch(() => {});
}

const step = (delta) => show(state.at + delta);

function renderPlayer() {
  const { id } = state.playlist[state.at];
  const query = `enablejsapi=1&rel=0&playsinline=1&autoplay=1&mute=1&loop=1&controls=0&playlist=${id}&origin=${encodeURIComponent(location.origin)}`;
  $('screen').style.backgroundImage = `url('https://i.ytimg.com/vi/${id}/hqdefault.jpg')`;
  $('player').innerHTML = `<iframe src="https://www.youtube.com/embed/${id}?${query}" title="Short ${state.at + 1}" allow="autoplay; encrypted-media"></iframe>`;
  $('player').querySelector('iframe').addEventListener('load', () => {
    if (!state.muted) [700, 1500].forEach((ms) => setTimeout(() => command('unMute'), ms));
  });
}

function renderPhoneChrome() {
  $('pos').textContent = `${state.at + 1}/${state.playlist.length}`;
  $('up').disabled = state.at <= 0;
  $('down').disabled = state.at >= state.playlist.length - 1;
  $('paused').classList.toggle('on', state.paused && !state.card && !state.onBreak);
  $('sound').textContent = state.muted ? '\u{1F507}' : '\u{1F50A}';
  $('sound').setAttribute('aria-pressed', String(!state.muted));
}

// The embedded player takes commands by postMessage (enablejsapi=1).
function command(func) {
  const frame = $('player').querySelector('iframe');
  frame?.contentWindow.postMessage(JSON.stringify({ event: 'command', func, args: [] }), '*');
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
}

async function choose(option) {
  const card = state.card;
  state.answered.add(card.id);
  state.card = null;
  $('overlay').innerHTML = '';
  if (option.action === 'leave') takeBreak(); else setPaused(false);
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
    <button type="button" id="gone-reset">Reset demo</button></div>`;
  $('gone-reset').onclick = reset;
}

async function reset() {
  await api(`/api/viewers/${state.viewer}`, { method: 'DELETE' }).catch((error) => setStatus(error.message, true));
  Object.assign(state, { playlist: [...state.script], feed: [], clips: [], drift: null, current: null, signature: '', card: null, onBreak: false });
  state.answered.clear();
  state.firstShown.clear();
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

function renderWaiting() {
  const id = state.playlist[state.at]?.id;
  const waiting = Boolean(id) && state.current?.id === id && !state.current.package;
  $('analysing').classList.toggle('on', waiting);
  if (!waiting) return;
  const item = state.feed.find((entry) => entry.event.video_id === id);
  const seconds = Math.round((Date.now() - (state.firstShown.get(id) ?? Date.now())) / 1000);
  const text = item?.state === 'failed' ? `Analysis failed: ${item.error}` : `Gemini is watching this Short... ${seconds} s`;
  $('analysing').textContent = item?.state === 'failed' ? 'Analysis failed' : `Gemini is watching... ${seconds} s`;
  $('pkg').innerHTML = `<div class="empty">${esc(text)}</div>`;
}

const LEVEL_CLASS = { learning: 'quiet', normal: 'quiet', watch: 'watch', warning: 'warning' };
const LEVEL_TITLE = { normal: 'Normal range', watch: 'Watch', warning: 'Warning' };
const LEVEL_STROKE = { learning: 'var(--faint)', normal: 'var(--mut)', watch: 'var(--watch)', warning: 'var(--warn)' };

function renderSignals(drift, nudges) {
  state.drift = drift;
  const shown = nudges.slice(0, 3);   // the API lists the newest first
  $('signals').classList.toggle('solo', shown.length === 0);
  $('nudges').innerHTML = shown.map(nudgeRow).join('');
  $('drift').className = `panel ${LEVEL_CLASS[drift?.level] ?? 'quiet'}`;
  $('drift').innerHTML = drift ? driftSummary(drift) + sparkline(drift) : '<div class="what"><span>No drift report yet</span></div>';
}

function driftSummary(d) {
  const n = d.recent.n;
  if (d.level === 'learning') return `<div class="what"><b>Collecting Shorts</b><span>${n} of ${Math.ceil(d.config.window / 2)} analysed</span></div>`;
  return `<div class="what"><b>${LEVEL_TITLE[d.level]}</b><span>${(d.score ?? 0).toFixed(1)} SD, last ${n} Shorts</span></div>`;
}

function sparkline(d) {
  const points = d.timeline.slice(-40);
  if (points.length < 2) return '<svg aria-hidden="true"></svg>';
  const W = 400, H = 46, P = 5;
  const top = Math.max(d.config.warn * 2, ...points.map((p) => p.score));
  const x = (i) => P + i / (points.length - 1) * (W - 2 * P);
  const y = (v) => H - P - Math.min(v, top) / top * (H - 2 * P);
  const line = points.map((p, i) => `${x(i).toFixed(1)},${y(p.score).toFixed(1)}`).join(' ');
  const stroke = LEVEL_STROKE[d.level];
  const last = { x: x(points.length - 1), y: y(points[points.length - 1].score) };
  return `<div class="spark"><span style="top:${(y(d.config.warn) / H * 100).toFixed(0)}%">${d.config.warn} SD</span><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Drift per Short; the dashed line is ${d.config.warn} SD">
    <line x1="${P}" x2="${W - P}" y1="${y(d.config.warn)}" y2="${y(d.config.warn)}" stroke="${stroke}" stroke-dasharray="5 4" opacity=".55" vector-effect="non-scaling-stroke"/>
    <polyline points="${line}" fill="none" stroke="${stroke}" stroke-width="2" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>
    <line x1="${last.x}" y1="${last.y}" x2="${last.x}" y2="${last.y}" stroke="${stroke}" stroke-width="7" stroke-linecap="round" vector-effect="non-scaling-stroke"/></svg></div>`;
}

function nudgeRow({ nudge, response, state: status }) {
  const chosen = nudge.card.options.find((o) => o.choice === response?.choice);
  const outcome = response ? `chose "${esc(chosen?.label ?? response.choice)}"` : status === 'open' ? 'no answer yet' : 'expired, no answer';
  return `<div><b>Check-in ${hhmm(nudge.created_at)}</b> ${outcome}</div>`;
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

function normalOverlay() {
  const n = state.drift?.affect_baseline;
  if (!n) return '';
  const cx = affectX(n.centre.valence), cy = affectY(n.centre.arousal);
  const rx = ELLIPSE_SD * n.sd.valence * GEO.PW / 5, ry = ELLIPSE_SD * n.sd.arousal * GEO.PH / 5;
  const ellipse = `<ellipse cx="${cx}" cy="${cy}" rx="${rx}" ry="${ry}" fill="var(--card)" stroke="var(--mut)" stroke-dasharray="5 4"><title>Normal range: typical affect of English words (${esc(n.cite)}), centre plus or minus 1 SD</title></ellipse>
    <ellipse cx="${cx}" cy="${cy}" rx="${rx}" ry="${ry}" fill="var(--acc)" fill-opacity=".05" pointer-events="none"/>`;
  const label = `<text x="${cx}" y="${cy - ry - 5}" text-anchor="middle">typical</text>`;
  return lowMoodQuadrant(cx, cy) + ellipse + label + driftArrow(cx, cy);
}

// The warning zone: below the norm on both axes. The ellipse drawn over it leaves the part
// beyond 1 SD tinted, which is exactly where a drift counts as a warning.
function lowMoodQuadrant(cx, cy) {
  const { L, T, PH } = GEO;
  const bottom = T + PH;
  return `<g pointer-events="none"><title>Low-mood zone: lower valence and lower arousal than typical</title>
    <rect x="${L}" y="${cy}" width="${cx - L}" height="${bottom - cy}" fill="var(--warn)" fill-opacity=".07"/>
    <line x1="${L}" y1="${cy}" x2="${cx}" y2="${cy}" stroke="var(--warn)" stroke-opacity=".55" stroke-dasharray="2 4" stroke-width="1.5"/>
    <line x1="${cx}" y1="${cy}" x2="${cx}" y2="${bottom}" stroke="var(--warn)" stroke-opacity=".55" stroke-dasharray="2 4" stroke-width="1.5"/>
    <text x="${L + 6}" y="${bottom - 8}" style="fill:var(--warn)">depressive signal zone</text></g>`;
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

$('touch').addEventListener('wheel', onWheel, { passive: false });
$('touch').addEventListener('pointerdown', (event) => { state.pointer = event.clientY; });
$('touch').addEventListener('pointerup', onPointerUp);
$('touch').addEventListener('pointercancel', () => { state.pointer = null; });
$('up').onclick = () => step(-1);
$('down').onclick = () => step(1);
$('sound').onclick = toggleSound;
$('reset').onclick = reset;
$('add').onsubmit = addShort;
document.addEventListener('keydown', (event) => {
  if (event.target.closest('input, textarea')) return;
  if (event.key === 'ArrowDown' || event.key === 'j') { event.preventDefault(); step(1); }
  if (event.key === 'ArrowUp' || event.key === 'k') { event.preventDefault(); step(-1); }
  if (event.key === ' ' && !event.target.closest('button, summary')) { event.preventDefault(); setPaused(!state.paused); }
});
init().catch((error) => { console.error(error); setStatus(`Server not reachable: ${error.message}`, true); });
