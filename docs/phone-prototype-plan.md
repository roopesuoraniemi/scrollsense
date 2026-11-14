# Phone prototype: YouTube Shorts → ScrollSense (investigation, 14 Nov 2026)

> **Status (14 Nov 2026, cleanup):** built as described in the README. Since this plan, the composition/readout endpoints, the baseline-vs-control readout, `JobBoard` and `/analyze`, the DSM-5 theme scores and the PHQ-9 yardstick were removed; drift is now affect-only against a global norm (`docs/clinical-calibration.md`). The sections below are the original investigation.

**Verdict: yes, partly, this weekend.** The route is a browser userscript, not the YouTube app.
- **Android:** Firefox (release) runs Violentmonkey from AMO. A userscript reads `/shorts/{id}` from `m.youtube.com` as you swipe and POSTs it through an HTTPS tunnel to a new `/api/views` endpoint.
- **Same script elsewhere:** iOS Safari with the free "Userscripts" app, and Edge Android with Tampermonkey as a fallback.
- **The YouTube app itself:** not feasible this weekend.

> **Decides everything, unverified:** does the `m.youtube.com` Shorts URL change on *every* swipe? Test in hour one.

## 1. Options, ranked

| # | Path | Captures | Effort | Reliability | ToS/policy risk | Verdict |
|---|---|---|---|---|---|---|
| 1 | **Firefox Android + Violentmonkey userscript** on m.youtube.com, logged into the user's account | video ID, timestamp, dwell, duration, loops, visibility. Feed ranked by YouTube for that account. | 1–2 h | Medium: depends on mobile-web URL/DOM, test first | Low: user watches normally; we read the page URL | **Recommended** |
| 2 | Same script, Edge Android + Tampermonkey | same | 1 h | Medium | Low | Fallback |
| 3 | Same script, iPhone Safari + "Userscripts" app (free, iOS 15+) | same | 1 h | Medium (iOS URL behaviour untested) | Low | Bonus platform |
| 4 | Custom Firefox WebExtension (`tabs.onUpdated` / `webNavigation.onHistoryStateUpdated`) | same | 3–5 h. Signing, or Nightly / adb `web-ext run` | Medium | Low | Product path, not needed for the demo |
| 5 | AccessibilityService on the official YouTube app | visible text only (title, channel). **No documented way to get the video ID** (unverified). Title → ID lookup is noisy and quota-capped. | 8–14 h Kotlin | Low–medium | High: Play policy; "restricted settings"; Android 17 Advanced Protection blocks non-tool services | Not this weekend |
| 6 | Google Data Portability API (`myactivity.youtube`, restricted scope) | "Watched…" entries, URL, time | 4–6 h + waiting | High, not live | Low, but needs Google verification + security assessment to publish | Product-path slide. EU/UK/CH only. Testing mode: 7-day access, 1 export/24 h. |
| 7 | Google Takeout `watch-history.json` | ID, title, time (Shorts probably included, unconfirmed) | Manual | Retrospective | Low | Request now as backfill |
| 8 | Own PWA with the IFrame Player | exact dwell/completion | 6–8 h | High | Low | Breaks "borrow the algorithm"; fallback only |
| 9 | YouTube Data API watch history | nothing (removed in 2016) | — | — | — | Dead end |
| 10 | Network / VPN / SNI | hostnames only (TLS, QUIC, ECH) | — | — | — | Infeasible |

