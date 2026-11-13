#!/usr/bin/env bash
# Simulates two viewers' feeds so the readout has something to compare:
#   patient-01: light, positive clips two days ago (baseline) -> depression-themed clips at night (now)
#   control-01: the same light clips in both windows (should stay flat)
# Usage: BASE=http://127.0.0.1:8765 TOKEN=<token or empty> scripts/try_feed.sh
set -euo pipefail
BASE="${BASE:-http://127.0.0.1:8765}"
AUTH=()
[ -n "${TOKEN:-}" ] && AUTH=(-H "Authorization: Bearer $TOKEN")
NOW=$(date +%s)
OLD=$((NOW - 2 * 86400))
TZ_MIN=120   # Finland in winter (UTC+2)

post() {  # viewer, then "id:seconds_ago_from_base:base" triples
  local viewer=$1; shift
  local events="" sep=""
  for spec in "$@"; do
    IFS=: read -r vid base offset dwell <<<"$spec"
    events+="$sep{\"event_id\":\"$viewer-$vid-$base\",\"video_id\":\"$vid\",\"seen_at\":$((base + offset)),\"tz_offset_min\":$TZ_MIN,\"dwell_s\":$dwell}"
    sep=","
  done
  curl -sS -X POST "$BASE/api/views" "${AUTH[@]}" -H 'Content-Type: application/json' \
       -d "{\"viewer\":\"$viewer\",\"events\":[$events]}"
  echo
}

LIGHT=(Qo4PLQXRmUw RWD9TXXf1_A KOiWuuzGzOw jNQXAC9IVRw)
HEAVY=(lMQJ2bHeP4c wZF2PLGsksI bPnRMwahAMA)

echo "== baseline (2 days ago)"
post patient-01 "${LIGHT[0]}:$OLD:0:4" "${LIGHT[1]}:$OLD:60:6" "${LIGHT[2]}:$OLD:120:3" "${LIGHT[3]}:$OLD:180:2"
post control-01 "${LIGHT[0]}:$OLD:0:4" "${LIGHT[1]}:$OLD:60:5" "${LIGHT[2]}:$OLD:120:3"
echo "== now"
post patient-01 "${HEAVY[0]}:$NOW:-600:14" "${HEAVY[1]}:$NOW:-540:11" "${HEAVY[2]}:$NOW:-480:16" "${LIGHT[0]}:$NOW:-420:1"
post control-01 "${LIGHT[1]}:$NOW:-600:4" "${LIGHT[2]}:$NOW:-540:3" "${LIGHT[3]}:$NOW:-480:5"

echo "== waiting for the queue"
for _ in $(seq 1 60); do
  q=$(curl -sS "$BASE/api/queue" "${AUTH[@]}")
  echo "$q" | grep -q '"depth":0,"in_flight":0' && break
  sleep 2
done
echo "$q"
echo "== readout: patient-01 vs its baseline, with control-01"
curl -sS "$BASE/api/viewers/patient-01/readout?control=control-01" "${AUTH[@]}" \
  | uv run python -c 'import json,sys; r=json.load(sys.stdin)["readout"]; print("flags:", r["flags"]); [print(" ", c["name"], c["level"]) for c in r["clusters"]]; print("safety hits:", len(r["safety_hits"]))'
