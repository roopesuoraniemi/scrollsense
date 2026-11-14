# Plan: clinician dashboard

Status: **plan only, not built.** Builds on the affect drift detector and the patient-nudge log.

## Goal
Give the TMS clinic's psychiatrist or nurse one screen that answers **"who needs a call today, and why?"** in under a minute. Their workload must not grow: no raw feeds to read and no daily reports to skim.

## Users and moments
| User | Moment | Need |
|---|---|---|
| Nurse coordinator | Morning triage | List of patients sorted by concern; acknowledge what's handled |
| Psychiatrist | Before a call or a maintenance-TMS decision | One patient's trajectory since TMS ended, what changed and when, the evidence |

## Screens

### 1. Triage list (`/clinic`)
| Status | Patient | Since | Why (top reason) | Last activity | Nudges | Action |
|---|---|---|---|---|---|---|
| 🔴 Warning | patient-07 | 2 d | Drift 1.6 SD towards low mood | 12 min ago | 1 shown, "Not now" | Call · Ack |
| 🟠 Watch | patient-03 | 6 h | Valence 1.1 SD below normal | 1 h ago | – | Ack |
| ⚪ Learning | patient-12 | – | 3/5 Shorts analysed | today | – | – |
| ⚫ Stale | patient-05 | 4 d | No activity for 4 days | 4 d ago | – | Check in |
| 🟢 Normal | … | | | | | |

- **Sort order:** warning, watch, stale, learning, normal.
- **Stale counts as a status.** A patient who stops scrolling may have changed phone, or may be withdrawing. The dashboard says "no data", never "fine".

### 2. Patient detail (`/clinic/patients/{v}`)
- **Header:** pseudonym, TMS end date, days since, consent state, care team.
- **Trajectory:** daily drift score since TMS ended (a line with watch/warn bands), with markers for nudges, clinician calls and maintenance sessions.
- **Now vs normal:** the affect map with the 1 SD normal-range ellipse and the drift arrow (reused from the laptop UI).
- **Evidence:** the 3–5 Shorts driving the drift. Each shows the title, `intended_meaning`, scores and a quote from the text package; the video plays on click.
- **Nudge history:** shown, chosen, completed.
- **Notes and actions:** "Called patient", "Scheduled maintenance TMS", "Adjust sensitivity". Each action acknowledges the open alert and is written to an audit log.
- **Disclaimer on every page:** "Engagement patterns from the patient's feed. Not a diagnosis. Confirm in conversation."

### 3. Alert inbox
Open alerts with acknowledge, snooze (24 h) and escalate.

## Alert rules (pure `AlertPolicy`, config from env like the drift thresholds)
| Alert | Opens when | Closes when |
|---|---|---|
| `drift` | Level `warning` for ≥ 2 consecutive daily windows (product), or ≥ 2 rolling windows (demo) | Acknowledged, or back to `normal` for 3 days |
| `stale` | No view events for 72 h | A new event, or acknowledged |
| `nudge_declined` (info) | 3 nudges in a row answered "Not now" | Acknowledged |

**No crisis/suicide alerts.** An earlier draft had an alert for any recent Short with an A9 (death/suicide) theme. It was dropped because the feed signal is not reliable enough for that kind of alert: prevention and educational content also scores A9 > 0 (a psychoeducation clip, "Nine Symptoms of a Depressive Episode", scored A9 = 1). The DSM-5 theme scores have since been removed from the scoring.

## Backend (sketch)
- **Daily aggregation:** a `DailySummary` per viewer per day (the drift score of that day's Shorts against the affect norm), computed by a scheduled job or on read with a cache. Multi-week timelines then don't rescan raw events.
- **Values:**
  - `Patient` (viewer id, display alias, TMS end date, care team, consent version)
  - `Alert` (id, viewer, kind, level, opened_at, reason, evidence ids, acked_by, acked_at, note)
  - `ClinicianAction` (who, what, when, viewer, alert id)
- **Ports:** `PatientRegistry`, `AlertLog`, `ActionLog` (JSONL adapters in the demo; a database in the product).
- **Endpoints, under `/api/clinic/` with a separate clinician role:**
  - `GET /patients`: triage rows
  - `GET /patients/{v}`: detail bundle (header, daily timeline, current drift report, evidence, nudges, alerts, actions)
  - `POST /alerts/{id}/ack` `{note}` · `POST /alerts/{id}/snooze` · `POST /patients/{v}/actions`
- **Auth and roles:** the demo uses two tokens (a device token for `/api/views`, a clinician token for `/api/clinic/*`). The product uses hospital SSO, per-patient access lists, an audit log of every view, and a session timeout.
- **Notifications:** alerts appear in the dashboard's alert inbox; there are no crisis alerts (see "Alert rules").

## Privacy and governance
- **Minimum necessary:** clinicians see aggregates and the few evidence clips (public videos), not the full scroll history by default. A "Show full feed" toggle needs a reason and is logged.
- **The patient sees the same view** (data mirror), and sees it first.
- **GDPR:** Art. 9 health data, explicit consent and DPIA. If marketed for relapse detection, likely EU MDR software (class IIa) and high-risk under the AI Act. The demo is labelled "research prototype".
- **Integration later:** export alerts as FHIR `Observation`/`Flag` to the EHR. Not in the demo.

## Demo plan
- `clinic.html` reuses the components in `app.js` (map, sparkline, evidence cards).
- A seed script generates 5 synthetic patients with 30 days of daily summaries (one sleep/fatigue drift, one anhedonia drift, one stale, two normal), alongside the live `patient-01` from the phone.
- **Storyline:**
  1. The dashboard shows `patient-01` green.
  2. The phone scrolls drift content, and `patient-01` turns amber, then red, at the top of the list.
  3. Open the detail and show the evidence quotes.
  4. Click "Called patient" to acknowledge; the note is logged.
  5. Show the nudge the patient answered.

## Effort: about 6–8 h
Seed generator (1 h) · `DailySummary` and `AlertPolicy` with tests (2 h) · clinic endpoints and roles (1.5 h) · triage page (1.5 h) · detail page reusing components (1.5 h) · polish (0.5 h).

## Open questions for the team
- Which roles are in the demo story: one psychiatrist, or nurse plus psychiatrist?
- Should "stale" alert, or only show? Disengagement is ambiguous.
- Should the dashboard suggest actions ("consider booster TMS session"), or only describe? Recommendation: describe only, because prescribing actions moves the product into a higher regulatory class.
- Is a time axis in "days since TMS end" meaningful for the clinic partner?
