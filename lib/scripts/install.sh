#!/usr/bin/env bash
# Install the library, editable, after its three sibling dependencies.
# Expects the sibling repos checked out beside this one:
#   ../blue-data, ../blue-data-kb-source, ../blue-data-doc-source
# The KB is installed with its llm and search extras: every query and
# extraction calls the LLM (through LiteLLM, to BLUE_DATA_LLM_PROVIDER's
# provider), and the CLI's default KB search is BM25.
# Usage: bash lib/scripts/install.sh        (run from anywhere; uses the active python3)
set -euo pipefail

LIB_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SIBLINGS="$(cd "$LIB_ROOT/../.." && pwd)"

for repo in blue-data blue-data-kb-source blue-data-doc-source; do
    if [ ! -d "$SIBLINGS/$repo/lib" ]; then
        echo "error: sibling repo not found at $SIBLINGS/$repo — clone it beside this repo first" >&2
        exit 1
    fi
done

pip() { python3 -m pip install -q "$@"; }

echo "Installing blue-data, blue-data-kb-source[llm,search], blue-data-doc-source..."
pip -e "$SIBLINGS/blue-data/lib"
pip -e "$SIBLINGS/blue-data-kb-source/lib[llm,search]"
pip -e "$SIBLINGS/blue-data-doc-source/lib"

echo "Installing blue-data-user-source (with the email and webhook contact extras, and dev tools)..."
pip -e "$LIB_ROOT[webhook,email,dev]"
