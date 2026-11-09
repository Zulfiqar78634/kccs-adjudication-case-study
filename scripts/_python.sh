# Sourced by the run scripts. Sets PY to a Python >= 3.11, or exits with a clear message.
# Honours $PYTHON if set. macOS's bundled /usr/bin/python3 is often 3.9, so newer versions are tried first.
find_python() {
  local c
  for c in ${PYTHON:-} python3.13 python3.12 python3.11 python3 python; do
    command -v "$c" >/dev/null 2>&1 || continue
    if "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
      PY="$c"; return 0
    fi
  done
  echo "Python 3.11 or newer is required (found: $(python3 --version 2>&1 || echo none))." >&2
  echo "Install it (macOS: 'brew install python@3.12'; Linux: your package manager or https://www.python.org)," >&2
  echo "or point to one explicitly: PYTHON=/path/to/python3.12 $0" >&2
  exit 1
}
find_python
