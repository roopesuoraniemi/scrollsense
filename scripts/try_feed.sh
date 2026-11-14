#!/usr/bin/env bash
# Simulates two viewers' feeds so the longitudinal readout has realistic comparison data:
#   patient-01: diverse daytime baseline 2 days ago -> nocturnal (02:15 local) low-arousal drift + 1 recovery clip
#   control-01: diverse daytime clips in both windows (stays stable)
# Usage: BASE=http://127.0.0.1:8765 TOKEN=<token or empty> scripts/try_feed.sh
set -euo pipefail
BASE="${BASE:-http://127.0.0.1:8765}"
AUTH=()
[ -n "${TOKEN:-}" ] && AUTH=(-H "Authorization: Bearer $TOKEN")
NOW=$(date +%s)
TZ_MIN=120   # Finland winter time (UTC+2)

# Anchor timestamps to deterministic local hours rather than wall-clock time-of-run:
#   OLD_DAY = 14:00 local two days ago; NIGHT_NOW = most recent 02:15 local within last 24h.
LOCAL_MOD=$(( (NOW + TZ_MIN * 60) % 86400 ))
OLD_DAY=$(( NOW - 2 * 86400 - LOCAL_MOD + 14 * 3600 ))
NIGHT_NOW=$(( NOW - LOCAL_MOD + 2 * 3600 + 15 * 60 ))
[ "$NIGHT_NOW" -gt $(( NOW - 300 )) ] && NIGHT_NOW=$(( NIGHT_NOW - 86400 ))
[ "$NIGHT_NOW" -lt $(( NOW - 82800 )) ] && NIGHT_NOW=$(( NOW - 1200 ))
DAY_NOW=$(( NOW - 1800 ))

post() {  # viewer, then "vid:base:offset:dwell:dur:loops" specs
  local viewer=$1; shift
  local events="" sep=""
  for spec in "$@"; do
    IFS=: read -r vid base offset dwell dur loops <<<"$spec"
    events+="$sep{\"event_id\":\"$viewer-$vid-$((base + offset))\",\"video_id\":\"$vid\",\"seen_at\":$((base + offset)),\"tz_offset_min\":$TZ_MIN,\"dwell_s\":$dwell,\"duration_s\":$dur,\"loops\":$loops}"
    sep=","
  done
  curl -sS -X POST "$BASE/api/views" "${AUTH[@]}" -H 'Content-Type: application/json' \
       -d "{\"viewer\":\"$viewer\",\"events\":[$events]}"
  echo
}

LIGHT=(Qo4PLQXRmUw RWD9TXXf1_A KOiWuuzGzOw jNQXAC9IVRw cRftRest001)
HEAVY=(lMQJ2bHeP4c wZF2PLGsksI bPnRMwahAMA)
RECOV=recovWin001

echo "== baseline (14:00 local, 2 days ago)"
post patient-01 \
  "${LIGHT[0]}:$OLD_DAY:0:9.5:15:0" \
  "${LIGHT[1]}:$OLD_DAY:45:12.0:14:1" \
  "${LIGHT[2]}:$OLD_DAY:90:8.0:16:0" \
  "${LIGHT[3]}:$OLD_DAY:140:11.0:18:0" \
  "${LIGHT[4]}:$OLD_DAY:195:10.5:20:0"

post control-01 \
  "${LIGHT[0]}:$OLD_DAY:10:8.0:15:0" \
  "${LIGHT[1]}:$OLD_DAY:60:10.0:14:0" \
  "${LIGHT[2]}:$OLD_DAY:110:7.5:16:0"

echo "== current window (02:15 local for patient-01, recent daytime for control-01)"
post patient-01 \
  "${HEAVY[0]}:$NIGHT_NOW:0:17.5:15:1" \
  "${HEAVY[1]}:$NIGHT_NOW:40:19.0:16:1" \
  "${LIGHT[0]}:$NIGHT_NOW:75:1.1:15:0" \
  "${HEAVY[2]}:$NIGHT_NOW:110:16.0:14:1" \
  "$RECOV:$NIGHT_NOW:155:9.0:18:0"

post control-01 \
  "${LIGHT[3]}:$DAY_NOW:0:9.0:18:0" \
  "${LIGHT[4]}:$DAY_NOW:60:11.0:20:0" \
  "${LIGHT[1]}:$DAY_NOW:120:8.5:14:0"

echo "== waiting for the analysis queue"
for _ in $(seq 1 60); do
  q=$(curl -sS "$BASE/api/queue" "${AUTH[@]}")
  echo "$q" | grep -q '"depth":0,"in_flight":0' && break
  sleep 1
done
echo "$q"
echo "== readout: patient-01 vs personal baseline, controlled against control-01"
curl -sS "$BASE/api/viewers/patient-01/readout?control=control-01" "${AUTH[@]}" \
  | uv run python -c '
import json, sys
body = json.load(sys.stdin)
r, g = body["readout"], body["guidance"]
print("triage:", g["triage_level"], "|", g["headline"])
print("flags:", r["flags"])
for c in r["clusters"]:
    name, level, flagged = c["name"], c["level"], list(c["flagged"])
    print(f"  cluster {name}: {level} ({flagged})")
print("resets:", [a["kind"] for a in g["resets"]])
print("evidence items:", len(body["evidence"]), "| safety hits:", len(r["safety_hits"]))
'
