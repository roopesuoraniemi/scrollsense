'use strict';

const $ = (id) => document.getElementById(id);
const POLL_MS = 2000;
const GEO = { W: 380, H: 340, L: 44, T: 16, PW: 318, PH: 286 };

const STANCE = {
  dwelling_or_romanticising: 'Dwelling / romanticising',
  neutral_or_informational: 'Neutral / informational',
  coping_or_recovery: 'Coping / recovery',
  unrelated: 'Unrelated',
};

const CLUSTER_LABELS = {
  sleep_fatigue: {
    title: 'Sleep & circadian',
    subtitle: 'A4 sleep, A6 fatigue, nocturnal 00–05h scrolling',
    keys: ['a4_sleep', 'a6_fatigue', 'night_share'],
  },
  anhedonia_hopelessness: {
    title: 'Anhedonia & narrowing',
    subtitle: 'A1 mood, A2 anhedonia, calm-negative pull, topic contraction',
    keys: ['a1_depressed_mood', 'a2_anhedonia', 'low_arousal_negative_share', 'format_entropy', 'semantic_dispersion'],
  },
  worthlessness_guilt: {
    title: 'Worthlessness & self-blame',
    subtitle: 'A7 worthlessness / guilt dwelling share',
    keys: ['a7_worthlessness_guilt'],
  },
};

const METRIC_SPEC = [
  { key: 'mean_valence', label: 'Mean viewer valence (1–5)', kind: 'scale5', threshold: -0.5 },
  { key: 'low_arousal_negative_share', label: 'Calm-negative quadrant (val ≤ 2, aro ≤ 2)', kind: 'pct', threshold: 0.15 },
  { key: 'dwell_negative_share', label: 'Dwell-weighted negative watch share', kind: 'pct', threshold: 0.20 },
  { key: 'negative_share', label: 'Unweighted negative clip share', kind: 'pct', threshold: 0.15 },
  { key: 'semantic_dispersion', label: 'Semantic topic dispersion (embeddings)', kind: 'pct', threshold: -0.12 },
  { key: 'format_entropy', label: 'Format diversity (Shannon entropy)', kind: 'pct', threshold: -0.15 },
  { key: 'night_share', label: 'Nocturnal scrolling (00:00–05:00 local)', kind: 'pct', threshold: 0.15 },
  { key: 'a1_depressed_mood', label: 'A1 Depressed mood (dwelling ≥ 2)', kind: 'pct', threshold: 0.15 },
  { key: 'a2_anhedonia', label: 'A2 Anhedonia (dwelling ≥ 2)', kind: 'pct', threshold: 0.15 },
  { key: 'a4_sleep', label: 'A4 Sleep / insomnia (dwelling ≥ 2)', kind: 'pct', threshold: 0.15 },
  { key: 'a6_fatigue', label: 'A6 Fatigue / exhaustion (dwelling ≥ 2)', kind: 'pct', threshold: 0.15 },
  { key: 'a7_worthlessness_guilt', label: 'A7 Worthlessness / guilt (dwelling ≥ 2)', kind: 'pct', threshold: 0.15 },
];

const state = {
  meta: null,
  token: loadInitialToken(),
  viewer: null,
  control: loadStored('scrollsense.control', '__auto__'),
  windowPreset: loadStored('scrollsense.window', '24h'),
  tab: initialTab(),
  view: initialMapView(),
  follow: true,
  viewers: [],
  feed: [],
  clips: [],
  readoutView: null,
  queue: null,
  current: null,
  evidenceFilter: null, // null | { label, keys: Set<string> }
  signature: '',
  pollTimer: null,
  customAnchors: loadCustomAnchors(),
};

function esc(text) {
  return String(text ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

function loadStored(key, fallback = '') {
  try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; }
}

function saveStored(key, value) {
  try { localStorage.setItem(key, value); } catch { /* convenience only */ }
}

function loadCustomAnchors() {
  try {
    const parsed = JSON.parse(localStorage.getItem('scrollsense.anchors') || '[]');
    return Array.isArray(parsed) ? parsed.slice(0, 6) : [];
  } catch {
    return [];
  }
}

function loadInitialToken() {
  const params = new URLSearchParams(location.search);
  const fromUrl = params.get('token');
  if (fromUrl !== null) {
    params.delete('token');
    const q = params.toString();
    history.replaceState(null, '', location.pathname + (q ? `?${q}` : '') + location.hash);
    saveStored('scrollsense.token', fromUrl);
    return fromUrl;
  }
  return loadStored('scrollsense.token', '');
}

function initialMapView() {
  return new URLSearchParams(location.search).get('view') === 'sem' ? 'sem' : 'aff';
}

function initialTab() {
  return new URLSearchParams(location.search).get('tab') === 'loop' ? 'loop' : 'inspect';
}

function applySavedTheme() {
  const saved = loadStored('scrollsense.theme', '');
  if (saved === 'light' || saved === 'dark') {
    document.documentElement.setAttribute('data-theme', saved);
  }
}

function toggleTheme() {
  const root = document.documentElement;
  const current = root.getAttribute('data-theme');
  const prefersDark = matchMedia('(prefers-color-scheme: dark)').matches;
  const isDark = current ? current === 'dark' : prefersDark;
  const next = isDark ? 'light' : 'dark';
  root.setAttribute('data-theme', next);
  saveStored('scrollsense.theme', next);
}

async function api(path, options = {}) {
  const headers = {
    ...(options.headers || {}),
    ...(state.token ? { Authorization: `Bearer ${state.token}` } : {}),
  };
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401) {
    openPairModal(true);
    throw new Error('Bearer token required — enter SCROLLSENSE_TOKEN');
  }
  if (response.status === 204) return null;
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || response.statusText);
  }
  return response.json();
}

function setStatus(text, isError = false) {
  const el = $('status');
  el.textContent = text;
  el.className = isError ? 'err' : '';
}

// ---------------------------------------------------------------- lifecycle & polling

async function init() {
  applySavedTheme();
  $('windowPreset').value = state.windowPreset;
  renderTabState();
  renderMapToggle();
  state.meta = await api('/api/meta');
  renderModeBadge();
  await refreshAll(true);
  if (!state.pollTimer) {
    state.pollTimer = setInterval(() => refreshAll(false).catch((err) => setStatus(err.message, true)), POLL_MS);
  }
}

async function refreshAll(initial = false) {
  const [viewers, queue] = await Promise.all([api('/api/viewers'), api('/api/queue')]);
  state.viewers = viewers;
  state.queue = queue;
  renderQueueBadge();
  syncViewerSelectors();

  if (!state.viewer) {
    state.feed = [];
    state.clips = [];
    state.readoutView = null;
    setStatus('No viewer logs yet — pair a phone, paste a Shorts URL, or click Sample feed.');
    renderStream();
    renderMap();
    renderGlobalSafety();
    renderLoopView();
    return;
  }

  const feed = await api(`/api/viewers/${encodeURIComponent(state.viewer)}/feed?limit=120`);
  const readoutQuery = buildReadoutQuery(feed);
  const ctrlName = effectiveControl() || '';
  const ctrlSummary = state.viewers.find((v) => v.viewer === ctrlName);
  const sig = [
    state.viewer,
    ctrlName,
    ctrlSummary ? `${ctrlSummary.events}:${ctrlSummary.last_seen ?? 0}` : '',
    state.windowPreset,
    queue.depth,
    queue.in_flight,
    queue.done,
    queue.failed,
    feed.map((i) => `${i.event.event_id}:${i.state}:${i.live ? 1 : 0}`).join('|'),
  ].join('::');

  if (!initial && sig === state.signature) return;
  state.signature = sig;
  state.feed = feed;
  state.clips = uniqueScoredClips(feed);
  state.readoutView = await api(`/api/viewers/${encodeURIComponent(state.viewer)}/readout${readoutQuery}`);

  updateStatusLine();
  renderStream();
  renderMap();
  renderGlobalSafety();
  renderLoopView();
  await syncSelectedClip(initial);
}

