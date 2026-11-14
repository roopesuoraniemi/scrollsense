'use strict';

const $ = (id) => document.getElementById(id);
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
const LEGEND = `Colour = DSM-5 theme load: ${swatch('var(--cool)')} low → ${swatch('var(--warm)')} high · ${swatch('var(--danger)')} A9 safety theme`;

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
  return new URLSearchParams(location.search).get('view') === 'sem' ? 'sem' : 'aff';
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
  const [feed, drift] = await Promise.all([
    api(`/api/viewers/${state.viewer}/feed?limit=100`),
    api(`/api/viewers/${state.viewer}/drift`).catch(() => null),
  ]);
  updateDrift(drift);
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
  const banner = analyser.mock ? '<div class="safety mockbanner">Mock output: placeholder text, no video was analysed.</div>' : '';
  $('pkg').innerHTML = `${banner}<div style="font-weight:600;font-size:16px">${esc(p.title)}</div>
    <div class="chips"><span class="chip">${esc(p.format)}</span><span class="chip">${p.people_present ? 'people present' : 'no people'}</span><span class="chip">lang: ${esc(p.language)}</span></div>
    <dl>${packageField('main_message', 'Main message')}${packageField('intended_meaning', 'Intended meaning')}${packageField('emotional_cues', 'Emotional cues')}${packageField('transcript', 'Transcript', 'scroll')}${packageField('on_screen_text', 'On-screen text', 'scroll')}${packageField('visual_description', 'Visuals')}${packageField('audio_description', 'Audio')}</dl>
    <p class="note">Generated by ${esc(analyser.name)}. This text is what stage 2 scores.</p>`;
}

// ---------------------------------------------------------------- panel 3: map

