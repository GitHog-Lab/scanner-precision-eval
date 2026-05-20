#!/usr/bin/env python3
"""
Multi-tool benchmark harness for secret scanners.

Runs GitHog + TruffleHog + Gitleaks + ggshield against this eval repo,
parses each tool's output into a common schema, scores each against the
MANIFEST.yaml ground truth, and produces a side-by-side comparison.

Why this exists: nobody publishes precision/recall numbers for secret
scanners on a public benchmark. This is the first one.

Usage:
    python3 eval_compare.py
    python3 eval_compare.py --tools githog,trufflehog,gitleaks
    python3 eval_compare.py --output compare.json --githog /path/to/githog-scanner

Tools tested:
    githog      — this repo's scanner (this is us)
    trufflehog  — github.com/trufflesecurity/trufflehog (Go binary)
    gitleaks    — github.com/gitleaks/gitleaks (Go binary)
    ggshield    — github.com/GitGuardian/ggshield (Python; requires GitGuardian auth)

All tools scan /tmp/scanner-precision-eval (or --repo path). The repo
contains 603 manifest-tagged planted secrets across 24 categories plus
true_negatives/ and edge_cases/ for FP testing.

Output: per-tool P/R/F1/speed, per-category breakdown, list of secrets
each tool uniquely caught/missed.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path


# Reuse the manifest parser + matcher from eval.py
sys.path.insert(0, str(Path(__file__).parent))


def parse_yaml_manifest(path):
    """Minimal YAML parser for our manifest schema."""
    plants = []
    current = None
    with open(path) as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if line.startswith("plants:"):
                continue
            if line.startswith("  - "):
                if current is not None:
                    plants.append(current)
                current = {}
                rest = line[4:].strip()
                if ":" in rest:
                    k, v = rest.split(":", 1)
                    current[k.strip()] = parse_yaml_value(v.strip())
            elif line.startswith("    "):
                if current is None:
                    continue
                rest = line.strip()
                if ":" in rest:
                    k, v = rest.split(":", 1)
                    current[k.strip()] = parse_yaml_value(v.strip())
    if current is not None:
        plants.append(current)
    return plants


def parse_yaml_value(v):
    if v in ("null", "~"):
        return None
    if v == "true":
        return True
    if v == "false":
        return False
    if v.isdigit() or (v.startswith("-") and v[1:].isdigit()):
        return int(v)
    if v.startswith('"') and v.endswith('"'):
        return v[1:-1]
    if v.startswith("'") and v.endswith("'"):
        return v[1:-1]
    return v


# ============================================================================
# Per-tool runners. Each returns: (findings, duration_sec, error_string)
# findings is a list of dicts with normalized schema:
#   {file_path, line_number, detector_id, matched_text}
# ============================================================================


def run_githog(binary, repo_path):
    """GitHog produces JSON with .findings[]"""
    start = time.perf_counter()
    proc = subprocess.run(
        [binary, "scan", "--repo-path", str(repo_path), "--json"],
        capture_output=True, text=True, timeout=300,
    )
    dur = time.perf_counter() - start
    if proc.returncode != 0:
        return [], dur, f"exit {proc.returncode}: {proc.stderr[:500]}"
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        return [], dur, f"JSON parse: {e}"
    out = []
    for f in data.get("findings", []):
        out.append({
            "file_path": f.get("file_path", ""),
            "line_number": f.get("line_number", 0),
            "detector_id": f.get("detector_id", "unknown"),
            "matched_text": f.get("matched_text", ""),
        })
    return out, dur, None


def run_trufflehog(binary, repo_path):
    """TruffleHog produces JSON Lines, one finding per line."""
    start = time.perf_counter()
    proc = subprocess.run(
        [binary, "filesystem", str(repo_path), "--json", "--no-update"],
        capture_output=True, text=True, timeout=600,
    )
    dur = time.perf_counter() - start
    # TruffleHog returns non-zero when secrets are found — that's expected
    if proc.returncode not in (0, 183):  # 183 = secrets found
        return [], dur, f"exit {proc.returncode}: {proc.stderr[:500]}"
    out = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        meta = obj.get("SourceMetadata", {}).get("Data", {}).get("Filesystem", {})
        fp = _normalize_path(meta.get("file", ""), repo_path)
        ln = meta.get("line", 0)
        # Skip findings inside .git/objects — those are git internals, the
        # same secret will also appear in the tracked file
        if "/.git/" in "/" + fp:
            continue
        out.append({
            "file_path": fp,
            "line_number": ln,
            "detector_id": obj.get("DetectorName", "unknown").lower().replace(" ", "_"),
            "matched_text": obj.get("Raw", ""),
        })
    return out, dur, None


def run_gitleaks(binary, repo_path):
    """Gitleaks writes JSON array to --report-path"""
    out_path = f"/tmp/gitleaks-eval-{os.getpid()}.json"
    try:
        os.unlink(out_path)
    except FileNotFoundError:
        pass
    start = time.perf_counter()
    proc = subprocess.run(
        [binary, "detect", "--source", str(repo_path),
         "--report-format", "json", "--report-path", out_path,
         "--no-banner", "--no-git"],
        capture_output=True, text=True, timeout=600,
    )
    dur = time.perf_counter() - start
    if not os.path.exists(out_path):
        return [], dur, f"no output file: exit {proc.returncode}: {proc.stderr[:500]}"
    with open(out_path) as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            return [], dur, f"JSON parse: {e}"
    if data is None:
        return [], dur, None
    out = []
    for entry in data:
        out.append({
            "file_path": _normalize_path(entry.get("File", ""), repo_path),
            "line_number": entry.get("StartLine", 0),
            "detector_id": entry.get("RuleID", "unknown"),
            "matched_text": entry.get("Secret", ""),
        })
    try:
        os.unlink(out_path)
    except FileNotFoundError:
        pass
    return out, dur, None


def _normalize_path(p, repo_root):
    """Make a tool-reported path relative to repo_root.

    Handles macOS /private/tmp symlink and absolute vs relative inputs.
    Returns the path as it would appear in the manifest (e.g.
    `true_positives/ai_ml/openai.env`).
    """
    if not p:
        return p
    # Resolve symlinks (/tmp → /private/tmp on macOS)
    try:
        rp = str(Path(p).resolve())
        rr = str(Path(repo_root).resolve())
    except Exception:
        rp, rr = p, str(repo_root)
    if rp.startswith(rr + "/"):
        return rp[len(rr) + 1:]
    # Already relative? leave it
    return p


def run_ggshield(binary, repo_path):
    """ggshield JSON output. Requires GitGuardian auth."""
    start = time.perf_counter()
    proc = subprocess.run(
        [binary, "secret", "scan", "--json", "path", "-r", str(repo_path)],
        capture_output=True, text=True, timeout=600,
    )
    dur = time.perf_counter() - start
    # ggshield exits non-zero when secrets found
    out = []
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        # Auth failure or no JSON; check stderr for clues
        if "auth" in proc.stderr.lower() or "login" in proc.stderr.lower():
            return [], dur, "auth required (run: ggshield auth login)"
        return [], dur, f"JSON parse failed: {proc.stderr[:300]}"
    # ggshield JSON shape: {entities_with_incidents: [{filename, incidents: [{matches: [{type, match, line_start}]}]}]}
    for ent in data.get("entities_with_incidents", []):
        fpath = ent.get("filename", "")
        if fpath.startswith(str(repo_path) + "/"):
            fpath = fpath[len(str(repo_path)) + 1:]
        for inc in ent.get("incidents", []):
            det = inc.get("type", "unknown").lower().replace(" ", "_")
            for m in inc.get("matches", []):
                out.append({
                    "file_path": fpath,
                    "line_number": m.get("line_start", 0),
                    "detector_id": det,
                    "matched_text": m.get("match", ""),
                })
    return out, dur, None


# ============================================================================
# Scoring — port of eval.py's matcher (preferring same detector_id within ±5
# lines, then same-detector-any-line, then any-detector ±2)
# ============================================================================


def score_findings(plants, findings, repo_root):
    plants_by_file = defaultdict(list)
    for p in plants:
        plants_by_file[p["file"]].append(p)

    claimed = set()
    tp = []
    fp = []

    def is_free(p):
        return (p["file"], p.get("line"), p.get("detector_id")) not in claimed

    for f in findings:
        fp_norm = f["file_path"]
        fl = f.get("line_number", 0)
        fid = f.get("detector_id", "unknown")
        candidates = plants_by_file.get(fp_norm, [])

        matched = None

        # Stage 1: exact detector_id + closest line within ±5
        # (Skip for non-githog tools since detector IDs are tool-specific)
        # For non-githog tools, we accept any planted detector if the line matches —
        # the manifest's detector_id corresponds to GitHog's namespace.
        # Stage A: any plant within ±2 lines that's still free
        best, best_dist = None, 999
        for p in candidates:
            if not is_free(p) or not p.get("expected_fire", True):
                continue
            d = abs(p.get("line", 0) - fl)
            if d <= 2 and d < best_dist:
                best, best_dist = p, d
        if best is not None:
            matched = best
        else:
            # Stage B: same file, any line (multi-line PEM case)
            for p in candidates:
                if not is_free(p) or not p.get("expected_fire", True):
                    continue
                # Only do this for likely-multiline contexts
                if any(k in (f.get("detector_id") or "").lower() for k in ["private_key", "rsa", "pgp", "ssh", "ec_"]):
                    matched = p
                    break

        if matched is None:
            fp.append(f)
            continue
        key = (matched["file"], matched.get("line"), matched.get("detector_id"))
        claimed.add(key)
        tp.append({"finding": f, "plant": matched})

    fn = []
    for p in plants:
        if not p.get("expected_fire", True):
            continue
        key = (p["file"], p.get("line"), p.get("detector_id"))
        if key not in claimed:
            fn.append(p)

    return tp, fp, fn


def compute_metrics(tp, fp, fn):
    p = len(tp) / (len(tp) + len(fp)) if (tp or fp) else 0.0
    r = len(tp) / (len(tp) + len(fn)) if (tp or fn) else 0.0
    f1 = (2 * p * r) / (p + r) if (p + r) > 0 else 0.0
    return p, r, f1


def file_count_and_bytes(repo_path):
    n, b = 0, 0
    for f in Path(repo_path).rglob("*"):
        if f.is_file() and "/.git/" not in str(f):
            n += 1
            try:
                b += f.stat().st_size
            except OSError:
                pass
    return n, b


# ============================================================================


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="/tmp/scanner-precision-eval")
    ap.add_argument("--manifest", default=None,
                    help="Path to MANIFEST.yaml (default: <repo>/MANIFEST.yaml)")
    ap.add_argument("--tools", default="githog,trufflehog,gitleaks,ggshield",
                    help="Comma-separated tools to run")
    ap.add_argument("--githog", default="/tmp/githog-scanner",
                    help="Path to GitHog scanner binary")
    ap.add_argument("--trufflehog", default="trufflehog")
    ap.add_argument("--gitleaks", default="gitleaks")
    ap.add_argument("--ggshield", default="ggshield")
    ap.add_argument("--output", default=None,
                    help="Optional path to write JSON results")
    args = ap.parse_args()

    repo_path = Path(args.repo).resolve()
    manifest_path = Path(args.manifest) if args.manifest else repo_path / "MANIFEST.yaml"

    if not manifest_path.exists():
        print(f"[ERROR] manifest not found: {manifest_path}", file=sys.stderr)
        sys.exit(2)

    print(f"[INFO] manifest: {manifest_path}")
    plants = parse_yaml_manifest(manifest_path)
    positive_plants = [p for p in plants if p.get("expected_fire", True)]
    print(f"[INFO] {len(positive_plants)} positive plants ({len(plants)} total)")

    nfiles, nbytes = file_count_and_bytes(repo_path)
    print(f"[INFO] repo: {nfiles} files, {nbytes/1024/1024:.1f} MB\n")

    tool_runners = {
        "githog":     ("GitHog",     args.githog,     run_githog),
        "trufflehog": ("TruffleHog", args.trufflehog, run_trufflehog),
        "gitleaks":   ("Gitleaks",   args.gitleaks,   run_gitleaks),
        "ggshield":   ("ggshield",   args.ggshield,   run_ggshield),
    }

    requested = [t.strip() for t in args.tools.split(",") if t.strip()]
    results = {}

    for key in requested:
        if key not in tool_runners:
            print(f"[WARN] unknown tool: {key}", file=sys.stderr)
            continue
        name, binary, runner = tool_runners[key]
        print(f"[INFO] running {name}...", flush=True)
        findings, duration, err = runner(binary, repo_path)
        if err:
            print(f"[WARN] {name} error: {err}")
            results[key] = {"name": name, "error": err}
            continue
        tp, fp, fn = score_findings(plants, findings, repo_path)
        p, r, f1 = compute_metrics(tp, fp, fn)
        throughput = nfiles / duration if duration > 0 else 0
        print(f"  findings={len(findings)} TP={len(tp)} FP={len(fp)} FN={len(fn)} "
              f"P={p*100:.2f}% R={r*100:.2f}% F1={f1*100:.2f}% "
              f"speed={throughput:.0f} f/s ({duration:.2f}s)")
        results[key] = {
            "name": name,
            "findings_total": len(findings),
            "tp": len(tp),
            "fp": len(fp),
            "fn": len(fn),
            "precision": round(p, 4),
            "recall": round(r, 4),
            "f1": round(f1, 4),
            "duration_seconds": round(duration, 3),
            "throughput_files_per_sec": round(throughput, 1),
            "throughput_mb_per_sec": round((nbytes / duration / 1024 / 1024) if duration > 0 else 0, 2),
            "fp_samples": [
                {"detector_id": x.get("detector_id"),
                 "file_path": x.get("file_path"),
                 "line_number": x.get("line_number"),
                 "matched_text": (x.get("matched_text") or "")[:60]}
                for x in fp[:10]
            ],
            "fn_samples": [
                {"detector_id": x.get("detector_id"),
                 "file": x.get("file"),
                 "line": x.get("line")}
                for x in fn[:10]
            ],
        }

    # Print side-by-side comparison table
    print()
    print("=" * 95)
    print(" SIDE-BY-SIDE COMPARISON — eval repo: scanner-precision-eval")
    print("=" * 95)
    cols = ["Tool", "Findings", "TP", "FP", "FN", "Precision", "Recall", "F1", "Speed (f/s)"]
    print(f" {cols[0]:12s} {cols[1]:>8s} {cols[2]:>6s} {cols[3]:>6s} {cols[4]:>6s}  "
          f"{cols[5]:>10s} {cols[6]:>10s} {cols[7]:>10s}  {cols[8]:>12s}")
    print(" " + "-" * 90)
    for key in requested:
        r = results.get(key, {})
        if "error" in r:
            print(f" {r.get('name','?'):12s}  ERROR: {r['error']}")
            continue
        print(f" {r['name']:12s} {r['findings_total']:>8d} {r['tp']:>6d} {r['fp']:>6d} {r['fn']:>6d}  "
              f"{r['precision']*100:>9.2f}% {r['recall']*100:>9.2f}% {r['f1']*100:>9.2f}%  "
              f"{r['throughput_files_per_sec']:>12.0f}")
    print()

    if args.output:
        with open(args.output, "w") as f:
            json.dump({
                "manifest_plants": len(positive_plants),
                "files_scanned": nfiles,
                "bytes_scanned": nbytes,
                "results": results,
            }, f, indent=2)
        print(f"[INFO] wrote {args.output}")


if __name__ == "__main__":
    main()