function storedViewer() {
  const fromUrl = new URLSearchParams(location.search).get('viewer');
  return fromUrl || loadStored('scrollsense.viewer', '');
}

function syncViewerSelectors() {
  const names = state.viewers.map((v) => v.viewer);
  const newest = [...state.viewers].sort((a, b) => (b.last_seen ?? 0) - (a.last_seen ?? 0))[0];
  const preferred = storedViewer();
  if (!state.viewer || !names.includes(state.viewer)) {
    state.viewer = names.includes(preferred) ? preferred : (newest?.viewer ?? null);
  }

  $('viewer').innerHTML = state.viewers.length
    ? state.viewers.map((v) => {
        const liveMark = v.watching ? ' ● live' : '';
        return `<option value="${esc(v.viewer)}" ${v.viewer === state.viewer ? 'selected' : ''}>${esc(v.viewer)} (${v.events})${liveMark}</option>`;
      }).join('')
    : '<option value="">(no viewers)</option>';

  const others = state.viewers.filter((v) => v.viewer !== state.viewer);
  const chosenCtrl = effectiveControl();
  $('control').innerHTML = [
    `<option value="" ${!chosenCtrl ? 'selected' : ''}>None</option>`,
    ...others.map((v) => `<option value="${esc(v.viewer)}" ${v.viewer === chosenCtrl ? 'selected' : ''}>${esc(v.viewer)} (${v.events})</option>`),
  ].join('');
}

function effectiveControl() {
  const others = state.viewers.map((v) => v.viewer).filter((n) => n !== state.viewer);
  if (state.control === '__auto__') {
    return others.find((n) => n.startsWith('control')) || '';
  }
  return others.includes(state.control) ? state.control : '';
}

function buildReadoutQuery(feed) {
  const params = new URLSearchParams();
  const ctrl = effectiveControl();
  if (ctrl) params.set('control', ctrl);

  const now = Math.floor(Date.now() / 1000);
  if (state.windowPreset === '2h') {
    const cut = now - 7200;
    params.set('from', String(cut));
    params.set('to', String(now + 60));
    params.set('baseline_from', '0');
    params.set('baseline_to', String(cut));
  } else if (state.windowPreset === 'split' && feed.length >= 2) {
    const times = feed.filter((f) => !f.live).map((f) => f.event.seen_at).sort((a, b) => a - b);
    if (times.length >= 2) {
      const mid = times[Math.floor(times.length / 2)];
      params.set('from', String(mid));
      params.set('to', String(Math.max(now, times.at(-1)) + 60));
      params.set('baseline_from', '0');
      params.set('baseline_to', String(mid));
    }
  }
  const qs = params.toString();
  return qs ? `?${qs}` : '';
}

function uniqueScoredClips(feed) {
  const byId = new Map();
  for (const item of feed) {
    if (item.state === 'scored' && item.clip && !byId.has(item.clip.id)) {
      byId.set(item.clip.id, item.clip);
    }
  }
  return [...byId.values()];
}

