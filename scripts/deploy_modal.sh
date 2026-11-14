#!/usr/bin/env bash
# Deploy the ScrollSense web demo to Modal. Run from the repository root after `modal token new`.
#   scripts/deploy_modal.sh          deploy (public URL, stays up)
#   scripts/deploy_modal.sh serve    temporary dev URL, live-reloads, stops with Ctrl-C
set -euo pipefail
cd "$(dirname "$0")/.."

MODAL=(uv run --with modal modal)

# 1. The secret: only GEMINI_API_KEY from .env goes to Modal, never printed. No SCROLLSENSE_TOKEN:
#    the public demo opens without one (Gemini is still limited to SCROLLSENSE_RPM per minute).
[[ -f .env ]] || { echo "No .env here: copy .env.example and fill in GEMINI_API_KEY" >&2; exit 1; }
secret_env=$(mktemp)
trap 'rm -f "$secret_env"' EXIT
chmod 600 "$secret_env"
grep -E '^GEMINI_API_KEY=.+' .env > "$secret_env" || { echo "GEMINI_API_KEY is missing or empty in .env" >&2; exit 1; }
"${MODAL[@]}" secret create scrollsense --from-dotenv "$secret_env" --force > /dev/null
echo "Secret 'scrollsense' updated (GEMINI_API_KEY only: the demo needs no token)."

# 2. Pinned dependencies from uv.lock, so the container runs what the tests ran.
uv export --no-dev --no-hashes --no-emit-project --format requirements-txt -q > requirements.lock.txt

# 3. Deploy (or serve).
if [[ "${1:-deploy}" == "serve" ]]; then
  "${MODAL[@]}" serve modal_app.py
else
  "${MODAL[@]}" deploy modal_app.py
  echo
  echo "Share the URL above: no token needed."
fi
