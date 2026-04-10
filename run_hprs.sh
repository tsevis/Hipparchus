#!/usr/bin/env zsh
set -euo pipefail

# Run from repo root regardless of caller location.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

source "$SCRIPT_DIR/scripts/python_env.sh"
check_hipparchus_runtime_deps

exec "$HIPPARCHUS_PYTHON" -m hipparchus
