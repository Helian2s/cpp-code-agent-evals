#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <run_id> [extra harness args]" >&2
  exit 1
fi

RUN_ID="$1"
shift

python -m harness.cli run-all --run-id "$RUN_ID" "$@"
