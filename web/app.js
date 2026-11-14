'use strict';

const $ = (id) => document.getElementById(id);
const VIEWS = { aff: 'tAff', con: 'tCon', sym: 'tSym' };
const state = { meta: null, viewer: null, feed: [], clips: [], current: null, follow: true, signature: '', view: initialView(), drift: null, driftKey: '' };
const POLL_MS = 2000;

const STANCE = {
  dwelling_or_romanticising: 'Dwelling / romanticising',
  neutral_or_informational: 'Neutral / informational',
  coping_or_recovery: 'Coping / recovery',
  unrelated: 'Unrelated',
};
const GEO = { W: 360, H: 330, L: 40, T: 14, PW: 308, PH: 280 };
const swatch = (c) => `<span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:${c};vertical-align:-1px"></span>`;
const LEGEND = `Colour = DSM-5 theme load: ${swatch('var(--cool)')} low → ${swatch('var(--warm)')} high`;

function esc(text) {
  return String(text ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

// The API may require a Bearer token (SCROLLSENSE_TOKEN). Open the page once with ?token=…;
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

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}), ...(TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {}) };
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || response.statusText);
  return response.status === 204 ? null : response.json();
}

function initialView() {
  const asked = new URLSearchParams(location.search).get('view');
  return asked in VIEWS ? asked : 'aff';
}

function setStatus(text, isError = false) {
  $('status').textContent = text;
  $('status').className = isError ? 'err' : '';
}

// ---------------------------------------------------------------- live feed of one viewer

async function init() {
  state.meta = await api('/api/meta');
  renderMode();
  renderToggle();
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
  $('viewer').innerHTML = viewers.map((v) => `<option value="${esc(v.viewer)}" ${v.viewer === state.viewer ? 'selected' : ''}>${esc(v.viewer)} (${v.events})</option>`).join('');
  if (!state.viewer) setStatus('No viewers yet: scroll Shorts on the phone with the userscript.');
}

function changeViewer(viewer) {
  state.viewer = viewer;
  try { localStorage.setItem('scrollsense.viewer', viewer); } catch { /* per-viewer convenience only */ }
  Object.assign(state, { feed: [], clips: [], current: null, signature: '', drift: null, driftKey: '' });
  renderDrift();
  setFollow(true);
}

async function tick() {
  if (!state.viewer) return loadViewers();
  const [feed, drift, nudges] = await Promise.all([
    api(`/api/viewers/${state.viewer}/feed?limit=100`),
    api(`/api/viewers/${state.viewer}/drift`).catch(() => null),
    api(`/api/viewers/${state.viewer}/nudges`).catch(() => []),
  ]);
  updateDrift(drift);
  renderNudges(nudges);
  const signature = feed.map((item) => item.event.event_id + item.state).join('|');
  if (signature === state.signature) return;
  state.signature = signature;
  state.feed = feed;
  await refreshClips();
  await followOrRefresh();
}

function feedVideos() {
  const seen = new Set();
  return state.feed.filter((item) => !seen.has(item.event.video_id) && seen.add(item.event.video_id));
}

async function refreshClips() {
  const videos = feedVideos();
  const scored = new Set(videos.filter((item) => item.state === 'scored').map((item) => item.event.video_id));
  state.clips = (await api('/api/clips')).filter((clip) => scored.has(clip.id));
  const waiting = videos.filter((item) => item.state === 'queued').length;
  setStatus(`${videos.length} Shorts from ${state.viewer} · ${scored.size} analysed · ${waiting} in queue`);
  renderList();
  renderMap();
}

async function followOrRefresh() {
  const newest = state.feed[0]?.event.video_id;
  if (state.follow && newest && newest !== state.current?.id) return select(newest, false);
  if (state.current && !state.current.scores) return select(state.current.id, false);
}

function setFollow(on) {
  state.follow = on;
  $('follow').checked = on;
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
    renderScores();
  } catch { renderPending(id); }
  renderList();
  renderMap();
}

