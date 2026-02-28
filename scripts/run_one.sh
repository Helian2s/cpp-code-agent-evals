#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <run_id> <instance_id> [extra harness args]" >&2
  exit 1
fi

RUN_ID="$1"
INSTANCE_ID="$2"
shift 2

python -m harness.cli run --run-id "$RUN_ID" --instance "$INSTANCE_ID" "$@"