Notes on the Android AccessibilityService path (#5):
- **Play policy:** non-tool use needs an in-app prominent disclosure and affirmative consent, plus a data-collection declaration. `isAccessibilityTool` can't be declared for monitoring apps; a false declaration is rejected and blocked by Play Protect.
- **Sideloading:** requires "Allow restricted settings" after a first blocked attempt. Developer verification is enforced in a few countries since Sep 2026 and goes global in 2027.
- **Android 16 `accessibilityDataSensitive`:** opt-in per view, so probably little impact on YouTube.

Other notes:
- Kiwi was discontinued in Jan 2025.
- Edge Android stable has a curated extension list that includes Tampermonkey; sideloading is Canary-only.
- A custom iOS Safari extension needs a Mac, Xcode and a paid Apple Developer membership. The Userscripts app avoids all three.

## 2. Architecture

```
Phone: Firefox (logged into the "Patient" sock-puppet YouTube account)
  m.youtube.com/shorts/{id} ── swipe ──► Violentmonkey userscript
    polls location.pathname every 500 ms; counts time only while the page is visible
    on change: closes the previous event (dwell_s, duration_s, loops), opens a new one
    buffers locally; flushes every 5 s or every 10 events
        │ GM_xmlhttpRequest (not limited by CORS)   Authorization: Bearer <token>
        ▼
https://<random>.trycloudflare.com   (cloudflared quick tunnel inside WSL2)
        ▼
uvicorn 127.0.0.1:8765 (WSL2, loopback only)
   POST /api/views ─► ViewLog (data/views/{viewer}.jsonl)
                   └► AnalysisQueue (dedupe by video id, token bucket, N workers)
                          └► existing AnalysisService (Gemini → data/clips)
   GET /api/viewers/{v}/composition | /readout ◄── laptop dashboard
```

**Connectivity:**
- **Cloudflare quick tunnel** (fastest): no account, HTTPS. The hostname changes every run, so make the endpoint a userscript setting.
- **Tailscale Serve** (more private): stable `*.ts.net` HTTPS. Needs the Tailscale app on the phone.

**Auth:** `SCROLLSENSE_TOKEN` in `.env`, checked as a Bearer token on every `/api/*` route, including `/analyze`. The tunnel exposes the server and Gemini credits are at stake.

## 3. Data model and endpoints

**Pure core:**
- `ViewerId`: pseudonym such as `patient-01`, `control-01`.
- `ViewEvent`:
  - `event_id`, `viewer`, `video_id`, `seen_at`, `tz_offset_min`
  - optional: `dwell_s`, `duration_s`, `loops`
  - `source` ∈ shorts_web | takeout | portability | a11y | manual
  - `surface` ∈ shorts | watch | other
- `ClipState`: pending | scored | unavailable(reason) | failed(error).
- `Composition` (per window):
  - counts
  - `theme_share` per criterion (score ≥ 2, dwelling stance)
  - mean valence / arousal, negative share, hopeful share
  - format and theme entropy
  - `night_share` (00:00–05:00 local)
  - dwell-weighted theme share, median dwell, completion rate
- `Readout`:
  - current vs baseline vs control
  - deltas and z-scores (need ≥ 3 baseline buckets)
  - flags: the metric must exceed both the baseline and the control threshold
  - clusters: sleep_fatigue, anhedonia_hopelessness, worthlessness_guilt
  - top evidence quotes
- Pure functions:
  - `dedupe(events)`: same viewer and video within 30 s counts once
  - `composition(events, analyses, window)`
  - `readout(current, baseline, control)`

**Ports and adapters:**
- `ViewLog` (JSONL per viewer, append-only)
- `ClipStates`
- `data/viewers.json` for consent records
- `AnalysisQueue` replaces the thread-per-job `JobBoard` and keeps `start` / `status`:
  - dedupe, 2–3 workers
  - token bucket (`SCROLLSENSE_RPM`, `SCROLLSENSE_DAILY_CLIPS`)
  - retry on 429 / 5xx; permission errors → unavailable
  - Shorts only
  - prioritise events with dwell ≥ 2 s

**Endpoints (all need the Bearer token):**

| Method + path | Purpose |
|---|---|
| `POST /api/views` | Batch of view events → 202 `{accepted, duplicates, queued, rejected}` |
| `GET /api/viewers` | IDs, consent state, last seen |
| `POST` / `DELETE /api/viewers/{v}/consent` | Give / withdraw consent (versioned) |
| `GET /api/viewers/{v}/feed` | Recent items with state + scores (live ticker) |
| `GET /api/viewers/{v}/composition?bucket=` | Composition time series |
| `GET /api/viewers/{v}/readout` | Readout vs baseline and control |
| `DELETE /api/viewers/{v}` | Erase the view log (GDPR) |
| `GET /api/queue` | Queue depth, rate, failures |

**Userscript sketch** (about 60 lines total):
```js
// @match https://m.youtube.com/*   @match https://www.youtube.com/*
// @grant GM_xmlhttpRequest  @grant GM_getValue  @grant GM_setValue  @grant GM_registerMenuCommand
// @connect trycloudflare.com
setInterval(() => { const m = location.pathname.match(/^\/shorts\/([\w-]{11})/); if (m && m[1] !== cur) rotate(m[1]); }, 500);
// rotate(): close the previous event (dwell, duration/loops from the <video> element), buffer it, start a new one
// flush(): POST {viewer, events} with Bearer; keep the buffer on failure
// first run: consent text + viewer id + endpoint; menu: Pause / Resume / Set endpoint
```
Collect no channel names or usernames (data minimisation; YouTube ToS).

## 4. Weekend plan (about 16 h, two tracks)

| Hours | Track A: backend | Track B: phone + dashboard |
|---|---|---|
| 0–1 | First-hour blockers (§5), together | — |
| 1–4 | `ViewEvent`, `ViewLog`, `POST /api/views`, token auth, `AnalysisQueue`; tests with `MockAnalyser` | Userscript (URL watcher, dwell, buffer, flush, consent, menu); test against `SCROLLSENSE_MOCK=1` |
| 4–7 | Pure `composition()`, `readout()` + tests; `/composition`, `/readout`, `/feed` | Dashboard: live feed ticker, theme share over time, baseline vs now vs control |
| 7–8 | Error mapping, `/api/queue` | Takeout import script if the export has arrived |
| 8–13 | **Sock-puppet data collection:** "Patient" and "Control" scroll neutrally for ~45 min each, then the Patient account drifts (sad, sleepless, exhausted content; searches "can't sleep"). The pipeline runs live. | Same |
| 13–15 | Tune thresholds; evidence drill-down; erase endpoint | Phone mirroring for the stage; polish |
| 15–16 | Rehearse; record a backup video; pre-cache clips | Same |

## 5. First-hour blockers (in order)

1. **Does the URL change per swipe?** Firefox + Violentmonkey; log into YouTube; open `m.youtube.com/shorts`; use a 5-line script that shows `location.pathname`; swipe 10×.
2. **Does the feed play and stay personalised?** Stop the YouTube app hijacking links (Android → Apps → YouTube → Open by default → off). Check that autoplay works and the feed looks personalised.
3. **If 1 or 2 fails:** try Edge Android + Tampermonkey, then iPhone + Userscripts, then desktop Chrome on the laptop.
4. **Tunnel:** install `cloudflared` in WSL; run `cloudflared tunnel --url http://127.0.0.1:8765`; open `/api/meta` from the phone.
5. **POST from the phone** with the Bearer token reaches the server.
6. **Gemini throughput:** 20 Shorts sequentially, then 3 in parallel. Measure seconds per clip and any 429s.
7. **Request Google Takeout** (YouTube history) for the sock-puppet account now.

## 6. Demo (about 3 min)

1. **Phone** (mirrored): Firefox → Shorts as "Patient"; consent prompt once; swipe naturally.
2. **Laptop, live feed:**
   - each swipe appears within about 1 s as `queued`, then is scored 10–20 s later
   - the composition bars move
   - "We built no recommender. This is YouTube's own model of this person, translated."
3. **Readout:** baseline vs drift shows sleep/fatigue share up, valence down, entropy narrowing. The control stays flat. Click a flag to see the evidence quotes.
4. **Roadmap:** the userscript is the prototype. The product path is the Data Portability API (EU/UK/CH) plus Takeout backfill.

## 7. Risks

| Risk | Mitigation |
|---|---|
| Mobile-web Shorts URL/DOM differs or changes | Hour-one test; poll the URL; desktop fallback |
| Web feed ≠ app feed | Same account model; say so honestly |
| Gemini YouTube-URL input is a preview | Paid key; cache; queue cap; mock mode |
| Tunnel URL changes or venue Wi-Fi blocks it | Endpoint as a setting; Tailscale; recorded video |
| Scoring lags the swiping | 2–3 workers; prioritise by dwell; show `pending` |
| Team testing pollutes the sock-puppet feeds | Dedicated accounts and browser profiles |
| Ads and live videos in the feed | Count only `/shorts/{id}` |
| Prevention content flagged as A9 | `stance` field; A9 is a content theme score only, with no crisis/suicide alerts (the feed signal is not reliable enough) |

## 8. Ethics, ToS, policy

- **YouTube ToS:** user-driven viewing in YouTube's own player. **Never auto-swipe.** Collect no handles or faces.
- **Google Play:** not involved in the userscript path.
- **GDPR Art. 9:**
  - explicit, versioned consent
  - pseudonymous IDs
  - minimal data (ID, time, dwell)
  - pause and erase
  - data stays on the laptop
  - Gemini sees only public URLs
  - the demo uses sock-puppet accounts, not patients
- **Positioning:** a research prototype, not a diagnostic (MDR risk if marketed for relapse detection). Disclose the dependence on an engagement-optimised algorithm, and use baseline plus control.

## Still unverified
- whether the mobile-web URL changes per swipe
- whether the YouTube app's accessibility tree exposes the video ID
- whether Shorts are in Takeout
- Edge stable sideloading
- the Shorts maximum length
- `gemini-4-hydrogen` rate limits
- Firefox "open links in apps" setting name
- scrcpy over Windows adb

## Sources
- Firefox Android WebExtension compat: [webNavigation](https://raw.githubusercontent.com/mdn/browser-compat-data/main/webextensions/api/webNavigation.json), [tabs](https://raw.githubusercontent.com/mdn/browser-compat-data/main/webextensions/api/tabs.json)
- Firefox Android extension development and signing:
  - [web-ext on Android](https://extensionworkshop.com/documentation/develop/developing-extensions-for-firefox-for-android/)
  - [install from file](https://discourse.mozilla.org/t/is-add-on-loading-from-file-possible-in-firefox-for-android-139-0-4/144353)
  - [signing](https://extensionworkshop.com/documentation/publish/signing-and-distribution-overview/)
  - [self-distribution](https://extensionworkshop.com/documentation/publish/self-distribution/)
- Userscript managers: [Violentmonkey (AMO)](https://addons.mozilla.org/en-US/android/addon/violentmonkey/), [Tampermonkey (AMO)](https://addons.mozilla.org/en-US/android/addon/tampermonkey/), [GM API](https://violentmonkey.github.io/api/gm/), [iOS Userscripts](https://apps.apple.com/us/app/userscripts/id1463298887)
- [Firefox bug 1882040 (m.youtube Shorts)](https://bugzilla.mozilla.org/show_bug.cgi?id=1882040) · [Kiwi discontinued](https://www.androidauthority.com/kiwi-browser-shutting-down-3519510)
- Android accessibility policy:
  - [Play AccessibilityService policy](https://support.google.com/googleplay/android-developer/answer/10964491)
  - [Android 16 accessibilityDataSensitive](https://developer.android.com/blog/posts/enhancing-android-security-stop-malware-from-snooping-on-your-app-data)
  - [Android 17 Advanced Protection](https://thehackernews.com/2026/03/android-17-blocks-non-accessibility.html)
  - [Restricted settings](https://9to5google.com/2024/09/12/android-15-sideloaded-apps-restrictions/)
  - [Developer verification](https://support.google.com/android-developer-console/answer/16561738)
- YouTube: [Data API quotas](https://developers.google.com/youtube/v3/determine_quota_cost) · [ToS](https://www.youtube.com/static?template=terms) · [Developer Policies](https://developers.google.com/youtube/terms/developer-policies) · [IFrame Player API](https://developers.google.com/youtube/iframe_api_reference)
- Google Data Portability: [schema](https://developers.google.com/data-portability/schema-reference/my_activity) · [scopes](https://developers.google.com/data-portability/user-guide/scopes) · [time-based access](https://developers.google.com/data-portability/user-guide/time-based) · [availability](https://support.google.com/accounts/answer/14452558)
- [Gemini YouTube URL limits](https://aistudio.google.com/docs/video-understanding)
- Tunnels: [Cloudflare quick tunnels](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/) · [Tailscale Serve](https://tailscale.com/kb/1312/serve)
