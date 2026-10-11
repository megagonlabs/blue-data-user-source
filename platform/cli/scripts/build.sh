#!/usr/bin/env bash
# Build the blue-data-user-cli sdist and wheel into platform/cli/dist/.
# Usage: bash platform/cli/scripts/build.sh        (run from anywhere)
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
python3 -m build
