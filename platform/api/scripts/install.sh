#!/usr/bin/env bash
# Install the blue-userdb REST API, editable, together with the library it needs
# (and so the sibling repos, which lib/scripts/install.sh installs first).
# Usage: bash platform/api/scripts/install.sh        (run from anywhere; uses the active python3)
set -euo pipefail

API_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

bash "$API_ROOT/../../lib/scripts/install.sh"

echo "Installing blue-data-user-api (with dev tools)..."
python3 -m pip install -q -e "$API_ROOT[dev]"

echo "Done. Run: blue-userdb-api"
