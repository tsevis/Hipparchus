#!/usr/bin/env zsh
set -euo pipefail

cd "$(dirname "$0")/.."
SCRIPT_DIR="$(pwd)"
source "$SCRIPT_DIR/scripts/python_env.sh"

"$HIPPARCHUS_PYTHON" -m py_compile $(rg --files -g '*.py')
"$HIPPARCHUS_PYTHON" -m unittest discover -s tests -p 'test_*.py'
"$HIPPARCHUS_PYTHON" -c "import importlib.util as u; assert u.find_spec('shapely'); print('shapely OK')"
"$HIPPARCHUS_PYTHON" -c "import importlib.util as u; print('skia present:', bool(u.find_spec('skia')))"

echo "Preflight checks passed"
