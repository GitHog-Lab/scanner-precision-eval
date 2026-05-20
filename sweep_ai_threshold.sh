#!/usr/bin/env bash
# AI FP filter threshold sweep — measures precision lift at each threshold.
#
# Runs the scanner with --ai-verify at five threshold values, records
# precision/recall/F1 after each run, then picks the optimal default.
#
# Cost: ~$0.16 per threshold × 5 thresholds × the ~503 findings in the eval
# repo ≈ $4 total against the live Anthropic API. Skip with --dry-run to
# print the plan without making API calls.
#
# Prerequisites:
#   export ANTHROPIC_API_KEY=...
#   GitHog scanner built at /tmp/githog-scanner
#   eval repo at /tmp/scanner-precision-eval
#
# Usage:
#   ./sweep_ai_threshold.sh
#   ./sweep_ai_threshold.sh --dry-run

set -euo pipefail

SCANNER=${SCANNER:-/tmp/githog-scanner}
EVAL_REPO=${EVAL_REPO:-/tmp/scanner-precision-eval}
DRY=${1:-}

thresholds=(0.5 0.6 0.7 0.8 0.9)

echo "AI threshold sweep — eval repo: $EVAL_REPO"
echo "Thresholds: ${thresholds[*]}"
echo ""

if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ "$DRY" != "--dry-run" ]; then
    echo "ANTHROPIC_API_KEY not set — exiting. Use --dry-run to plan without API calls." >&2
    exit 1
fi

# Baseline (no AI verifier)
echo "=== Baseline (no AI verifier) ==="
python3 "$EVAL_REPO/eval.py" --scanner "$SCANNER" --repo "$EVAL_REPO" --output /tmp/sweep-baseline.json 2>&1 \
    | grep -E "Precision|Recall|F1" | head -3

if [ "$DRY" = "--dry-run" ]; then
    echo ""
    echo "(dry run — skipping --ai-verify runs)"
    exit 0
fi

# Sweep
for t in "${thresholds[@]}"; do
    echo ""
    echo "=== threshold = $t ==="
    out="/tmp/sweep-t${t}.json"
    findings="/tmp/sweep-t${t}-findings.json"
    "$SCANNER" scan --repo-path "$EVAL_REPO" --json \
        --ai-verify --ai-verify-threshold "$t" > "$findings" 2>/dev/null
    # Inject the AI-verified findings into a manifest scoring run
    # eval.py expects to run the scanner itself, so we use the temporary
    # finding file as a fake binary that just cats it (simple hack).
    cat > /tmp/sweep-fake-scanner.sh <<EOF
#!/usr/bin/env bash
cat "$findings"
EOF
    chmod +x /tmp/sweep-fake-scanner.sh
    python3 "$EVAL_REPO/eval.py" --scanner /tmp/sweep-fake-scanner.sh --repo "$EVAL_REPO" --output "$out" 2>&1 \
        | grep -E "Precision|Recall|F1" | head -3
done

# Summary
echo ""
echo "==================== SUMMARY ===================="
printf "%-12s  %-10s  %-10s  %-10s\n" "threshold" "precision" "recall" "F1"
for t in baseline "${thresholds[@]}"; do
    f=/tmp/sweep-${t}.json
    if [ "$t" = "baseline" ]; then
        f=/tmp/sweep-baseline.json
    else
        f=/tmp/sweep-t${t}.json
    fi
    if [ -f "$f" ]; then
        python3 -c "import json; d=json.load(open('$f'))['metrics']; print(f'$t  {d[\"precision\"]*100:.2f}%  {d[\"recall\"]*100:.2f}%  {d[\"f1\"]*100:.2f}%')"
    fi
done
