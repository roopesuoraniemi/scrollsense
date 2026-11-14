# Plan: patient nudge ("Hi, how are you doing?")

Status: **built (demo).** Builds on the drift detector (`GET /api/viewers/{v}/drift`). Research prototype, not a medical device. See README "Patient nudge" for env vars and endpoints.

> **Update:** the "1-minute breathing" and "Talk to someone" options (and the calm page and contact settings) were removed. Then "Step outside" and "Refresh my feed" were replaced too: the card now asks **"How do these videos feel right now?"** with three equal options side by side: **I'm OK · I want to take a break · Not now**. "I want to take a break" pauses the video and closes the tab, or switches to a blank page (pages can't open the browser's home page). "Refresh my feed" was dropped because steering the feed would erase the signal the drift detector reads.

Deviations from this plan in the demo build:
- The policy is `NudgePolicy(settings).decide(report, history, now)`: settings live on the instance (code-style limit of 3 parameters).
- Breathing completion is not logged: the tap on "1-minute breathing" is recorded, and `/calm.html` sends nothing (no token in URLs). The page is at `/calm.html`, not `/calm`.
- No per-patient preferences or Finnish wording yet; contact and texts come from `SCROLLSENSE_NUDGE_*` settings. Wording does not vary with the drift reason. No weekly cap.
- "Step outside" shows a short message instead of a timer.
- No crisis/suicide card (decision after the build): see "A9 and crisis alerts" below.
- The receipt carries a phone-safe `NudgeCard` (no reason, score or video id); the full `Nudge` with `reason` is only in the history endpoint.

## Goal
When a viewer's feed drifts away from their normal, offer the patient a small, kind, optional step at the moment they are scrolling, without alarming them and without diagnostic language. The patient's one-tap answer is also a lightweight self-report that the clinician can see.

## Principles
- **Offer, never alarm.** Never say "we detected depression". Say "Hi, how are you doing today?"
- **Autonomy.** Every nudge has "I'm OK" and "Not now". Neither choice is punished or repeated straight away.
- **Rare.** Cooldowns and quiet hours. A nudge that comes too often trains people to swipe it away.
- **No crisis alerts.** The support card is the only patient-facing intervention (see "A9 and crisis alerts" below).
- **Separate consent.** Patients opt in to nudges separately from monitoring.
- **No engagement tricks.** No streaks or rewards. Success means the patient feels supported, not that they spend more time in the app.

## When a nudge fires (pure `NudgePolicy`)
Input: the latest `DriftReport`, the nudge history and the patient's preferences. Output: `Nudge | None`.

| Condition | Default (demo / product) |
|---|---|
| Drift level | `warning` (a `watch` goes only to the clinician view) |
| Sustained | at least 2 consecutive windows at warning (demo) / 20 min (product) |
| Cooldown after any nudge | 10 min (demo) / 24 h (product) |
| After "I'm OK" | Cooldown ×2. The answer is logged as a possible false positive for tuning. |
| Quiet hours | none (demo) / 23:00–07:00 (product) |
| Max per week | n/a (demo) / 3 (product) |

All values come from env vars, like the drift thresholds (`SCROLLSENSE_NUDGE_*`).

## What the patient sees
A card over the feed, in calm colours. English or Finnish, according to the patient's preference.

> **Hi, how are you doing today?**
> You've been scrolling for a while. Would any of these help right now?
> - 🫁 **1-minute breathing**: a guided exercise, opens in a calm page
> - 💬 **Talk to someone**: call or message the person you chose, or the clinic
> - 🚶 **Step outside for 5 minutes**: with a gentle timer
> - 🔄 **Refresh my feed**: explains YouTube's "not interested" option and TikTok's "Refresh your For You feed"
> - 🙂 **I'm OK**  ·  ⏱ **Not now**