function renderPending(id) {
  const item = state.feed.find((entry) => entry.event.video_id === id);
  const text = item?.state === 'failed' ? `Analysis failed: ${item.error}` : 'Queued: Gemini is watching this Short…';
  $('pkg').innerHTML = `<div class="empty">${esc(text)}</div>`;
  $('dsm').innerHTML = `<div class="empty">${esc(text)}</div>`;
}

// ---------------------------------------------------------------- header and list

function renderMode() {
  const { analyser } = state.meta;
  $('mode').textContent = analyser.mock ? 'MOCK mode, no API calls' : `Gemini: ${analyser.name}`;
  $('mode').classList.toggle('mock', analyser.mock);
}

function listButton(item) {
  const id = item.event.video_id;
  const label = item.clip ? item.clip.title : `${item.state === 'failed' ? '✗' : '⏳'} ${id}`;
  const dwell = item.event.dwell_s != null ? ` · ${Math.round(item.event.dwell_s)}s` : '';
  return `<button type="button" data-id="${id}" class="${state.current?.id === id ? 'on' : ''} ${item.state}" title="${esc(label)}">${esc(label)}${dwell}</button>`;
}

function renderList() {
  $('list').innerHTML = feedVideos().map(listButton).join('');
  [...$('list').children].forEach((b) => { b.onclick = () => select(b.dataset.id); });
}

// ---------------------------------------------------------------- panels 1 and 2

function renderVideo() {
  const { id } = state.current;
  const url = `https://www.youtube.com/shorts/${id}`;
  $('video').innerHTML = `<div class="video"><iframe src="https://www.youtube.com/embed/${id}?rel=0&playsinline=1&autoplay=1&mute=1&loop=1&playlist=${id}" title="Original video" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen></iframe></div>
    <p class="note"><a href="${url}" target="_blank" rel="noopener">${url}</a></p>`;
}

function packageField(key, label, cls = '') {
  const value = state.current.package[key];
  return `<dt>${label}</dt><dd class="${cls}">${esc(value) || '<span style="color:var(--mut)">(none)</span>'}</dd>`;
}

function renderPackage() {
  const { package: p, analyser } = state.current;
  const banner = analyser.mock ? '<div class="banner mockbanner">Mock output: placeholder text, no video was analysed.</div>' : '';
  $('pkg').innerHTML = `${banner}<div style="font-weight:600;font-size:16px">${esc(p.title)}</div>
    <div class="chips"><span class="chip">${esc(p.format)}</span><span class="chip">${p.people_present ? 'people present' : 'no people'}</span><span class="chip">lang: ${esc(p.language)}</span></div>
    <dl>${packageField('main_message', 'Main message')}${packageField('intended_meaning', 'Intended meaning')}${packageField('emotional_cues', 'Emotional cues')}${packageField('transcript', 'Transcript', 'scroll')}${packageField('on_screen_text', 'On-screen text', 'scroll')}${packageField('visual_description', 'Visuals')}${packageField('audio_description', 'Audio')}</dl>
    <p class="note">Generated by ${esc(analyser.name)}. This text is what stage 2 scores.</p>`;
}

// ---------------------------------------------------------------- panel 3: map

const LAYERS = { aff: () => affectLayer(), con: () => contentLayer(), sym: () => symptomLayer() };

function renderMap() {
  const layer = LAYERS[state.view]();
  const normal = state.view === 'aff' ? normalOverlay() : recentOverlay(layer.points);
  const shown = windowPoints(layer.points);
  $('map').innerHTML = frame() + layer.axes + normal + dots(shown);
  const normalNote = normal ? `<br>${state.view === 'aff' ? NORMAL_LEGEND : RECENT_LEGEND}` : '';
  const scope = state.drift ? `<br>Showing the ${shown.length} Shorts in the drift window (the ones the arrow averages).` : '';
  $('mapnote').innerHTML = `${layer.note}<br>${LEGEND}${normalNote}${scope}`;
  $('map').querySelectorAll('[data-id]').forEach((g) => { g.onclick = () => select(g.dataset.id); });
}

