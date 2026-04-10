#!/usr/bin/env zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

source "$SCRIPT_DIR/scripts/python_env.sh"
check_hipparchus_runtime_deps

if [[ -x "scripts/release_preflight.sh" ]]; then
  ./scripts/release_preflight.sh
else
  "$HIPPARCHUS_PYTHON" -m py_compile $(rg --files -g '*.py')
  "$HIPPARCHUS_PYTHON" -m unittest discover -s tests -p 'test_*.py'
fi

echo "Launching Hipparchus GUI..."
if ! "$HIPPARCHUS_PYTHON" -m hipparchus; then
  echo "Hipparchus failed to launch. Re-run with: $HIPPARCHUS_PYTHON -X faulthandler -m hipparchus"
  exit 1
fi
