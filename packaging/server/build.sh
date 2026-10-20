#!/bin/sh
# Run on the target distribution; no Docker image is needed or extracted.
set -eu
exec python3 "$(dirname "$0")/build.py" "$@"
