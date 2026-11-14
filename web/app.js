'use strict';

const $ = (id) => document.getElementById(id);
const POLL_MS = 2000;
const STRIP_MAX = 7;
const THUMB_STEP = 92;   // thumbnail width plus gap, in px
const state = { meta: null, viewer: null, feed: [], clips: [], current: null, follow: true, signature: '', drift: null };

function esc(text) {
  return String(text ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

const hhmm = (seconds) => new Date(seconds * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

// The API may require a Bearer token (SCROLLSENSE_TOKEN). Open the page once with ?token=...;
// it is kept in localStorage and removed from the address bar.
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

async function api(path) {
  const response = await fetch(path, { headers: TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {} });
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || response.statusText);
  return response.json();
}

function setStatus(text, isError = false) {
  $('status').textContent = text;
  $('status').className = isError ? 'err' : '';
}

// ---------------------------------------------------------------- live feed of one viewer

async function init() {
  state.meta = await api('/api/meta');
  renderMode();
  await loadViewers();
  await tick();
  setInterval(() => tick().catch((error) => setStatus(error.message, true)), POLL_MS);
}

function storedViewer() {
  const fromUrl = new URLSearchParams(location.search).get('viewer');
  try { return fromUrl || localStorage.getItem('scrollsense.viewer'); } catch { return fromUrl; }
}

async function loadViewers() {
  const viewers = await api('/api/viewers');
  const names = viewers.map((v) => v.viewer);
  const newest = [...viewers].sort((a, b) => (b.last_seen ?? 0) - (a.last_seen ?? 0))[0];
  state.viewer = names.includes(storedViewer()) ? storedViewer() : newest?.viewer ?? null;
  $('viewer').innerHTML = viewers.map((v) => `<option value="${esc(v.viewer)}" ${v.viewer === state.viewer ? 'selected' : ''}>${esc(v.viewer)}</option>`).join('');
  if (!state.viewer) setStatus('No viewers yet. Scroll Shorts on the phone with the userscript.');
}

function changeViewer(viewer) {
  state.viewer = viewer;
  try { localStorage.setItem('scrollsense.viewer', viewer); } catch { /* per-viewer convenience only */ }
  Object.assign(state, { feed: [], clips: [], current: null, signature: '', drift: null });
  setFollow(true);
}

async function tick() {
  if (!state.viewer) return loadViewers();
  const [feed, drift, nudges] = await Promise.all([
    api(`/api/viewers/${state.viewer}/feed?limit=200`),
    api(`/api/viewers/${state.viewer}/drift`).catch(() => null),
    api(`/api/viewers/${state.viewer}/nudges`).catch(() => []),
  ]);
  renderSignals(drift, nudges);
  const signature = feed.map((item) => item.event.event_id + item.state).join('|');
  if (signature === state.signature) return;
  state.signature = signature;
  state.feed = feed;
  await refreshClips();
  await followOrRefresh();
}

// Unique Shorts, oldest first (the feed endpoint returns newest first).
function shorts() {
  const seen = new Set();
  return state.feed.filter((item) => !seen.has(item.event.video_id) && seen.add(item.event.video_id)).reverse();
}

async function refreshClips() {
  const all = shorts();
  const scored = new Set(all.filter((item) => item.state === 'scored').map((item) => item.event.video_id));
  state.clips = (await api('/api/clips')).filter((clip) => scored.has(clip.id));
  const waiting = all.filter((item) => item.state === 'queued').length;
  setStatus(`${all.length} Shorts, ${scored.size} analysed${waiting ? `, ${waiting} in queue` : ''}`);
  renderStrip();
  renderMap();
}

async function followOrRefresh() {
  const newest = state.feed[0]?.event.video_id;
  if (state.follow && newest && newest !== state.current?.id) return select(newest, false);
  if (state.current && !state.current.scores) return select(state.current.id, false);
}

function setFollow(on) {
  state.follow = on;
  $('live').setAttribute('aria-pressed', String(on));
  if (on) state.signature = '';
}

async function select(id, manual = true) {
  if (manual) setFollow(false);
  if (id !== state.current?.id) {
    state.current = { id };
    renderVideo();
  }
  try {
    state.current = await api(`/api/clips/${id}`);
    renderPackage();
  } catch { renderPending(id); }
  renderStrip();
  renderMap();
}

function step(delta) {
  const all = shorts();
  const at = all.findIndex((item) => item.event.video_id === state.current?.id);
  const next = all[Math.min(all.length - 1, Math.max(0, (at < 0 ? all.length - 1 : at) + delta))];
  if (next && next.event.video_id !== state.current?.id) select(next.event.video_id);
}

function renderMode() {
  const { analyser } = state.meta;
  $('mode').textContent = analyser.mock ? 'Mock mode, no API calls' : analyser.name;
  $('mode').classList.toggle('mock', analyser.mock);
}

// ---------------------------------------------------------------- warning and nudges

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
  return `<div><b>Nudge ${hhmm(nudge.created_at)}</b> ${outcome}</div>`;
}

// ---------------------------------------------------------------- carousel of scrolled Shorts

function renderStrip() {
  const all = shorts();
  const found = all.findIndex((item) => item.event.video_id === state.current?.id);
  const at = found < 0 ? all.length - 1 : found;
  const size = stripSize();
  const start = Math.min(Math.max(0, at - Math.floor(size / 2)), Math.max(0, all.length - size));
  $('thumbs').innerHTML = all.slice(start, start + size).map(thumb).join('');
  $('thumbs').querySelectorAll('[data-id]').forEach((b) => { b.onclick = () => select(b.dataset.id); });
  $('count').textContent = all.length ? `${at + 1} of ${all.length}` : '';
  $('prev').disabled = at <= 0;
  $('next').disabled = at >= all.length - 1;
}

// As many thumbnails as fit, so the selected one is never clipped.
function stripSize() {
  return Math.max(1, Math.min(STRIP_MAX, Math.floor(($('thumbs').clientWidth + 8) / THUMB_STEP)));
}

function thumb(item) {
  const id = item.event.video_id;
  const title = item.clip?.title ?? (item.state === 'failed' ? 'Analysis failed' : 'Analysing...');
  const on = state.current?.id === id;
  return `<button type="button" class="thumb ${item.state}${on ? ' on' : ''}" data-id="${esc(id)}" title="${esc(title)}" aria-current="${on}">
    <span class="img" style="background-image:url('https://i.ytimg.com/vi/${esc(id)}/mqdefault.jpg')"></span><span class="t">${esc(title)}</span></button>`;
}

// ---------------------------------------------------------------- video and text package

function renderVideo() {
  const { id } = state.current;
  $('video').innerHTML = `<div class="video"><iframe src="https://www.youtube.com/embed/${id}?rel=0&playsinline=1&autoplay=1&mute=1&loop=1&playlist=${id}" title="Original video" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen></iframe></div>
    <a class="video-link" href="https://www.youtube.com/shorts/${id}" target="_blank" rel="noopener">Open on YouTube</a>`;
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

function renderPending(id) {
  const item = state.feed.find((entry) => entry.event.video_id === id);
  const text = item?.state === 'failed' ? `Analysis failed: ${item.error}` : 'Gemini is watching this Short...';
  $('pkg').innerHTML = `<div class="empty">${esc(text)}</div>`;
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
  $('map').querySelectorAll('[data-id]').forEach((g) => { g.onclick = () => select(g.dataset.id); });
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
  return `<g data-id="${esc(clip.id)}" style="cursor:pointer"><title>${esc(clip.title)}: valence ${clip.valence}, arousal ${clip.arousal}</title>${ring}
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

function driftArrow(cx, cy) {
  const centroid = state.drift.recent.centroid;
  if (!centroid) return '';
  const tx = affectX(centroid.valence), ty = affectY(centroid.arousal);
  const colour = LEVEL_STROKE[state.drift.level];
  const angle = Math.atan2(ty - cy, tx - cx);
  const wing = (turn) => `${(tx - 11 * Math.cos(angle + turn)).toFixed(1)},${(ty - 11 * Math.sin(angle + turn)).toFixed(1)}`;
  const tip = Math.hypot(tx - cx, ty - cy) > 5 ? `<polygon points="${tx},${ty} ${wing(0.45)} ${wing(-0.45)}" fill="${colour}"/>` : '';
  return `<g><title>Average of the last ${state.drift.recent.n} Shorts</title><line x1="${cx}" y1="${cy}" x2="${tx}" y2="${ty}" stroke="${colour}" stroke-width="3" stroke-linecap="round"/>${tip}<circle cx="${cx}" cy="${cy}" r="3" fill="var(--mut)"/></g>`;
}

// ---------------------------------------------------------------- wiring

$('viewer').onchange = (event) => changeViewer(event.target.value);
$('live').onclick = () => setFollow(!state.follow);
$('prev').onclick = () => step(-1);
$('next').onclick = () => step(1);
window.addEventListener('resize', () => renderStrip());
document.addEventListener('keydown', (event) => {
  if (event.target.closest('select, input, textarea, summary')) return;
  if (event.key === 'ArrowLeft') step(-1);
  if (event.key === 'ArrowRight') step(1);
});
init().catch((error) => { console.error(error); setStatus(`Server not reachable: ${error.message}`, true); });
