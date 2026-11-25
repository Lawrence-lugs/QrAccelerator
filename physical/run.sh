#!/usr/bin/env bash
# Run a command inside the physical-design container.
# Usage (from the repo root): ./physical/run.sh "make -C /workspace/physical generic"
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

if [ "$#" -eq 0 ]; then
    echo "usage: $0 <command>" >&2
    exit 2
fi

exec docker compose -f "$here/compose.yaml" run --rm --entrypoint /bin/bash \
    qracc-physical -lc "$*"
