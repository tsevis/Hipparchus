#!/usr/bin/env zsh
# Shared Python launcher setup for running Hipparchus from a source checkout.

if [[ -z "${SCRIPT_DIR:-}" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
fi

export HIPPARCHUS_PYTHON="${HIPPARCHUS_PYTHON:-python3}"

if ! command -v "$HIPPARCHUS_PYTHON" >/dev/null 2>&1; then
  echo "Python interpreter not found: $HIPPARCHUS_PYTHON" >&2
  echo "Set HIPPARCHUS_PYTHON to a Python 3.11+ executable, for example:" >&2
  echo "  HIPPARCHUS_PYTHON=/opt/homebrew/bin/python3 ./run_hprs.sh" >&2
  exit 1
fi

PYTHON_VERSION="$("$HIPPARCHUS_PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if ! "$HIPPARCHUS_PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
  echo "Hipparchus needs Python 3.11 or newer. Found Python $PYTHON_VERSION at: $HIPPARCHUS_PYTHON" >&2
  exit 1
fi

if [[ -n "${PYTHONPATH:-}" ]]; then
  export PYTHONPATH="$SCRIPT_DIR/src:$SCRIPT_DIR:$PYTHONPATH"
else
  export PYTHONPATH="$SCRIPT_DIR/src:$SCRIPT_DIR"
fi

check_hipparchus_runtime_deps() {
  "$HIPPARCHUS_PYTHON" - <<'PY'
import importlib.util
import sys

required = {
    "numpy": "numpy",
    "scipy": "scipy",
    "shapely": "shapely",
    "tkinter": "tkinter",
}
missing = [package for module, package in required.items() if importlib.util.find_spec(module) is None]
if missing:
    print("Missing required Python packages:", ", ".join(missing), file=sys.stderr)
    print("", file=sys.stderr)
    print("Install them into your normal Python, without a virtualenv:", file=sys.stderr)
    print(f"  {sys.executable} -m pip install --user numpy scipy shapely", file=sys.stderr)
    print("", file=sys.stderr)
    print("If pip refuses --user inside conda/base, use:", file=sys.stderr)
    print(f"  {sys.executable} -m pip install numpy scipy shapely", file=sys.stderr)
    raise SystemExit(1)

if importlib.util.find_spec("skia") is None:
    print("Warning: skia-python is not installed; Hipparchus will use the fallback renderer.", file=sys.stderr)
    print(f"Install it with: {sys.executable} -m pip install --user skia-python", file=sys.stderr)
PY
}