function uniqueFeedItems() {
  const seen = new Set();
  return state.feed.filter((item) => {
    const key = item.event.video_id;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function updateStatusLine() {
  const items = uniqueFeedItems();
  const scored = items.filter((i) => i.state === 'scored').length;
  const waiting = items.filter((i) => i.state === 'queued').length;
  const liveCount = state.feed.some((i) => i.live) ? ' · watching live on phone' : '';
  setStatus(`${items.length} unique Shorts (${state.feed.length} views) · ${scored} scored · ${waiting} queued${liveCount}`);
}

async function syncSelectedClip(initial) {
  const hashId = initial ? location.hash.replace(/^#/, '') : '';
  if (hashId && state.feed.some((f) => f.event.video_id === hashId)) {
    return selectClip(hashId, false);
  }
  const newest = state.feed[0]?.event.video_id;
  if (state.follow && newest && newest !== state.current?.id) {
    return selectClip(newest, false);
  }
  if (!state.current && newest) {
    return selectClip(newest, false);
  }
  if (state.current && !state.current.scores) {
    return selectClip(state.current.id, false);
  }
}

// ---------------------------------------------------------------- header & badges

function renderModeBadge() {
  const { analyser } = state.meta;
  const badge = $('mode');
  badge.textContent = analyser.mock ? 'Mock mode · offline' : `Gemini · ${analyser.name}`;
  badge.classList.toggle('mock', analyser.mock);
}

function renderQueueBadge() {
  const q = state.queue;
  const el = $('queuePill');
  if (!q) return;
  const active = q.in_flight + q.depth;
  if (active > 0) {
    el.textContent = `${q.in_flight} analysing · ${q.depth} waiting`;
    el.classList.add('busy');
  } else if (q.failed > 0) {
    el.textContent = `Idle · ${q.done} done · ${q.failed} failed`;
    el.classList.remove('busy');
  } else {
    el.textContent = `Queue idle · ${q.done} scored`;
    el.classList.remove('busy');
  }
}

function setTab(tab) {
  state.tab = tab === 'loop' ? 'loop' : 'inspect';
  const params = new URLSearchParams(location.search);
  if (state.tab === 'loop') params.set('tab', 'loop'); else params.delete('tab');
  const q = params.toString();
  history.replaceState(null, '', location.pathname + (q ? `?${q}` : '') + location.hash);
  renderTabState();
}

function renderTabState() {
  const isLoop = state.tab === 'loop';
  $('tabInspect').classList.toggle('on', !isLoop);
  $('tabInspect').setAttribute('aria-selected', String(!isLoop));
  $('tabLoop').classList.toggle('on', isLoop);
  $('tabLoop').setAttribute('aria-selected', String(isLoop));
  $('viewInspect').classList.toggle('hidden', isLoop);
  $('viewLoop').classList.toggle('hidden', !isLoop);
}

function setFollow(on) {
  state.follow = Boolean(on);
  $('follow').checked = state.follow;
  if (state.follow) state.signature = '';
}

// ---------------------------------------------------------------- stream filmstrip & clip selection

function formatLocalClock(event) {
  const localSec = ((event.seen_at + 60 * (event.tz_offset_min || 0)) % 86400 + 86400) % 86400;
  const hh = String(Math.floor(localSec / 3600)).padStart(2, '0');
  const mm = String(Math.floor((localSec % 3600) / 60)).padStart(2, '0');
  const isNight = localSec / 3600 < 5;
  return { clock: `${hh}:${mm}`, isNight };
}

function clipColour(clip) {
  if (!clip) return 'var(--muted)';
  if (clip.a9 > 0) return 'var(--danger)';
  if (clip.stance === 'coping_or_recovery') return 'var(--recovery)';
  const pct = Math.round((Math.min(clip.load, 16) / 16) * 100);
  return `color-mix(in srgb, var(--warm-dot) ${pct}%, var(--cool-dot))`;
}

function isCurrentWindowEvent(seenAt) {
  const w = state.readoutView?.windows?.current;
  if (!w) return true;
  return seenAt >= w.start && seenAt < w.end;
}

function isBaselineWindowEvent(seenAt) {
  const w = state.readoutView?.windows?.baseline;
  if (!w) return false;
  return seenAt >= w.start && seenAt < w.end;
}

function renderStream() {
  const container = $('list');
  const items = uniqueFeedItems();
  if (!items.length) {
    container.innerHTML = '';
    return;
  }
  container.innerHTML = items.map((item) => {
    const id = item.event.video_id;
    const isSel = state.current?.id === id;
    const title = item.clip ? item.clip.title.replace(/^\[MOCK\]\s*/, '') : id;
    const dwell = item.event.dwell_s != null ? `${Math.round(item.event.dwell_s)}s` : '';
    const loops = (item.event.loops || 0) > 0 ? ` · ${item.event.loops}↻` : '';
    const { clock, isNight } = formatLocalClock(item.event);
    const indicator = item.live
      ? '<span class="live-dot" title="Open on phone now"></span>'
      : `<span class="dot" style="background:${clipColour(item.clip)}"></span>`;
    const stateTag = item.state === 'failed' ? '✗ ' : (item.state !== 'scored' ? '… ' : '');
    const nightTag = isNight ? `☾${clock}` : clock;
    return `<button type="button" data-id="${esc(id)}" class="clip-pill ${isSel ? 'on' : ''} ${esc(item.state)} ${item.live ? 'live' : ''}" title="${esc(title)} (${nightTag})">
      ${indicator}
      <span class="clip-title">${stateTag}${esc(title)}</span>
      <span class="clip-meta">${esc(dwell)}${esc(loops)}</span>
    </button>`;
  }).join('');

  container.querySelectorAll('[data-id]').forEach((btn) => {
    btn.onclick = () => selectClip(btn.dataset.id, true);
  });
}

async function selectClip(id, manual = true) {
  if (manual) {
    setFollow(false);
    history.replaceState(null, '', location.pathname + location.search + `#${id}`);
  }
  const changed = id !== state.current?.id;
  if (changed) {
    state.current = { id };
    renderVideoPanel();
  }
  $('btnRerun').classList.remove('hidden');
  try {
    state.current = await api(`/api/clips/${encodeURIComponent(id)}`);
    if (!changed) renderVideoExposureMeta();
    renderPackagePanel();
    renderScoresPanel();
  } catch {
    renderPendingPanels(id);
  }
  renderStream();
  renderMap();
  renderGlobalSafety();
}

function renderPendingPanels(id) {
  const item = state.feed.find((entry) => entry.event.video_id === id);
  if (item?.state === 'failed') {
    const html = `<div class="empty-state">
      Analysis failed: <span class="mono">${esc(item.error || 'unknown error')}</span>
      <div class="empty-actions"><button type="button" class="primary" data-retry="${esc(id)}">Retry analysis</button></div>
    </div>`;
    $('pkg').innerHTML = html;
    $('dsm').innerHTML = html;
    document.querySelectorAll('[data-retry]').forEach((b) => {
      b.onclick = () => rerunClip(b.dataset.retry);
    });
    return;
  }
  const msg = item?.live
    ? 'Watching live on phone — Gemini is describing and scoring this Short now…'
    : 'Queued in background worker — scoring will appear automatically…';
  $('pkg').innerHTML = `<div class="empty-state">${esc(msg)}</div>`;
  $('dsm').innerHTML = `<div class="empty-state">${esc(msg)}</div>`;
}

// ---------------------------------------------------------------- Inspector Panels 1–4

function renderVideoPanel() {
  const id = state.current?.id;
  if (!id) return;
  const shortUrl = `https://www.youtube.com/shorts/${encodeURIComponent(id)}`;
  $('video').innerHTML = `
    <div class="video-frame">
      <iframe src="https://www.youtube.com/embed/${encodeURIComponent(id)}?rel=0&playsinline=1&autoplay=1&mute=1&loop=1&playlist=${encodeURIComponent(id)}"
              title="Watched YouTube Short"
              allow="autoplay; encrypted-media; picture-in-picture"
              allowfullscreen></iframe>
    </div>
    <div id="videoMeta"></div>
    <p class="note"><a href="${shortUrl}" target="_blank" rel="noopener">${esc(shortUrl)}</a></p>`;
  renderVideoExposureMeta();
}

function renderVideoExposureMeta() {
  const holder = $('videoMeta');
  if (!holder || !state.current?.id) return;
  const matching = state.feed.filter((f) => f.event.video_id === state.current.id);
  if (!matching.length) {
    holder.innerHTML = '';
    return;
  }
  const latest = matching[0];
  const ev = latest.event;
  const { clock, isNight } = formatLocalClock(ev);
  const inNow = isCurrentWindowEvent(ev.seen_at);
  const chips = [
    `<span class="chip">${inNow ? 'Current window' : 'Baseline window'}</span>`,
    `<span class="chip ${isNight ? 'night' : ''}">${isNight ? 'Nocturnal ' : 'Local '}${esc(clock)}</span>`,
  ];
  if (ev.dwell_s != null) chips.push(`<span class="chip">Dwell ${ev.dwell_s.toFixed(1)}s</span>`);
  if (ev.duration_s) {
    const pct = Math.min(100, Math.round(((ev.dwell_s || 0) / ev.duration_s) * 100));
    chips.push(`<span class="chip">${pct}% of ${Math.round(ev.duration_s)}s</span>`);
  }
  if ((ev.loops || 0) > 0) chips.push(`<span class="chip">${ev.loops}× loop</span>`);
  if (matching.length > 1) chips.push(`<span class="chip">Shown ${matching.length}×</span>`);
  holder.innerHTML = `<div class="chips" style="margin-top:10px">${chips.join('')}</div>`;
}

function pkgField(pkg, key, label, scroll = false) {
  const val = pkg[key];
  const body = val ? esc(val) : '<span style="color:var(--muted)">(none)</span>';
  return `<dt>${esc(label)}</dt><dd class="${scroll ? 'scroll' : ''}">${body}</dd>`;
}

function renderPackagePanel() {
  const { package: p, analyser } = state.current;
  const mockNote = analyser.mock
    ? '<div class="mock-notice">Offline mock archetype — set GEMINI_API_KEY in .env for live multimodal video analysis.</div>'
    : '';
  $('pkg').innerHTML = `${mockNote}
    <div style="font-weight:600;font-size:15.5px">${esc(p.title)}</div>
    <div class="chips">
      <span class="chip">${esc(p.format.replace(/_/g, ' '))}</span>
      <span class="chip">${p.people_present ? 'People shown' : 'No people shown'}</span>
      <span class="chip">Lang: ${esc(p.language)}</span>
    </div>
    <dl class="pkg-dl">
      ${pkgField(p, 'main_message', 'Main message')}
      ${pkgField(p, 'intended_meaning', 'Intended meaning & subtext')}
      ${pkgField(p, 'emotional_cues', 'Content affect cues')}
      ${pkgField(p, 'transcript', 'Spoken transcript', true)}
      ${pkgField(p, 'on_screen_text', 'On-screen text', true)}
      ${pkgField(p, 'visual_description', 'Visuals')}
      ${pkgField(p, 'audio_description', 'Audio')}
    </dl>
    <p class="note">Stage 1 (${esc(analyser.name)}) describes published media attributes only — forbidden from inferring emotions or mental state of creators (EU AI Act Art. 50(3)).</p>`;
}

function renderScoresPanel() {
  const { scores: s, load, valence } = state.current;
  const stanceCls = s.stance === 'coping_or_recovery' ? 'recovery' : (s.stance === 'dwelling_or_romanticising' ? 'dwelling' : '');
  const a9Inline = s.a9_death_suicide > 0
    ? `<div class="safety-card" style="margin-bottom:10px">
         <h3>Safety path triggered (A9 = ${s.a9_death_suicide}/3)</h3>
         <div style="font-size:13px">Death or self-harm themes are never folded into a score trend. In deployment this routes directly to crisis resources and clinician safety protocol.</div>
       </div>`
    : '';
  const rows = state.meta.criteria.map((c) => {
    const val = s[c.key];
    const segs = [1, 2, 3].map((i) => `<i class="${val >= i ? 'f' : ''}"></i>`).join('');
    return `<div class="dsm-row ${c.code === 'A9' ? 'a9' : ''}" title="${esc(c.theme)}">
      <span class="code">${esc(c.code)}</span>
      <span>${esc(c.label)}</span>
      <span class="seg-bar">${segs}</span>
      <span class="mono" style="text-align:right">${val}</span>
    </div>`;
  }).join('');

  $('dsm').innerHTML = `${a9Inline}
    <div class="load-summary">
      <b>${load}</b>
      <span style="color:var(--muted)">/ 27 content theme load (sum of A1–A9)</span>
    </div>
    <div class="chips" style="margin-bottom:10px">
      <span class="chip ${stanceCls}">Stance: ${esc(STANCE[s.stance] || s.stance)}</span>
      <span class="chip" title="Derived from positive minus negative viewer affect">Valence ${valence}/5</span>
      <span class="chip">Arousal ${s.arousal}/5</span>
      <span class="chip">Neg ${s.negative_affect}/3 · Pos ${s.positive_affect}/3</span>
      <span class="chip ${s.hopeful ? 'recovery' : ''}">${s.hopeful ? 'Hopeful' : 'Not hopeful'}</span>
    </div>
    ${rows}
    <blockquote class="evidence-quote">${esc(s.evidence)}</blockquote>
    <p class="note"><strong>Rationale:</strong> ${esc(s.rationale)}</p>
    <p class="note">Scale: 0 absent · 1 mentioned · 2 central · 3 intense. Quantifies media exposure themes, not a clinical diagnosis.</p>`;
}

// ---------------------------------------------------------------- Embedded Space SVG (Affect & Semantic + Drift Vector)

function setMapView(view) {
  state.view = view === 'sem' ? 'sem' : 'aff';
  renderMapToggle();
  renderMap();
}

function renderMapToggle() {
  $('tAff').classList.toggle('on', state.view === 'aff');
  $('tSem').classList.toggle('on', state.view === 'sem');
}

const affectX = (v) => GEO.L + ((v - 0.5) / 5) * GEO.PW;
const affectY = (a) => GEO.T + GEO.PH - ((a - 0.5) / 5) * GEO.PH;
const semX = (x) => GEO.L + GEO.PW / 2 + x * GEO.PW * 0.43;
const semY = (y) => GEO.T + GEO.PH / 2 - y * GEO.PH * 0.43;

function hashInt(text) {
  let h = 0;
  for (const ch of text) h = (h * 31 + ch.charCodeAt(0)) | 0;
  return Math.abs(h);
}

function windowMembershipByClip() {
  const tallies = new Map(); // clipId -> { baseline: dwellOrCount, current: dwellOrCount }
  for (const item of state.feed) {
    const id = item.event.video_id;
    const weight = Math.max(0.5, item.event.dwell_s ?? 1.0);
    const entry = tallies.get(id) || { baseline: 0, current: 0 };
    if (isCurrentWindowEvent(item.event.seen_at)) {
      entry.current += weight;
    } else if (isBaselineWindowEvent(item.event.seen_at)) {
      entry.baseline += weight;
    }
    tallies.set(id, entry);
  }
  const membership = new Map();
  for (const [id, entry] of tallies) {
    membership.set(id, entry.current >= entry.baseline ? 'current' : 'baseline');
  }
  return membership;
}

function centroidOf(coords) {
  if (!coords.length) return null;
  const sx = coords.reduce((acc, p) => acc + p.x, 0) / coords.length;
  const sy = coords.reduce((acc, p) => acc + p.y, 0) / coords.length;
  return { x: sx, y: sy };
}

function exposureCentroids(coordByClipId) {
  const baseCoords = [];
  const currCoords = [];
  for (const item of state.feed) {
    if (item.live || item.state !== 'scored') continue;
    const coord = coordByClipId.get(item.event.video_id);
    if (!coord) continue;
    if (isCurrentWindowEvent(item.event.seen_at)) {
      currCoords.push(coord);
    } else if (isBaselineWindowEvent(item.event.seen_at)) {
      baseCoords.push(coord);
    }
  }
  return { base: centroidOf(baseCoords), curr: centroidOf(currCoords) };
}

function renderDriftVector(points) {
  const coordByClipId = new Map(points.map((p) => [p.clip.id, { x: p.rawX, y: p.rawY }]));
  const { base, curr } = exposureCentroids(coordByClipId);
  const b = base || centroidOf(points.filter((p) => p.window === 'baseline').map((p) => ({ x: p.rawX, y: p.rawY })));
  const c = curr || centroidOf(points.filter((p) => p.window === 'current').map((p) => ({ x: p.rawX, y: p.rawY })));
  if (!b || !c) return '';
  const dx = c.x - b.x;
  const dy = c.y - b.y;
  if (Math.hypot(dx, dy) < 6) return '';
  return `<defs>
      <marker id="driftArrow" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 1 L 10 5 L 0 9 z" fill="var(--accent)"/>
      </marker>
    </defs>
    <circle cx="${b.x.toFixed(1)}" cy="${b.y.toFixed(1)}" r="4" fill="none" stroke="var(--muted)" stroke-dasharray="2 2"/>
    <line x1="${b.x.toFixed(1)}" y1="${b.y.toFixed(1)}" x2="${c.x.toFixed(1)}" y2="${c.y.toFixed(1)}"
          stroke="var(--accent)" stroke-width="2" stroke-dasharray="4 3" marker-end="url(#driftArrow)" opacity="0.88"/>`;
}

function renderMap() {
  const membership = windowMembershipByClip();
  const isAff = state.view === 'aff';
  const layer = isAff ? buildAffectLayer(membership) : buildSemanticLayer(membership);
  const frame = `<rect x="${GEO.L}" y="${GEO.T}" width="${GEO.PW}" height="${GEO.PH}" rx="4" fill="var(--surface-2)" fill-opacity="0.35" stroke="var(--line)"/>`;
  const midY = GEO.T + GEO.PH / 2;
  const titles = `<text x="${GEO.L + GEO.PW / 2}" y="${GEO.H - 4}" text-anchor="middle">${esc(layer.xLabel)}</text>
    <text x="13" y="${midY}" transform="rotate(-90 13 ${midY})" text-anchor="middle">${esc(layer.yLabel)}</text>`;

  const sortedPts = [...layer.points].sort((a, b) => (state.current?.id === a.clip.id) - (state.current?.id === b.clip.id));
  const dotsSvg = sortedPts.map((pt) => renderMapDot(pt, state.current?.id === pt.clip.id)).join('');
  $('map').innerHTML = frame + layer.grid + renderDriftVector(layer.points) + dotsSvg + titles;
  $('mapnote').innerHTML = `${layer.note}<br><span style="display:inline-block;margin-top:3px">Filled = current window · Hollow = baseline · Dashed arrow = baseline → current centroid shift · Green halo = coping/recovery</span>`;

  $('map').querySelectorAll('[data-id]').forEach((g) => {
    g.onclick = () => selectClip(g.dataset.id, true);
  });
}

function buildAffectLayer(membership) {
  const { L, T, PW, PH } = GEO;
  const lowQuadW = affectX(2.5) - L;
  const lowQuadY = affectY(2.5);
  const lowQuadH = T + PH - lowQuadY;
  const dysphoricShade = `<rect x="${L + 1}" y="${lowQuadY}" width="${lowQuadW}" height="${lowQuadH - 1}" fill="var(--watch-soft)" opacity="0.45"/>`;
  const cross = `<line x1="${affectX(3)}" y1="${T}" x2="${affectX(3)}" y2="${T + PH}" stroke="var(--line)" stroke-dasharray="3 3"/>
    <line x1="${L}" y1="${affectY(3)}" x2="${L + PW}" y2="${affectY(3)}" stroke="var(--line)" stroke-dasharray="3 3"/>`;
  const ticks = [1, 2, 3, 4, 5].map((i) => (
    `<text x="${affectX(i)}" y="${T + PH + 14}" text-anchor="middle">${i}</text>
     <text x="${L - 7}" y="${affectY(i) + 4}" text-anchor="end">${i}</text>`
  )).join('');
  const quads = `<text x="${L + 7}" y="${T + 14}">tense · negative</text>
    <text x="${L + PW - 7}" y="${T + 14}" text-anchor="end">lively · positive</text>
    <text x="${L + 7}" y="${T + PH - 7}">calm · negative (low arousal)</text>
    <text x="${L + PW - 7}" y="${T + PH - 7}" text-anchor="end">calm · positive</text>`;

  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  const jitter = (n) => ((n % 13) - 6) * 2.1;
  const points = state.clips.map((clip) => {
    const h = hashInt(clip.id);
    const rawX = affectX(clip.valence);
    const rawY = affectY(clip.arousal);
    return {
      clip,
      window: membership.get(clip.id) || 'current',
      rawX,
      rawY,
      x: clamp(rawX + jitter(h), L + 10, L + PW - 10),
      y: clamp(rawY + jitter(h >> 4), T + 10, T + PH - 10),
    };
  });

  return {
    grid: dysphoricShade + cross + ticks + quads,
    xLabel: 'Viewer valence (1 negative → 5 positive)',
    yLabel: 'Arousal (1 still → 5 intense)',
    points,
    note: 'Russell circumplex from Stage-2 affect & arousal scores. Shaded bottom-left quadrant marks low-valence, low-arousal withdrawal pull.',
  };
}

function buildSemanticLayer(membership) {
  const { L, T, PW, PH } = GEO;
  const embedded = state.clips.filter((c) => c.semantic);
  const cross = `<line x1="${L + PW / 2}" y1="${T}" x2="${L + PW / 2}" y2="${T + PH}" stroke="var(--line)" stroke-dasharray="2 4"/>
    <line x1="${L}" y1="${T + PH / 2}" x2="${L + PW}" y2="${T + PH / 2}" stroke="var(--line)" stroke-dasharray="2 4"/>`;
  const empty = embedded.length < 2
    ? `<text x="${L + PW / 2}" y="${T + PH / 2}" text-anchor="middle">Score at least 2 Shorts to project semantic space</text>`
    : '';
  const points = embedded.map((clip) => {
    const x = semX(clip.semantic.x);
    const y = semY(clip.semantic.y);
    return { clip, window: membership.get(clip.id) || 'current', rawX: x, rawY: y, x, y };
  });
  const disp = state.readoutView?.current?.semantic_dispersion;
  const dispText = disp != null ? ` Current window semantic dispersion: ${(disp * 100).toFixed(0)}%.` : '';
  return {
    grid: cross + empty,
    xLabel: 'Principal component 1',
    yLabel: 'Principal component 2',
    points,
    note: `Viewer-scoped 2-D PCA of text-package embeddings (${esc(state.meta?.analyser?.embed_name || 'embed')}). Tight clustering indicates filter-bubble narrowing.${dispText}`,
  };
}

function renderMapDot(pt, isSelected) {
  const { clip, x, y, window: win } = pt;
  const col = clipColour(clip);
  const r = isSelected ? 8 : 5.8;
  const selectRing = isSelected
    ? `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="13" fill="none" stroke="var(--accent)" stroke-width="2"/>`
    : '';
  const recoveryHalo = clip.stance === 'coping_or_recovery'
    ? `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${r + 3.2}" fill="none" stroke="var(--recovery)" stroke-width="1.5"/>`
    : '';
  const body = win === 'baseline'
    ? `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${r}" fill="var(--surface)" stroke="${col}" stroke-width="2.2" opacity="${isSelected ? 1 : 0.78}"/>`
    : `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${r}" fill="${col}" stroke="var(--surface)" stroke-width="1.5" opacity="${isSelected ? 1 : 0.9}"/>`;
  return `<g data-id="${esc(clip.id)}" style="cursor:pointer">
    <title>${esc(clip.title)} · ${win} · valence ${clip.valence}/5 · arousal ${clip.arousal}/5 · load ${clip.load}/27</title>
    ${selectRing}${recoveryHalo}${body}
  </g>`;
}

// ---------------------------------------------------------------- Global Deterministic A9 Safety Banner

function renderGlobalSafety() {
  const container = $('safetyGlobal');
  const guidance = state.readoutView?.guidance;
  const hits = state.readoutView?.current?.safety_hits || [];
  if (!guidance?.safety_active || !hits.length) {
    container.classList.add('hidden');
    container.innerHTML = '';
    return;
  }
  const resources = guidance.crisis_resources.map((r) => `
    <div class="crisis-item">
      <div>${esc(r.label)}</div>
      <strong>${esc(r.contact)}</strong>
      <div style="color:var(--muted);font-size:12px">${esc(r.detail)}</div>
    </div>`).join('');
  const hitLinks = hits.map((h) => (
    `<button type="button" data-jump="${esc(h.video_id)}">Inspect ${esc(h.video_id)}</button>`
  )).join(' ');

  container.classList.remove('hidden');
  container.innerHTML = `<div class="safety-card">
    <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap">
      <h3>${esc(guidance.headline)}</h3>
      <div>${hitLinks}</div>
    </div>
    <div style="font-size:13px">${esc(guidance.clinical_note)}</div>
    <div class="crisis-grid">${resources}</div>
  </div>`;

  container.querySelectorAll('[data-jump]').forEach((btn) => {
    btn.onclick = () => {
      setTab('inspect');
      selectClip(btn.dataset.jump, true);
    };
  });
}

// ---------------------------------------------------------------- Tab 2: Longitudinal Drift & Home Loop

function renderLoopView() {
  const rv = state.readoutView;
  if (!rv) {
    $('clusterStrip').innerHTML = '';
    $('metricsTable').innerHTML = '<div class="empty-state">Load or stream viewer Shorts to compute baseline vs current readout.</div>';
    $('trajChart').innerHTML = '';
    $('trajNote').textContent = '';
    $('loopPanel').innerHTML = '<div class="empty-state">No active viewer readout.</div>';
    $('evidenceList').innerHTML = '<div class="empty-state">No current-window exposures yet.</div>';
    return;
  }
  renderClusterStrip(rv);
  renderMetricsComparison(rv);
  renderTrajectoryChart(rv.trajectory);
  renderCompanionLoop(rv.guidance);
  renderEvidenceList(rv);
}

function renderClusterStrip(rv) {
  $('clusterStrip').innerHTML = rv.readout.clusters.map((c) => {
    const meta = CLUSTER_LABELS[c.name] || { title: c.name, subtitle: '', keys: [] };
    const isSelected = state.evidenceFilter?.id === `cluster:${c.name}`;
    const flaggedText = c.flagged.length
      ? `Triggered: ${c.flagged.map(shortMetricName).join(', ')}`
      : 'No threshold crossings vs baseline';
    return `<button type="button" class="cluster-card ${isSelected ? 'selected' : ''}" data-cluster="${esc(c.name)}">
      <div class="cluster-top">
        <span class="cluster-name">${esc(meta.title)}</span>
        <span class="level-badge ${esc(c.level)}">${esc(capitalize(c.level))}</span>
      </div>
      <div style="font-size:12px;color:var(--muted)">${esc(meta.subtitle)}</div>
      <div class="mono" style="font-size:11.5px;color:var(--ink)">${esc(flaggedText)}</div>
    </button>`;
  }).join('');

  $('clusterStrip').querySelectorAll('[data-cluster]').forEach((card) => {
    card.onclick = () => {
      const name = card.dataset.cluster;
      const id = `cluster:${name}`;
      if (state.evidenceFilter?.id === id) {
        state.evidenceFilter = null;
      } else {
        const meta = CLUSTER_LABELS[name];
        state.evidenceFilter = { id, label: meta.title, keys: new Set(meta.keys) };
      }
      renderClusterStrip(rv);
      renderEvidenceList(rv);
    };
  });
}

function fmtMetric(val, kind) {
  if (val == null) return '—';
  if (kind === 'scale5') return `${val.toFixed(2)} / 5`;
  return `${Math.round(val * 100)}%`;
}

function fmtDelta(delta, kind) {
  if (delta == null) return '—';
  const sign = delta > 0 ? '+' : '';
  if (kind === 'scale5') return `${sign}${delta.toFixed(2)}`;
  return `${sign}${Math.round(delta * 100)} pp`;
}

function crosses(delta, threshold) {
  if (delta == null) return false;
  return threshold > 0 ? delta >= threshold - 1e-9 : delta <= threshold + 1e-9;
}

function renderMetricsComparison(rv) {
  const base = rv.baseline;
  const curr = rv.current;
  const flags = new Set(rv.readout.flags);
  const ctrlDeltas = rv.readout.control_deltas;
  const ctrlName = effectiveControl();

  const sameDayHint = base.n_shown === 0 && curr.n_shown >= 4 && state.windowPreset === '24h'
    ? `<div class="mock-notice">All ${curr.n_shown} logged events occurred within the last 24 hours, so the prior baseline window is empty. <button type="button" id="btnSwitchSplit" style="margin-left:6px;padding:2px 8px;font-size:12px">Compare recent half vs earlier</button></div>`
    : '';

  $('windowNote').textContent = `Baseline: ${base.n_scored}/${base.n_shown} scored · Current: ${curr.n_scored}/${curr.n_shown} scored${ctrlName ? ` · Control: ${ctrlName}` : ''}`;

  const baseMetrics = base.theme_share ? { ...base, ...base.theme_share } : base;
  const currMetrics = curr.theme_share ? { ...curr, ...curr.theme_share } : curr;

  const rows = METRIC_SPEC.map((spec) => {
    const bVal = baseMetrics[spec.key];
    const cVal = currMetrics[spec.key];
    const delta = rv.readout.deltas[spec.key];
    const isFlag = flags.has(spec.key);
    const ctrlDelta = ctrlDeltas ? ctrlDeltas[spec.key] : null;
    const suppressed = !isFlag && crosses(delta, spec.threshold) && crosses(ctrlDelta, spec.threshold);
    const badgeCls = isFlag ? 'flagged' : (suppressed ? 'suppressed' : '');
    const statusLabel = isFlag
      ? 'Flagged'
      : (suppressed ? 'In control too (suppressed)' : '');

    return `<tr class="${isFlag ? 'flagged-row' : ''}" data-metric="${esc(spec.key)}" data-label="${esc(spec.label)}">
      <td>${esc(spec.label)}</td>
      <td class="num">${fmtMetric(bVal, spec.kind)}</td>
      <td class="num">${fmtMetric(cVal, spec.kind)}</td>
      <td class="num"><span class="delta-tag ${badgeCls}">${fmtDelta(delta, spec.kind)}</span></td>
      <td style="font-size:12px;color:${isFlag ? 'var(--danger)' : 'var(--muted)'}">${esc(statusLabel)}</td>
    </tr>`;
  }).join('');

  $('metricsTable').innerHTML = `${sameDayHint}
    <div style="overflow-x:auto">
      <table class="metric-table">
        <thead>
          <tr>
            <th>Exposure signal</th>
            <th class="num">Baseline</th>
            <th class="num">Current</th>
            <th class="num">Shift</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;

  const switchBtn = $('btnSwitchSplit');
  if (switchBtn) {
    switchBtn.onclick = () => {
      state.windowPreset = 'split';
      $('windowPreset').value = 'split';
      saveStored('scrollsense.window', 'split');
      state.signature = '';
      refreshAll(false);
    };
  }

  $('metricsTable').querySelectorAll('tr.flagged-row').forEach((row) => {
    row.onclick = () => {
      const key = row.dataset.metric;
      const id = `metric:${key}`;
      state.evidenceFilter = state.evidenceFilter?.id === id
        ? null
        : { id, label: row.dataset.label, keys: new Set([key]) };
      renderClusterStrip(rv);
      renderEvidenceList(rv);
    };
  });
}

function renderTrajectoryChart(series) {
  const svg = $('trajChart');
  const W = 420;
  const H = 190;
  const L = 34;
  const T = 14;
  const PW = 372;
  const PH = 144;
  if (!series || series.length < 2) {
    svg.innerHTML = `<rect x="${L}" y="${T}" width="${PW}" height="${PH}" rx="4" fill="var(--surface-2)" fill-opacity="0.35" stroke="var(--line)"/>
      <text x="${L + PW / 2}" y="${T + PH / 2}" text-anchor="middle">Need at least 2 chronological exposures for trajectory</text>`;
    $('trajNote').textContent = '';
    return;
  }

  const xAt = (i) => L + (i / (series.length - 1)) * PW;
  const yAt = (pct) => T + PH - Math.min(1, Math.max(0, pct)) * PH;

  const polyline = (getter, color, dashed = false) => {
    const pts = series
      .map((pt, idx) => ({ idx, val: getter(pt) }))
      .filter((p) => p.val != null);
    if (pts.length < 2) return '';
    const d = pts.map((p, j) => `${j === 0 ? 'M' : 'L'}${xAt(p.idx).toFixed(1)},${yAt(p.val).toFixed(1)}`).join(' ');
    const dash = dashed ? 'stroke-dasharray="4 3"' : '';
    const dots = pts.map((p) => `<circle cx="${xAt(p.idx).toFixed(1)}" cy="${yAt(p.val).toFixed(1)}" r="2.8" fill="${color}"/>`).join('');
    return `<path d="${d}" fill="none" stroke="${color}" stroke-width="2" ${dash}/>${dots}`;
  };

  const grid = [0, 0.5, 1].map((g) => (
    `<line x1="${L}" y1="${yAt(g)}" x2="${L + PW}" y2="${yAt(g)}" stroke="var(--line)" stroke-dasharray="2 3"/>
     <text x="${L - 5}" y="${yAt(g) + 4}" text-anchor="end">${Math.round(g * 100)}%</text>`
  )).join('');

  const valenceLine = polyline((p) => (p.mean_valence != null ? (p.mean_valence - 1) / 4 : null), 'var(--accent)');
  const dysphoricLine = polyline((p) => p.low_arousal_negative_share, 'var(--danger)');
  const dispersionLine = polyline((p) => p.semantic_dispersion, 'var(--cool-dot)', true);

  svg.innerHTML = `<rect x="${L}" y="${T}" width="${PW}" height="${PH}" rx="4" fill="var(--surface-2)" fill-opacity="0.3" stroke="var(--line)"/>
    ${grid}${dispersionLine}${valenceLine}${dysphoricLine}
    <text x="${L}" y="${H - 6}">Oldest</text>
    <text x="${L + PW}" y="${H - 6}" text-anchor="end">Latest</text>`;

  $('trajNote').innerHTML = `<span style="color:var(--accent);font-weight:600">— Valence</span> · <span style="color:var(--danger);font-weight:600">— Calm-negative share</span> · <span style="color:var(--cool-dot);font-weight:600">- - Semantic dispersion</span>`;
}

function renderCompanionLoop(guidance) {
  const badge = $('triageBadge');
  badge.className = `level-badge ${guidance.triage_level}`;
  badge.textContent = capitalize(guidance.triage_level);

  const resetsHtml = guidance.resets.length
    ? `<div class="reset-list">${guidance.resets.map((r) => `
        <div class="reset-card">
          <h4>${esc(r.title)}</h4>
          <p>${esc(r.summary)}</p>
          <div class="reset-basis">${esc(r.basis)}</div>
        </div>`).join('')}</div>`
    : `<p class="note" style="margin:0">No micro-interventions triggered while feed remains aligned with personal baseline — avoiding reminder fatigue (Astill Wright et al., 2026).</p>`;

  const allAnchors = [...guidance.anchors, ...state.customAnchors];
  const anchorLinks = allAnchors.map((a) => (
    `<a class="anchor-link" href="${esc(a.url)}" target="_blank" rel="noopener" title="Open restorative topic to re-seed minute-level Shorts recommendations">${esc(a.topic)} ↗</a>`
  )).join('');

  $('loopPanel').innerHTML = `
    <div class="triage-banner">
      <h3>${esc(guidance.headline)}</h3>
      <p>${esc(guidance.clinical_note)}</p>
    </div>
    ${resetsHtml}
    <div class="anchor-box">
      <div style="font-size:12.5px;font-weight:600">Comfort-Anchor topics (2-minute recommender re-seed)</div>
      <div class="anchor-links">${anchorLinks}</div>
      <form id="anchorForm" style="display:flex;gap:6px;margin-top:8px">
        <label class="hidden" for="anchorInput">Custom restorative topic</label>
        <input id="anchorInput" type="text" placeholder="Add personal comfort topic (e.g. pottery)…" style="flex:1;font-size:12.5px;padding:4px 8px" aria-label="Custom comfort topic">
        <button type="submit" style="font-size:12.5px;padding:4px 10px">Add anchor</button>
      </form>
    </div>`;

  $('anchorForm').onsubmit = (ev) => {
    ev.preventDefault();
    const topic = $('anchorInput').value.trim();
    if (!topic) return;
    const url = `https://www.youtube.com/results?search_query=${encodeURIComponent(`${topic} calm shorts`)}`;
    state.customAnchors = [...state.customAnchors.filter((a) => a.topic !== topic), { topic, url }].slice(-6);
    saveStored('scrollsense.anchors', JSON.stringify(state.customAnchors));
    renderCompanionLoop(guidance);
  };
}

function renderEvidenceList(rv) {
  const filter = state.evidenceFilter;
  $('evidenceScope').textContent = filter ? filter.label : 'all current exposures';
  $('btnClearFilter').classList.toggle('hidden', !filter);

  const items = filter
    ? rv.evidence.filter((ev) => ev.metrics.some((m) => filter.keys.has(m)))
    : rv.evidence;

  if (!items.length) {
    $('evidenceList').innerHTML = `<div class="empty-state">${
      filter ? 'No current-window clips matched this filter.' : 'No theme-bearing clips in the current window.'
    }</div>`;
    return;
  }

  $('evidenceList').innerHTML = `<div class="evidence-grid">${items.map((ev) => {
    const totalMin = ((Math.round(ev.local_hour * 60) % 1440) + 1440) % 1440;
    const hh = String(Math.floor(totalMin / 60)).padStart(2, '0');
    const mm = String(totalMin % 60).padStart(2, '0');
    const dwell = ev.dwell_s != null ? ` · ${ev.dwell_s.toFixed(1)}s dwell` : '';
    return `<div class="ev-card">
      <div class="ev-head">
        <span class="ev-title">${esc(ev.title.replace(/^\[MOCK\]\s*/, ''))}</span>
        <span class="mono" style="color:var(--muted);font-size:11.5px">${hh}:${mm}${esc(dwell)}</span>
      </div>
      <div class="ev-quote">${esc(ev.quote)}</div>
      <div style="display:flex;justify-content:space-between;align-items:center;gap:6px;margin-top:auto;padding-top:4px">
        <span style="font-size:11.5px;color:var(--muted)">${esc(STANCE[ev.stance] || ev.stance)} · load ${ev.load}/27</span>
        <button type="button" data-evid="${esc(ev.video_id)}" style="font-size:12px;padding:3px 9px">Inspect clip</button>
      </div>
    </div>`;
  }).join('')}</div>`;

  $('evidenceList').querySelectorAll('[data-evid]').forEach((btn) => {
    btn.onclick = () => {
      setTab('inspect');
      selectClip(btn.dataset.evid, true);
    };
  });
}

function shortMetricName(key) {
  const found = METRIC_SPEC.find((m) => m.key === key);
  if (found) return found.label.split(' (')[0];
  return key.replace(/_/g, ' ');
}

function capitalize(s) {
  return s ? s[0].toUpperCase() + s.slice(1) : '';
}

// ---------------------------------------------------------------- Actions: Log URL, Re-analyse, Seed Demo, Erase, Pair Modal

async function logManualUrl(ev) {
  ev.preventDefault();
  const raw = $('urlInput').value.trim();
  if (!raw) return;
  const viewer = state.viewer || 'patient-01';
  const nowSec = Date.now() / 1000;
  try {
    setStatus('Logging Short to viewer feed…');
    await api('/api/views', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        viewer,
        events: [{
          event_id: `manual-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
          url: raw,
          seen_at: nowSec,
          tz_offset_min: -new Date().getTimezoneOffset(),
          dwell_s: 8.0,
          source: 'manual',
          surface: 'shorts',
        }],
      }),
    });
    $('urlInput').value = '';
    state.viewer = viewer;
    setFollow(true);
    state.signature = '';
    await refreshAll(false);
  } catch (err) {
    setStatus(err.message, true);
  }
}

async function rerunClip(videoId) {
  if (!videoId) return;
  try {
    setStatus(`Re-analysing ${videoId}…`);
    const job = await api('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: videoId, force: true }),
    });
    for (let i = 0; i < 80; i += 1) {
      await new Promise((r) => setTimeout(r, 400));
      const status = await api(`/api/jobs/${encodeURIComponent(job.job)}`);
      setStatus(`${videoId}: ${status.stage}…`);
      if (status.stage === 'done') break;
      if (status.stage === 'error') throw new Error(status.error || 'Analysis failed');
    }
    state.signature = '';
    await refreshAll(false);
    await selectClip(videoId, false);
  } catch (err) {
    setStatus(err.message, true);
  }
}

async function seedSampleScenario() {
  const now = Math.floor(Date.now() / 1000);
  const tzMin = 120; // UTC+2 Helsinki
  // Place current events at 02:15 local time within the last 24h so nocturnal drift is realistic.
  const localTodaySec = ((now + tzMin * 60) % 86400 + 86400) % 86400;
  let nightBase = now - localTodaySec + 2 * 3600 + 15 * 60;
  if (nightBase > now - 300) nightBase -= 86400;
  if (nightBase < now - 82800) nightBase = now - 3600;
  let dayNow = now - localTodaySec + 14 * 3600;
  if (dayNow > now - 300) dayNow -= 86400;
  if (dayNow < now - 82800) dayNow = now - 3600;
  const oldDay = now - 2 * 86400 - localTodaySec + 14 * 3600; // 14:00 local two days ago

  const mk = (viewer, vid, seenAt, dwell, dur, loops = 0) => ({
    event_id: `seed-${viewer}-${vid}-${Math.round(seenAt)}`,
    video_id: vid,
    seen_at: seenAt,
    tz_offset_min: tzMin,
    dwell_s: dwell,
    duration_s: dur,
    loops,
    source: 'shorts_web',
    surface: 'shorts',
  });

  const patientEvents = [
    mk('patient-01', 'Qo4PLQXRmUw', oldDay + 0, 9.5, 15, 0),
    mk('patient-01', 'RWD9TXXf1_A', oldDay + 45, 12.0, 14, 1),
    mk('patient-01', 'KOiWuuzGzOw', oldDay + 90, 8.0, 16, 0),
    mk('patient-01', 'jNQXAC9IVRw', oldDay + 140, 11.0, 18, 0),
    mk('patient-01', 'cRftRest001', oldDay + 195, 10.5, 20, 0),
    // Current nocturnal drift window: long dwell + loops on heavy clips, 1.1s skip on light clip, plus 1 peer recovery clip
    mk('patient-01', 'lMQJ2bHeP4c', nightBase + 0, 17.5, 15, 1),
    mk('patient-01', 'wZF2PLGsksI', nightBase + 40, 19.0, 16, 1),
    mk('patient-01', 'Qo4PLQXRmUw', nightBase + 75, 1.1, 15, 0),
    mk('patient-01', 'bPnRMwahAMA', nightBase + 110, 16.0, 14, 1),
    mk('patient-01', 'recovWin001', nightBase + 155, 9.0, 18, 0),
  ];

  const controlEvents = [
    mk('control-01', 'Qo4PLQXRmUw', oldDay + 10, 8.0, 15, 0),
    mk('control-01', 'RWD9TXXf1_A', oldDay + 60, 10.0, 14, 0),
    mk('control-01', 'KOiWuuzGzOw', oldDay + 110, 7.5, 16, 0),
    mk('control-01', 'jNQXAC9IVRw', dayNow + 0, 9.0, 18, 0),
    mk('control-01', 'cRftRest001', dayNow + 60, 11.0, 20, 0),
    mk('control-01', 'RWD9TXXf1_A', dayNow + 120, 8.5, 14, 0),
  ];

  try {
    setStatus('Seeding patient-01 (baseline → nocturnal drift) & control-01…');
    await api('/api/views', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ viewer: 'patient-01', events: patientEvents }),
    });
    await api('/api/views', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ viewer: 'control-01', events: controlEvents }),
    });
    state.viewer = 'patient-01';
    state.control = 'control-01';
    state.windowPreset = '24h';
    $('windowPreset').value = '24h';
    saveStored('scrollsense.viewer', 'patient-01');
    saveStored('scrollsense.control', 'control-01');
    saveStored('scrollsense.window', '24h');
    state.signature = '';
    await refreshAll(false);
  } catch (err) {
    setStatus(err.message, true);
  }
}

async function eraseCurrentViewer() {
  if (!state.viewer) return;
  if (!confirm(`Erase all logged view events for "${state.viewer}"? (Shared anonymous clip analyses stay cached.)`)) return;
  try {
    await api(`/api/viewers/${encodeURIComponent(state.viewer)}`, { method: 'DELETE' });
    state.viewer = null;
    state.current = null;
    state.signature = '';
    await refreshAll(true);
  } catch (err) {
    setStatus(err.message, true);
  }
}

function encodeBase64Url(obj) {
  const utf8 = unescape(encodeURIComponent(JSON.stringify(obj)));
  return btoa(utf8).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function updatePairLinkPreview() {
  const endpoint = $('pairEndpoint').value.trim().replace(/\/+$/, '');
  const token = $('pairToken').value.trim();
  const viewer = ($('pairViewer').value.trim() || 'patient-01').toLowerCase();
  $('scriptInstallLink').href = `${endpoint || location.origin}/scrollsense.user.js`;
  const payload = encodeBase64Url({ endpoint: endpoint || location.origin, token, viewer });
  $('pairLink').value = `https://m.youtube.com/shorts#scrollsense_pair=${payload}`;
}

function openPairModal(focusToken = false) {
  const modal = $('pairModal');
  if (modal.open) return;
  $('pairEndpoint').value = loadStored('scrollsense.endpoint', location.origin);
  $('pairToken').value = state.token;
  $('pairViewer').value = state.viewer || 'patient-01';
  updatePairLinkPreview();
  modal.showModal();
  if (focusToken) $('pairToken').focus();
}

// ---------------------------------------------------------------- Event Wiring

$('viewer').onchange = (e) => {
  state.viewer = e.target.value || null;
  if (state.viewer) saveStored('scrollsense.viewer', state.viewer);
  Object.assign(state, { feed: [], clips: [], readoutView: null, current: null, evidenceFilter: null, signature: '' });
  setFollow(true);
  refreshAll(true).catch((err) => setStatus(err.message, true));
};

$('control').onchange = (e) => {
  state.control = e.target.value || '';
  saveStored('scrollsense.control', state.control);
  state.signature = '';
  refreshAll(false).catch((err) => setStatus(err.message, true));
};

$('windowPreset').onchange = (e) => {
  state.windowPreset = e.target.value;
  saveStored('scrollsense.window', state.windowPreset);
  state.signature = '';
  refreshAll(false).catch((err) => setStatus(err.message, true));
};

$('follow').onchange = (e) => setFollow(e.target.checked);
$('tabInspect').onclick = () => setTab('inspect');
$('tabLoop').onclick = () => setTab('loop');
$('tAff').onclick = () => setMapView('aff');
$('tSem').onclick = () => setMapView('sem');
$('btnTheme').onclick = toggleTheme;
$('urlForm').onsubmit = logManualUrl;
$('btnRerun').onclick = () => rerunClip(state.current?.id);
$('btnSeed').onclick = seedSampleScenario;
$('btnErase').onclick = eraseCurrentViewer;
$('btnClearFilter').onclick = () => {
  state.evidenceFilter = null;
  if (state.readoutView) {
    renderClusterStrip(state.readoutView);
    renderEvidenceList(state.readoutView);
  }
};

$('btnPair').onclick = () => openPairModal(false);
['pairEndpoint', 'pairToken', 'pairViewer'].forEach((id) => {
  $(id).oninput = updatePairLinkPreview;
});
$('btnCopyPair').onclick = async () => {
  updatePairLinkPreview();
  try {
    await navigator.clipboard.writeText($('pairLink').value);
    $('btnCopyPair').textContent = 'Copied ✓';
    setTimeout(() => { $('btnCopyPair').textContent = 'Copy pairing URL'; }, 1500);
  } catch {
    $('pairLink').select();
  }
};
$('pairForm').onsubmit = () => {
  state.token = $('pairToken').value.trim();
  const viewer = $('pairViewer').value.trim().toLowerCase();
  saveStored('scrollsense.token', state.token);
  saveStored('scrollsense.endpoint', $('pairEndpoint').value.trim() || location.origin);
  if (/^[a-z0-9-]{3,32}$/.test(viewer)) {
    saveStored('scrollsense.viewer', viewer);
    state.viewer = viewer;
  }
  state.signature = '';
  init().catch((err) => setStatus(err.message, true));
};

init().catch((error) => {
  console.error(error);
  setStatus(`Server status: ${error.message}`, true);
});