Design notes:
- The wording comes from the drift *reason*, not a diagnosis. For example, sleep/fatigue themes at night give: "It's late. Want to try winding down?"
- "Talk to someone" uses a contact the patient chose at onboarding (a friend, a peer, or the clinic). The demo uses a placeholder number.
- The breathing page is static: `GET /calm`, a 60-second paced animation (4 s in, 6 s out). It logs completion.

## A9 and crisis alerts
Decision: no crisis or suicide alerts, for the patient or the clinician. The earlier plan had a separate crisis card and clinician alert for A9 (death/suicide) themes; it was removed because the feed signal is not reliable enough for that kind of alert. Prevention and educational content also scores A9 > 0 (in tuning, "Nine Symptoms of a Depressive Episode" got A9 = 1). A9 remains one of the nine content theme scores and counts in the theme load like A1–A8.

## How it reaches the phone (demo vs product)

| Channel | Demo | Product |
|---|---|---|
| **Overlay from the userscript** on m.youtube.com | ✔ Main path. Shows at the moment of scrolling. | Only as part of the browser-based prototype |
| Push notification (PWA with Web Push) | – | ✔ Also works when they aren't scrolling |
| SMS | – | Fallback; consent needed |
| Wearable vibration and card | – | Later (Oura/watch) |

**Demo mechanics, with no new polling:** the response to `POST /api/views` already goes to the phone every 5 s. Add an optional `nudge` field to it. When it's present, the userscript renders the card. Taps go to `POST /api/viewers/{v}/nudges/{id}/response`.

## Backend (sketch, following the existing ports-and-adapters layout)
- Pure: `Nudge` (id, viewer, kind `support`, reason, options, created_at), `NudgeResponse` (nudge_id, choice, at), `NudgePolicy.decide(report, history, prefs, now) -> Nudge | None`.
- Port `NudgeLog`: `record(nudge)` and `respond(response)` are commands; `history(viewer)` is a query. Adapter: JSONL under the views dir.
- `ViewIntake.record` → after appending the events, `NudgeService.pending(viewer)` decides and records a new nudge or returns the open one. The `Receipt` gains `nudge: Nudge | None`.
  - Command–query separation: decide-and-record is one atomic command, named `issue_if_due`.
- Endpoints:
  - `GET /api/viewers/{v}/nudges` (history, for the clinician view)
  - `POST /api/viewers/{v}/nudges/{id}/response`
  - `GET /calm` (static page)
- The UI on the laptop shows "Nudge shown 14:22 → chose breathing ✓ completed" under the drift banner.

## Demo script (about 60 s inside the main demo)
1. The phone scrolls drift content until the laptop banner turns red.
2. On the next send, about 5 s later, the phone shows "Hi, how are you doing today?" over the Short.
3. Tap "1-minute breathing" and show the calm page for a few seconds.
4. The laptop shows the response and a timestamp under the warning.

## Effort: about 4–6 h
`NudgePolicy` and tests (1.5 h) · `NudgeLog` and endpoints (1 h) · receipt field and userscript card (1.5 h) · `/calm` page (0.5 h) · laptop UI line (0.5 h) · wording review (0.5 h).

## Open questions for the team
- Which options to offer? Three is calmer than five.
- Is "Talk to someone" in the demo a fake contact or the clinic's real number?
- Finnish wording, and who reviews it (ideally the clinician partner)?
- Should "I'm OK" lower drift sensitivity for that patient (personal calibration), or only feed the tuning dataset?

## Grounding
- Just-in-time adaptive interventions; receptivity matters ([Thompson sampling in the wild](https://arxiv.org/html/2508.02817v1), [reBandit](https://www.arxiv.org/pdf/2402.17739)).
- Patients find active monitoring an emotional burden, so one tap is the most we ask ([remitted-depression focus groups](https://mental.jmir.org/2022/8/e38934/PDF)).
- Hopeful content lifts mood more than merely pleasant content ([summary](https://www.psypost.org/watching-hopeful-videos-online-can-reduce-short-term-depression/)), which is relevant to the "refresh my feed" option.