function frame() {
  return `<rect x="${GEO.L}" y="${GEO.T}" width="${GEO.PW}" height="${GEO.PH}" fill="none" stroke="var(--line)"/>`;
}

function axisTitles(xTitle, yTitle) {
  const midY = GEO.T + GEO.PH / 2;
  return `<text x="${GEO.L + GEO.PW / 2}" y="${GEO.H - 4}" text-anchor="middle">${xTitle}</text>
    <text x="12" y="${midY}" transform="rotate(-90 12 ${midY})" text-anchor="middle">${yTitle}</text>`;
}

const affectX = (v) => GEO.L + (v - 0.5) / 5 * GEO.PW;
const affectY = (a) => GEO.T + GEO.PH - (a - 0.5) / 5 * GEO.PH;

function affectLayer() {
  return {
    axes: affectGrid() + affectQuadrants() + axisTitles('Valence: negative → positive', 'Arousal'),
    points: state.clips.map(affectPoint),
    note: 'Axes come from stage-2 scores: valence (1–5, derived from negative and positive affect) and arousal (1–5). Small offsets keep clips with equal scores apart.',
  };
}

function affectGrid() {
  const centre = `<line x1="${affectX(3)}" y1="${GEO.T}" x2="${affectX(3)}" y2="${GEO.T + GEO.PH}" stroke="var(--line)" stroke-dasharray="3 3"/>
    <line x1="${GEO.L}" y1="${affectY(3)}" x2="${GEO.L + GEO.PW}" y2="${affectY(3)}" stroke="var(--line)" stroke-dasharray="3 3"/>`;
  const ticks = [1, 2, 3, 4, 5].map((i) =>
    `<text x="${affectX(i)}" y="${GEO.T + GEO.PH + 14}" text-anchor="middle">${i}</text><text x="${GEO.L - 8}" y="${affectY(i) + 4}" text-anchor="end">${i}</text>`).join('');
  return centre + ticks;
}

