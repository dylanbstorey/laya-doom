#!/usr/bin/env bash
# Start the demo. Needs a laya-mps server already running:
#   cd ../laya-mps && ./scripts/serve.sh --memory full --question-batch-size 4
set -euo pipefail
cd "$(dirname "$0")"

if ! curl -sf --max-time 3 "${LAYA_URL:-http://127.0.0.1:8000}/health" >/dev/null; then
  echo "No laya-mps server on ${LAYA_URL:-http://127.0.0.1:8000}." >&2
  echo "Start one:  cd ../laya-mps && ./scripts/serve.sh --memory full --question-batch-size 4" >&2
  exit 1
fi

PORT="${PORT:-8100}"
echo "LAYA plays Doom -> http://127.0.0.1:${PORT}"
exec uv run uvicorn laya_doom.server:app --app-dir src --host 127.0.0.1 --port "${PORT}"
