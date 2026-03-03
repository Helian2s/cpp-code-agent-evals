#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <run_id> [extra harness args]" >&2
  echo "  extra harness args may include: --config <path> --max-parallel N --resume --show-patch-only" >&2
  echo "  script-only option: --skip-preflight" >&2
  exit 1
fi

resolve_python_bin() {
  if command -v python3 >/dev/null 2>&1; then
    echo "python3"
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    echo "python"
    return 0
  fi
  echo "error: python3/python is required but was not found in PATH" >&2
  exit 2
}

RUN_ID="$1"
shift

PYTHON_BIN="$(resolve_python_bin)"
CONFIG_PATH=""
SKIP_PREFLIGHT=false
RUN_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      if [[ $# -lt 2 || "${2}" == --* ]]; then
        echo "error: --config requires a value" >&2
        exit 2
      fi
      CONFIG_PATH="$2"
      shift 2
      ;;
    --skip-preflight)
      SKIP_PREFLIGHT=true
      shift
      ;;
    *)
      RUN_ARGS+=("$1")
      shift
      ;;
  esac
done

BASE_CMD=("$PYTHON_BIN" -m harness.cli)
if [[ -n "$CONFIG_PATH" ]]; then
  BASE_CMD+=(--config "$CONFIG_PATH")
fi

if [[ "$SKIP_PREFLIGHT" != true ]]; then
  "${BASE_CMD[@]}" preflight --expect-instances 12 --require-bedrock-auth
fi

"${BASE_CMD[@]}" run-all --run-id "$RUN_ID" "${RUN_ARGS[@]}"
