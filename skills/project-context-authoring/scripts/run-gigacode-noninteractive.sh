#!/usr/bin/env bash
# Run GigaCode with closed stdin and show liveness while text output is buffered.
set -uo pipefail

if [ "$#" -eq 0 ]; then
  echo "Usage: $0 command [args...]" >&2
  exit 2
fi

OUTPUT_FORMAT="${PROJECT_CONTEXT_OUTPUT_FORMAT:-stream-json}"
if [ "$OUTPUT_FORMAT" != "text" ]; then
  exec "$@" </dev/null
fi

HEARTBEAT_SECONDS="${PROJECT_CONTEXT_HEARTBEAT_SECONDS:-30}"
case "$HEARTBEAT_SECONDS" in
  ''|*[!0-9]*)
    echo "PROJECT_CONTEXT_HEARTBEAT_SECONDS must be a positive integer" >&2
    exit 2
    ;;
esac
if [ "$HEARTBEAT_SECONDS" -lt 1 ]; then
  echo "PROJECT_CONTEXT_HEARTBEAT_SECONDS must be a positive integer" >&2
  exit 2
fi

"$@" </dev/null &
GIGACODE_PID=$!
STARTED_AT=$SECONDS
NEXT_HEARTBEAT=$HEARTBEAT_SECONDS

stop_child() {
  kill -TERM "$GIGACODE_PID" 2>/dev/null || true
  wait "$GIGACODE_PID" 2>/dev/null || true
  exit 130
}
trap stop_child INT TERM

while kill -0 "$GIGACODE_PID" 2>/dev/null; do
  sleep 1
  ELAPSED=$((SECONDS - STARTED_AT))
  if [ "$ELAPSED" -ge "$NEXT_HEARTBEAT" ]; then
    echo "GigaCode agent is still working — ${ELAPSED}s elapsed" >&2
    NEXT_HEARTBEAT=$((NEXT_HEARTBEAT + HEARTBEAT_SECONDS))
  fi
done

wait "$GIGACODE_PID"
STATUS=$?
trap - INT TERM
exit "$STATUS"