function renderMap() {
  const layer = state.view === 'aff' ? affectLayer() : semanticLayer();
  const normal = state.view === 'aff' ? normalOverlay() : '';
  $('map').innerHTML = frame() + layer.axes + normal + dots(layer.points);
  const normalNote = normal ? `<br>${NORMAL_LEGEND}` : '';
  $('mapnote').innerHTML = `${layer.note}<br>${LEGEND}${normalNote}`;
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

function semanticLayer() {
  const points = state.clips.filter((c) => c.semantic).map((clip) => ({
    clip, x: GEO.L + GEO.PW / 2 + clip.semantic.x * GEO.PW * 0.43, y: GEO.T + GEO.PH / 2 - clip.semantic.y * GEO.PH * 0.43,
  }));
  const empty = points.length < 2 ? `<text x="${GEO.L + GEO.PW / 2}" y="${GEO.T + GEO.PH / 2}" text-anchor="middle">Needs at least 2 analysed Shorts</text>` : '';
  return {
    axes: axisTitles('Principal component 1', 'Principal component 2') + empty,
    points,
    note: `2-D PCA of text-package embeddings (${esc(state.meta.analyser.embed_name)}). Nearby points have similar content. Axes are relative and shift as clips are added.`,
  };
}

function hash(text) {
  let h = 0;
  for (const c of text) h = (h * 31 + c.charCodeAt(0)) | 0;
  return h;
}

function pointColour(clip) {
  if (clip.a9 > 0) return 'var(--danger)';
  return `color-mix(in srgb, var(--warm) ${Math.round(Math.min(clip.load, 18) / 18 * 100)}%, var(--cool))`;
}

function dots(points) {
  const isCurrent = (p) => state.current?.id === p.clip.id;
  const currentLast = [...points].sort((a, b) => isCurrent(a) - isCurrent(b));
  return currentLast.map((p) => dot(p, isCurrent(p))).join('');
}

function dot({ clip, x, y }, current) {
  const ring = current ? `<circle cx="${x}" cy="${y}" r="13" fill="none" stroke="var(--acc)" stroke-width="2"/>` : '';
  return `<g data-id="${clip.id}" style="cursor:pointer"><title>${esc(clip.title)} · theme load ${clip.load}/27</title>${ring}
    <circle cx="${x}" cy="${y}" r="${current ? 8 : 5.5}" fill="${pointColour(clip)}" stroke="var(--card)" stroke-width="1.5" opacity="${current ? 1 : 0.75}"/></g>`;
}

function setView(view) {
  state.view = view;
  renderToggle();
  renderMap();
}

function renderToggle() {
  $('tAff').classList.toggle('on', state.view === 'aff');
  $('tSem').classList.toggle('on', state.view === 'sem');
}

// ---------------------------------------------------------------- drift from this person's normal

// Same floor the detector puts under the baseline SD of valence and arousal, so the ellipse
// shows the spread it actually tolerates even when every baseline Short scored alike.
const AFFECT_SD_FLOOR = 0.5;
const ELLIPSE_SD = 1.5;
const LEVEL_COLOUR = { learning: 'var(--mut)', normal: 'var(--ok)', watch: 'var(--amber)', warning: 'var(--danger)' };
const LEVEL_TITLE = { watch: 'Watch', warning: 'Warning' };
const NORMAL_LEGEND = `Dashed ellipse: this person's normal feed (baseline centre ± ${ELLIPSE_SD} SD) · arrow: where their recent Shorts moved`;

const hhmm = (seconds) => new Date(seconds * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

function updateDrift(drift) {
  const key = JSON.stringify(drift);
  if (key === state.driftKey) return;
  state.driftKey = key;
  state.drift = drift;
  renderDrift();
  renderMap();
}

async function refreshDrift() {
  if (!state.viewer) return;
  updateDrift(await api(`/api/viewers/${state.viewer}/drift`));
}

function renderDrift() {
  const d = state.drift;
  $('resetBase').disabled = d?.baseline.source !== 'marked';
  $('markBase').disabled = !state.viewer;
  $('drift').innerHTML = d ? driftLine(d) + safetyLine(d) : '';
  $('drift').querySelectorAll('[data-id]').forEach((b) => { b.onclick = () => select(b.dataset.id); });
}

function baselineText(b) {
  if (b.source === 'marked') return `baseline set by hand (${b.n} Shorts up to ${hhmm(b.last_seen_at)})`;
  return b.n ? `baseline: first ${b.n} Shorts` : 'no baseline yet';
}

function driftLine(d) {
  const alarming = d.level === 'watch' || d.level === 'warning';
  const quietContext = d.level === 'learning' && d.baseline.source === 'default' ? '' : ` · ${esc(baselineText(d.baseline))}`;
  const body = alarming ? alarmText(d) : `<b>${esc(d.note)}</b>${quietContext}`;
  const footer = '<span class="note" style="color:inherit;opacity:.8"> Drift from this person\'s normal feed: it describes the content shown, not a diagnosis.</span>';
  return `<div class="drift ${alarming ? d.level : 'quiet'}"><div class="what">${body}${footer}</div>${sparkline(d)}</div>`;
}

function alarmText(d) {
  const since = d.recent.first_seen_at != null ? ` · since ${hhmm(d.recent.first_seen_at)} (${d.recent.n} Shorts)` : '';
  const reasons = d.reasons.length ? `<div class="why">${d.reasons.map(esc).join(' · ')}</div>` : '';
  const chips = d.evidence.map((e) => chip(e.video_id, `${e.title} · valence ${e.valence} · load ${e.theme_load}`)).join('');
  return `<b>${LEVEL_TITLE[d.level]}: ${esc(d.note)}</b>${since} · ${esc(baselineText(d.baseline))}${reasons}<div class="chips">${chips}</div>`;
}

function chip(id, label) {
  return `<button type="button" data-id="${esc(id)}" title="${esc(label)}">${esc(label)}</button>`;
}

function safetyLine(d) {
  if (!d.safety.length) return '';
  const chips = d.safety.map((s) => chip(s.video_id, `A9 = ${s.a9} · ${s.title}`)).join('');
  return `<div class="drift safetyline"><div class="what"><b>Safety path:</b> ${d.safety.length} recent Short${d.safety.length > 1 ? 's' : ''} with death or suicide themes. Shown whatever the drift level: follow the clinician protocol.<div class="chips">${chips}</div></div></div>`;
}

function sparkline(d) {
  const points = d.timeline;
  if (points.length < 2) return '';
  const W = 200, H = 56, P = 4;
  const top = Math.max(d.config.warn * 1.3, ...points.map((p) => p.score));
  const x = (i) => P + i / (points.length - 1) * (W - 2 * P);
  const y = (v) => H - P - Math.min(v, top) / top * (H - 2 * P);
  // watch and warn sit close together, so their labels go at opposite ends of the chart
  const guide = (v, label, end) => `<line x1="${P}" x2="${W - P}" y1="${y(v)}" y2="${y(v)}" stroke="currentColor" stroke-dasharray="3 3" opacity=".5"/><text x="${end ? W - P : P}" y="${y(v) - 2}" text-anchor="${end ? 'end' : 'start'}" style="fill:currentColor;opacity:.7">${label}</text>`;
  const line = points.map((p, i) => `${x(i).toFixed(1)},${y(p.score).toFixed(1)}`).join(' ');
  const last = points[points.length - 1];
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Drift score over time"><title>Drift score of the last ${d.config.window} Shorts, at each Short after the baseline</title>${guide(d.config.watch, 'watch', false)}${guide(d.config.warn, 'warn', true)}<polyline points="${line}" fill="none" stroke="currentColor" stroke-width="1.5"/><circle cx="${x(points.length - 1)}" cy="${y(last.score)}" r="3" fill="${LEVEL_COLOUR[last.level]}"/></svg>`;
}

function normalOverlay() {
  const b = state.drift?.baseline;
  if (!b?.centroid) return '';
  const cx = affectX(b.centroid.valence), cy = affectY(b.centroid.arousal);
  const rx = ELLIPSE_SD * Math.max(b.sd.valence, AFFECT_SD_FLOOR) * GEO.PW / 5;
  const ry = ELLIPSE_SD * Math.max(b.sd.arousal, AFFECT_SD_FLOOR) * GEO.PH / 5;
  const ellipse = `<ellipse cx="${cx}" cy="${cy}" rx="${rx}" ry="${ry}" fill="var(--acc)" fill-opacity=".06" stroke="var(--acc)" stroke-dasharray="5 4"><title>This person's normal feed: ${b.n} baseline Shorts</title></ellipse>`;
  const clip = `<clipPath id="plotclip"><rect x="${GEO.L}" y="${GEO.T}" width="${GEO.PW}" height="${GEO.PH}"/></clipPath>`;
  const label = `<text x="${cx}" y="${Math.max(cy - ry - 4, GEO.T + 26)}" text-anchor="middle">normal</text>`;
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
  return `<g><title>Recent ${r.n} Shorts: centre moved from the normal feed</title><line x1="${cx}" y1="${cy}" x2="${tx}" y2="${ty}" stroke="${colour}" stroke-width="2.5" stroke-linecap="round"/>${tip}<circle cx="${cx}" cy="${cy}" r="3" fill="var(--acc)"/></g>`;
}

async function markBaseline() {
  if (!state.viewer || !confirm(`Use ${state.viewer}'s most recent analysed Shorts as their normal feed?`)) return;
  try {
    await api(`/api/viewers/${state.viewer}/baseline`, { method: 'POST' });
    setStatus('Baseline set: drift is now measured from the most recent Shorts.');
    await refreshDrift();
  } catch (error) { setStatus(error.message, true); }
}

async function resetBaseline() {
  if (!state.viewer) return;
  try {
    await api(`/api/viewers/${state.viewer}/baseline`, { method: 'DELETE' });
    setStatus('Baseline reset to the first analysed Shorts.');
    await refreshDrift();
  } catch (error) { setStatus(error.message, true); }
}

// ---------------------------------------------------------------- panel 4: DSM-5 scores

function scoreRow(criterion, value) {
  const segments = [1, 2, 3].map((i) => `<i class="${value >= i ? 'f' : ''}"></i>`).join('');
  return `<div class="row ${criterion.code === 'A9' ? 'a9' : ''}" title="${esc(criterion.theme)}"><span class="code">${criterion.code}</span><span>${esc(criterion.label)}</span><span class="bar">${segments}</span><span>${value}</span></div>`;
}

function safetyBanner(a9) {
  if (a9 <= 0) return '';
  return `<div class="safety"><b>Safety path:</b> this clip contains death or suicide themes (A9 = ${a9}). In the product it is never shown as a trend: engagement with it triggers the clinician protocol and shows crisis resources.</div>`;
}

function renderScores() {
  const { scores: s, load, valence } = state.current;
  const rows = state.meta.criteria.map((c) => scoreRow(c, s[c.key])).join('');
  $('dsm').innerHTML = `${safetyBanner(s.a9_death_suicide)}
    <div class="total"><b>${load}</b><span style="color:var(--mut)">/ 27 theme load (sum of A1–A9)</span></div>
    <div class="chips" style="margin-bottom:10px"><span class="chip">Stance: ${esc(STANCE[s.stance] || s.stance)}</span><span class="chip" title="Derived from negative and positive affect">Valence ${valence}/5</span><span class="chip">Negative affect ${s.negative_affect}/3</span><span class="chip">Positive affect ${s.positive_affect}/3</span><span class="chip">Arousal ${s.arousal}/5</span><span class="chip">${s.hopeful ? 'Hopeful' : 'Not hopeful'}</span></div>
    ${rows}<blockquote>${esc(s.evidence)}</blockquote>
    <p class="note"><b>Rationale:</b> ${esc(s.rationale)}</p>
    <p class="note">0 absent · 1 mentioned · 2 central · 3 intense or glorified. These scores describe the <i>content's</i> themes, not any person, and are not a diagnosis.</p>`;
}

// ---------------------------------------------------------------- wiring

$('viewer').onchange = (event) => changeViewer(event.target.value);
$('follow').onchange = (event) => setFollow(event.target.checked);
$('tAff').onclick = () => setView('aff');
$('tSem').onclick = () => setView('sem');
$('markBase').onclick = markBaseline;
$('resetBase').onclick = resetBaseline;
init().catch((error) => { console.error(error); setStatus(`Server not reachable: ${error.message}`, true); });