function affectQuadrants() {
  const { L, T, PW, PH } = GEO;
  return `<text x="${L + 6}" y="${T + 14}">energetic, negative</text><text x="${L + PW - 6}" y="${T + 14}" text-anchor="end">energetic, positive</text>
    <text x="${L + 6}" y="${T + PH - 8}">calm, negative</text><text x="${L + PW - 6}" y="${T + PH - 8}" text-anchor="end">calm, positive</text>`;
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

// Content similarity: fixed axes from scripts/build_content_axis.py. x is 0 at the light test
// Shorts' centre and 1 at the depression-themed ones'; y is the main other topic direction (SD).
const CONTENT = { xMin: -0.5, xMax: 1.5, yMin: -3, yMax: 3 };
const contentX = (v) => GEO.L + (v - CONTENT.xMin) / (CONTENT.xMax - CONTENT.xMin) * GEO.PW;
const contentY = (v) => GEO.T + GEO.PH - (v - CONTENT.yMin) / (CONTENT.yMax - CONTENT.yMin) * GEO.PH;
const clampTo = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

function contentLayer() {
  const points = state.clips.filter((c) => c.content).map((clip) => ({
    clip,
    x: clampTo(contentX(clip.content.x), GEO.L + 8, GEO.L + GEO.PW - 8),
    y: clampTo(contentY(clip.content.y), GEO.T + 8, GEO.T + GEO.PH - 8),
  }));
  const empty = points.length ? '' : emptyText('No embeddings from the reference model yet');
  return {
    axes: contentGuides() + axisTitles('Similar to depression-themed Shorts →', 'Main other topic direction') + empty,
    points,
    note: 'Fixed axes from the text-package embeddings, learned once from 50 labelled test Shorts: independent of the LLM scores. 0 = like the light test Shorts, 1 = like the depression-themed ones.',
  };
}

function contentGuides() {
  const guide = (v, label) => `<line x1="${contentX(v)}" y1="${GEO.T}" x2="${contentX(v)}" y2="${GEO.T + GEO.PH}" stroke="var(--line)" stroke-dasharray="3 3"/><text x="${contentX(v)}" y="${GEO.T + 14}" text-anchor="middle">${label}</text>`;
  const ticks = [-0.5, 0, 0.5, 1, 1.5].map((v) => `<text x="${contentX(v)}" y="${GEO.T + GEO.PH + 14}" text-anchor="middle">${v}</text>`).join('');
  return guide(0, 'light') + guide(1, 'depression-themed') + ticks;
}

// Symptom space: DSM-5 theme clusters from the stage-2 scores, each axis 0-6.
const symptomX = (v) => GEO.L + (v + 0.5) / 7 * GEO.PW;
const symptomY = (v) => GEO.T + GEO.PH - (v + 0.5) / 7 * GEO.PH;

function symptomLayer() {
  return {
    axes: symptomGrid() + axisTitles('Low mood + anhedonia (A1 + A2) →', 'Sleep + fatigue (A4 + A6) →'),
    points: state.clips.map(symptomPoint),
    note: 'DSM-5 theme clusters of the content (0 absent … 6 = both themes intense). Most light Shorts sit at 0, 0. Small offsets keep clips with equal scores apart; hover a dot for worthlessness/guilt (A7).',
  };
}

function symptomGrid() {
  const ticks = [0, 2, 4, 6].map((i) => `<text x="${symptomX(i)}" y="${GEO.T + GEO.PH + 14}" text-anchor="middle">${i}</text><text x="${GEO.L - 8}" y="${symptomY(i) + 4}" text-anchor="end">${i}</text>`).join('');
  const { L, T, PW, PH } = GEO;
  return `${ticks}<text x="${L + PW - 6}" y="${T + PH - 8}" text-anchor="end">low mood themes</text><text x="${L + 6}" y="${T + 14}">sleep / fatigue themes</text><text x="${L + PW - 6}" y="${T + 14}" text-anchor="end">both</text>`;
}

function symptomPoint(clip) {
  const h = Math.abs(hash(clip.id));
  const jitter = (n) => ((n % 13) - 6) * 2.2;
  return {
    clip,
    x: clampTo(symptomX(clip.symptoms.x) + jitter(h), GEO.L + 8, GEO.L + GEO.PW - 8),
    y: clampTo(symptomY(clip.symptoms.y) + jitter(h >> 4), GEO.T + 8, GEO.T + GEO.PH - 8),
  };
}

function emptyText(text) {
  return `<text x="${GEO.L + GEO.PW / 2}" y="${GEO.T + GEO.PH / 2}" text-anchor="middle">${text}</text>`;
}

// The content and symptom maps have no research norm, so they show only where the drift
// window (the report's recent Shorts) sits: the centre of its dots.
function firstSeen() {
  const seen = new Map();
  for (const item of state.feed) seen.set(item.event.video_id, item.event.seen_at);
  return seen;
}

// With a viewer's drift report, the maps show only the Shorts in its window.
function windowPoints(points) {
  return state.drift ? within(points, state.drift.recent, firstSeen()) : points;
}

function within(points, group, seen) {
  if (group?.first_seen_at == null) return [];
  return points.filter((p) => seen.get(p.clip.id) >= group.first_seen_at && seen.get(p.clip.id) <= group.last_seen_at);
}

function recentOverlay(points) {
  const recent = within(points, state.drift?.recent, firstSeen());
  if (!recent.length) return '';
  const mean = (pick) => recent.reduce((sum, p) => sum + pick(p), 0) / recent.length;
  const cx = mean((p) => p.x), cy = mean((p) => p.y);
  const colour = LEVEL_COLOUR[state.drift.level];
  return `<g><title>Centre of the recent ${recent.length} Shorts (the drift window)</title><circle cx="${cx}" cy="${cy}" r="11" fill="none" stroke="${colour}" stroke-width="2.5"/><circle cx="${cx}" cy="${cy}" r="2.5" fill="${colour}"/><text x="${cx}" y="${Math.max(cy - 15, GEO.T + 26)}" text-anchor="middle">recent</text></g>`;
}

function hash(text) {
  let h = 0;
  for (const c of text) h = (h * 31 + c.charCodeAt(0)) | 0;
  return h;
}

function pointColour(clip) {
  return `color-mix(in srgb, var(--warm) ${Math.round(Math.min(clip.load, 18) / 18 * 100)}%, var(--cool))`;
}

function dots(points) {
  const isCurrent = (p) => state.current?.id === p.clip.id;
  const currentLast = [...points].sort((a, b) => isCurrent(a) - isCurrent(b));
  return currentLast.map((p) => dot(p, isCurrent(p))).join('');
}

function dot({ clip, x, y }, current) {
  const ring = current ? `<circle cx="${x}" cy="${y}" r="13" fill="none" stroke="var(--acc)" stroke-width="2"/>` : '';
  return `<g data-id="${clip.id}" style="cursor:pointer"><title>${esc(clip.title)} · theme load ${clip.load}/27 · A7 ${clip.a7}</title>${ring}
    <circle cx="${x}" cy="${y}" r="${current ? 8 : 5.5}" fill="${pointColour(clip)}" stroke="var(--card)" stroke-width="1.5" opacity="${current ? 1 : 0.75}"/></g>`;
}

function setView(view) {
  state.view = view;
  renderToggle();
  renderMap();
}

function renderToggle() {
  Object.entries(VIEWS).forEach(([view, id]) => $(id).classList.toggle('on', state.view === view));
}

// ---------------------------------------------------------------- drift against research norms

// Same floor the detector puts under the norm SD of valence and arousal, so the ellipse
// shows the spread it actually tolerates.
// The ellipse is the 1 SD edge of the normal range: an arrow tip past it, pointing down-left, is a deviation.
const ELLIPSE_SD = 1;
const LEVEL_COLOUR = { learning: 'var(--mut)', normal: 'var(--ok)', watch: 'var(--amber)', warning: 'var(--danger)' };
const LEVEL_TITLE = { watch: 'Watch', warning: 'Warning' };
const NORMAL_LEGEND = `Dashed ellipse: typical affect from published word norms (centre ± ${ELLIPSE_SD} SD, the normal range) · arrow: where the recent Shorts sit; a deviation when it leaves the ellipse towards the bottom left`;
const RECENT_LEGEND = 'Ring: centre of the recent Shorts the drift detector judges (this map has no research norm)';

const hhmm = (seconds) => new Date(seconds * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

function updateDrift(drift) {
  const key = JSON.stringify(drift);
  if (key === state.driftKey) return;
  state.driftKey = key;
  state.drift = drift;
  renderDrift();
  renderMap();
}

function renderDrift() {
  const d = state.drift;
  $('drift').innerHTML = d ? driftLine(d) : '';
  $('drift').querySelectorAll('[data-id]').forEach((b) => { b.onclick = () => select(b.dataset.id); });
}

function clinicalLine(c) {
  if (!c) return '';
  return `<div class="why">Content exposure, PHQ-9 style: <b>${c.total}/27</b> · ${esc(c.band)} · pattern: ${esc(c.pattern)} (last ${c.window_n} Shorts) — describes the content shown, not the person</div>`;
}

function driftLine(d) {
  const alarming = d.level === 'watch' || d.level === 'warning';
  const body = alarming ? alarmText(d) : `<b>${esc(d.note)}</b>`;
  const footer = `<span class="note" style="color:inherit;opacity:.8"> Compared with word-affect norms (${esc(d.affect_baseline.cite)}) and PHQ-9 cutoffs: it describes the content shown, not a diagnosis.</span>`;
  return `<div class="drift ${alarming ? d.level : 'quiet'}"><div class="what">${body}${footer}${clinicalLine(d.clinical)}</div>${sparkline(d)}</div>`;
}

function alarmText(d) {
  const since = d.recent.first_seen_at != null ? ` · since ${hhmm(d.recent.first_seen_at)} (${d.recent.n} Shorts)` : '';
  const reasons = d.reasons.length ? `<div class="why">${d.reasons.map(esc).join(' · ')}</div>` : '';
  const themes = (e) => (e.central.length ? e.central.join('/') : 'no central theme');
  const chips = d.evidence.map((e) => chip(e.video_id, `${e.title} · valence ${e.valence} · ${themes(e)}`)).join('');
  return `<b>${LEVEL_TITLE[d.level]}: ${esc(d.note)}</b>${since}${reasons}<div class="chips">${chips}</div>`;
}

function chip(id, label) {
  return `<button type="button" data-id="${esc(id)}" title="${esc(label)}">${esc(label)}</button>`;
}

function sparkline(d) {
  const points = d.timeline;
  if (points.length < 2) return '';
  const W = 200, H = 56, P = 4;
  const top = Math.max(d.config.warn * 2, ...points.map((p) => p.score));
  const x = (i) => P + i / (points.length - 1) * (W - 2 * P);
  const y = (v) => H - P - Math.min(v, top) / top * (H - 2 * P);
  // watch and warn sit close together, so their labels go at opposite ends of the chart
  const guide = (v, label, end) => `<line x1="${P}" x2="${W - P}" y1="${y(v)}" y2="${y(v)}" stroke="currentColor" stroke-dasharray="3 3" opacity=".5"/><text x="${end ? W - P : P}" y="${y(v) - 2}" text-anchor="${end ? 'end' : 'start'}" style="fill:currentColor;opacity:.7">${label}</text>`;
  const line = points.map((p, i) => `${x(i).toFixed(1)},${y(p.score).toFixed(1)}`).join(' ');
  const last = points[points.length - 1];
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Affect score over time"><title>Affect score (SDs of drift towards lower valence and arousal; 0 in any other direction) of the last ${d.config.window} Shorts at each Short; dot colour = overall level; PHQ-9-style exposure now ${last.exposure}/27</title>${d.config.watch < d.config.warn ? guide(d.config.watch, 'watch', false) : ''}${guide(d.config.warn, `warn ${d.config.warn} SD`, true)}<polyline points="${line}" fill="none" stroke="currentColor" stroke-width="1.5"/><circle cx="${x(points.length - 1)}" cy="${y(last.score)}" r="3" fill="${LEVEL_COLOUR[last.level]}"/></svg>`;
}

function normalOverlay() {
  const n = state.drift?.affect_baseline;
  if (!n) return '';
  const cx = affectX(n.centre.valence), cy = affectY(n.centre.arousal);
  const rx = ELLIPSE_SD * n.sd.valence * GEO.PW / 5;
  const ry = ELLIPSE_SD * n.sd.arousal * GEO.PH / 5;
  const ellipse = `<ellipse cx="${cx}" cy="${cy}" rx="${rx}" ry="${ry}" fill="var(--acc)" fill-opacity=".06" stroke="var(--acc)" stroke-dasharray="5 4"><title>Typical affect of English words (${esc(n.source)}): centre ± ${ELLIPSE_SD} SD. Word norms, not video norms.</title></ellipse>`;
  const clip = `<clipPath id="plotclip"><rect x="${GEO.L}" y="${GEO.T}" width="${GEO.PW}" height="${GEO.PH}"/></clipPath>`;
  const label = `<text x="${cx}" y="${Math.max(cy - ry - 4, GEO.T + 26)}" text-anchor="middle">typical (norms)</text>`;
  return `${clip}<g clip-path="url(#plotclip)">${ellipse}${label}${driftArrow(cx, cy)}</g>`;
}

function driftArrow(cx, cy) {
  const r = state.drift.recent;
  if (!r.centroid) return '';
  const tx = affectX(r.centroid.valence), ty = affectY(r.centroid.arousal);
  const colour = LEVEL_COLOUR[state.drift.level];
  const angle = Math.atan2(ty - cy, tx - cx);
  const wing = (turn) => `${(tx - 10 * Math.cos(angle + turn)).toFixed(1)},${(ty - 10 * Math.sin(angle + turn)).toFixed(1)}`;
  const tip = Math.hypot(tx - cx, ty - cy) > 4 ? `<polygon points="${tx},${ty} ${wing(0.45)} ${wing(-0.45)}" fill="${colour}"/>` : '';
  return `<g><title>Recent ${r.n} Shorts: their centre relative to the word norm</title><line x1="${cx}" y1="${cy}" x2="${tx}" y2="${ty}" stroke="${colour}" stroke-width="2.5" stroke-linecap="round"/>${tip}<circle cx="${cx}" cy="${cy}" r="3" fill="var(--acc)"/></g>`;
}

// ---------------------------------------------------------------- nudges shown on the phone

const NUDGE_STATE = { open: 'waiting for an answer', expired: 'expired unanswered' };

function nudgeText(entry) {
  const { nudge, response, state: status } = entry;
  const chosen = nudge.card.options.find((o) => o.choice === response?.choice);
  const outcome = response ? `chose “${esc(chosen?.label ?? response.choice)}” at ${hhmm(response.at)}` : NUDGE_STATE[status] ?? status;
  return `<b>Support nudge</b> shown ${hhmm(nudge.created_at)} → ${outcome} <span title="${esc(nudge.reason)}">ⓘ</span>`;
}

function renderNudges(entries) {
  const recent = entries.slice(0, 3);
  const html = recent.length ? `Phone: ${recent.map(nudgeText).join(' · ')}` : '';
  if (html !== state.nudgesHtml) $('nudges').innerHTML = state.nudgesHtml = html;
}

// ---------------------------------------------------------------- panel 4: DSM-5 scores

function scoreRow(criterion, value) {
  const segments = [1, 2, 3].map((i) => `<i class="${value >= i ? 'f' : ''}"></i>`).join('');
  return `<div class="row" title="${esc(criterion.theme)}"><span class="code">${criterion.code}</span><span>${esc(criterion.label)}</span><span class="bar">${segments}</span><span>${value}</span></div>`;
}

function renderScores() {
  const { scores: s, load, valence } = state.current;
  const rows = state.meta.criteria.map((c) => scoreRow(c, s[c.key])).join('');
  $('dsm').innerHTML = `<div class="total"><b>${load}</b><span style="color:var(--mut)">/ 27 theme load (sum of A1–A9)</span></div>
    <div class="chips" style="margin-bottom:10px"><span class="chip">Stance: ${esc(STANCE[s.stance] || s.stance)}</span><span class="chip" title="Derived from negative and positive affect">Valence ${valence}/5</span><span class="chip">Negative affect ${s.negative_affect}/3</span><span class="chip">Positive affect ${s.positive_affect}/3</span><span class="chip">Arousal ${s.arousal}/5</span><span class="chip">${s.hopeful ? 'Hopeful' : 'Not hopeful'}</span></div>
    ${rows}<blockquote>${esc(s.evidence)}</blockquote>
    <p class="note"><b>Rationale:</b> ${esc(s.rationale)}</p>
    <p class="note">0 absent · 1 mentioned · 2 central · 3 intense or glorified. These scores describe the <i>content's</i> themes, not any person, and are not a diagnosis.</p>`;
}

// ---------------------------------------------------------------- wiring

$('viewer').onchange = (event) => changeViewer(event.target.value);
$('follow').onchange = (event) => setFollow(event.target.checked);
Object.entries(VIEWS).forEach(([view, id]) => { $(id).onclick = () => setView(view); });
init().catch((error) => { console.error(error); setStatus(`Server not reachable: ${error.message}`, true); });
