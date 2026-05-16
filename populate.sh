#!/usr/bin/env bash
# Regenerate planted fixtures from MANIFEST.yaml metadata.
# Run from the repo root after cloning.
set -euo pipefail
echo "scanner-precision-eval: populate"
echo ""
echo "Run the planting agent or scanner-precision-eval/scripts/plant.py"
echo "to materialize the 463 fixture files referenced in MANIFEST.yaml."
echo ""
echo "Original plants generated via Claude Code agent dispatch."
echo "MANIFEST.yaml has 658 entries with file/line/detector_id ground truth."
