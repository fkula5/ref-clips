#!/usr/bin/env bash
# Checks that the edge proxy's logs hold no token from a secret link (/set-password, /s, /watch,
# /ws/watch, /unsubscribe). Reads BOTH streams of the container: the filtered access log goes to stdout,
# but reverse_proxy warnings and error logs go to stderr, which `docker logs ... | grep` never sees.
# Prints only counts per logger, never a matching line, so the output is safe to paste anywhere.
# Run on the server.
#
# Usage: deploy/check-log-leaks.sh [SINCE]   (SINCE as for `docker logs --since`, e.g. 24h; default: all)
# Exit codes: 0 no leaks, 1 leaks found, 2 usage or docker error.
set -euo pipefail

CONTAINER="${REFCLIPS_EDGE_CONTAINER:-edge-caddy}"
[ "$#" -le 1 ] || { echo "Użycie: $0 [SINCE]" >&2; exit 2; }
since=()
[ -n "${1:-}" ] && since=(--since "$1")

# A token is a path segment right after a secret prefix that is not the filter's own replacement.
LEAK='/(set-password|s|watch|ws/watch|unsubscribe)/[^/?#[:space:]"\\[]'
LOGGER='"logger":"[^"]*"'

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
docker logs "${since[@]}" "$CONTAINER" >"$tmp/out" 2>"$tmp/err" || {
  echo "check-log-leaks: nie udało się odczytać logów $CONTAINER" >&2
  exit 2
}

found=0
for stream in out err; do
  n="$(grep -cE "$LEAK" "$tmp/$stream" || true)"
  name=stdout; [ "$stream" = err ] && name=stderr
  echo "$name: $n (wpisy z niezamaskowanym tokenem)"
  if [ "$n" -gt 0 ]; then
    found=1
    grep -E "$LEAK" "$tmp/$stream" | { grep -oE "$LOGGER" || echo '"logger":"?"'; } | sort | uniq -c | sed 's/^/  /'
  fi
done
exit "$found"
