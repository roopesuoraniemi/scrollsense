'use strict';

const $ = (id) => document.getElementById(id);
const state = { meta: null, clips: [], current: null, view: initialView() };

const STANCE = {
  dwelling_or_romanticising: 'Dwelling / romanticising',
  neutral_or_informational: 'Neutral / informational',
  coping_or_recovery: 'Coping / recovery',
  unrelated: 'Unrelated',
};
const STAGE = {
  queued: 'Queued…', cached: 'Loaded from cache', describing: 'Watching the video…',
  scoring: 'Scoring DSM-5 themes…', embedding: 'Embedding the text package…', done: 'Done',
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
  return response.json();
}

function initialView() {
  return new URLSearchParams(location.search).get('view') === 'sem' ? 'sem' : 'aff';
}

function setStatus(text, isError = false) {
  $('status').textContent = text;
  $('status').className = isError ? 'err' : '';
}

// ---------------------------------------------------------------- loading

async function init() {
  state.meta = await api('/api/meta');
  renderMode();
  renderToggle();
  await refreshClips();
  const id = location.hash.slice(1) || state.clips.at(-1)?.id;
  if (id) await select(id);
}

async function refreshClips() {
  state.clips = await api('/api/clips');
  renderList();
  renderMap();
}

async function select(id) {
  try { state.current = await api(`/api/clips/${id}`); } catch { return; }
  location.hash = id;
  renderList();
  renderVideo();
  renderPackage();
  renderMap();
  renderScores();
}

// ---------------------------------------------------------------- header and list

function renderMode() {
  const { analyser } = state.meta;
  $('mode').textContent = analyser.mock ? 'MOCK mode, no API calls' : `Gemini: ${analyser.name}`;
  $('mode').classList.toggle('mock', analyser.mock);
}

function renderList() {
  const isCurrent = (c) => state.current?.id === c.id;
  $('list').innerHTML = state.clips.map((c) =>
    `<button type="button" data-id="${c.id}" class="${isCurrent(c) ? 'on' : ''}" title="${esc(c.title)}">${esc(c.title)}</button>`).join('');
  [...$('list').children].forEach((b) => { b.onclick = () => select(b.dataset.id); });
}

// ---------------------------------------------------------------- panels 1 and 2

function renderVideo() {
  const { id, url } = state.current;
  $('video').innerHTML = `<div class="video"><iframe src="https://www.youtube.com/embed/${id}?rel=0&playsinline=1" title="Original video" allow="autoplay; encrypted-media; picture-in-picture" allowfullscreen></iframe></div>
    <p class="note"><a href="${esc(url)}" target="_blank" rel="noopener">${esc(url)}</a></p>`;
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
  $('map').innerHTML = frame() + layer.axes + dots(layer.points);
  $('mapnote').innerHTML = `${layer.note}<br>${LEGEND}`;
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
  const empty = points.length < 2 ? `<text x="${GEO.L + GEO.PW / 2}" y="${GEO.T + GEO.PH / 2}" text-anchor="middle">Analyse at least 2 clips to see the semantic map</text>` : '';
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

// ---------------------------------------------------------------- analysing

async function onSubmit(event) {
  event.preventDefault();
  const url = $('url').value.trim();
  if (!url) return setStatus('Paste a YouTube URL first.', true);
  try {
    const job = await api('/api/analyze', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url, force: $('force').checked }) });
    setStatus(STAGE.queued);
    poll(job.job);
  } catch (error) { setStatus(error.message, true); }
}

async function poll(jobId) {
  const status = await api(`/api/jobs/${jobId}`);
  if (status.stage === 'error') return setStatus(status.error, true);
  setStatus(STAGE[status.stage] || status.stage);
  if (status.stage !== 'done') return setTimeout(() => poll(jobId), 800);
  await refreshClips();
  await select(status.id);
  $('url').value = '';
}

$('f').onsubmit = onSubmit;
$('url').oninput = () => setStatus($('status').textContent);
$('tAff').onclick = () => setView('aff');
$('tSem').onclick = () => setView('sem');
init().catch((error) => { console.error(error); setStatus(`Server not reachable: ${error.message}`, true); });
