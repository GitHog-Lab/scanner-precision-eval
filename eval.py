#!/usr/bin/env python3
"""
GitHog scanner precision/recall eval harness.

Runs the scanner against this eval repo, compares findings against MANIFEST.yaml
ground truth, and reports precision, recall, F1, speed, and per-detector
breakdown. Writes both a human-readable report and a machine-readable JSON
score file for trend tracking across iterations.

Usage:
    python3 eval.py --scanner /path/to/githog-scanner-binary
    python3 eval.py --scanner ../scanner/scanner --output report.json
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


def parse_yaml_manifest(path):
    """Minimal YAML parser for our manifest schema. Avoids requiring PyYAML."""
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
    if v == "null" or v == "~":
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


def run_scanner(scanner_path, repo_path, timeout=300):
    """Invoke the scanner and return (findings, duration_seconds, stderr)."""
    cmd = [scanner_path, "scan", "--repo-path", str(repo_path), "--json"]
    start = time.perf_counter()
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    duration = time.perf_counter() - start
    if proc.returncode != 0:
        print(f"[ERROR] scanner exited {proc.returncode}", file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        sys.exit(2)
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        print(f"[ERROR] could not parse scanner JSON: {e}", file=sys.stderr)
        print("First 2000 chars of stdout:", file=sys.stderr)
        print(proc.stdout[:2000], file=sys.stderr)
        sys.exit(2)
    return result.get("findings", []), duration, proc.stderr


def normalize_path(path, repo_root):
    """Strip repo_root prefix so manifest and scanner paths align."""
    p = Path(path)
    rr = Path(repo_root).resolve()
    try:
        return str(p.resolve().relative_to(rr))
    except ValueError:
        return str(p)


def match_finding_to_plant(finding, plants_by_file):
    """Match a finding to a plant. Two-stage:
       1. Exact (file, line ± 2) match — preferred.
       2. Multi-line fallback: same file + same detector_id, any line.
          Catches multi-line PEM/JWT detectors whose match position differs
          from the plant's BEGIN-line position.
    """
    fp = finding["file_path"]
    fl = finding.get("line_number", 0)
    candidates = plants_by_file.get(fp, [])

    # Stage 1: line-exact match (±2 lines)
    for plant in candidates:
        if abs(plant.get("line", 0) - fl) <= 2:
            return plant

    # Stage 2: file + detector_id match for multi-line credentials
    fid = finding.get("detector_id")
    for plant in candidates:
        if plant.get("detector_id") == fid and plant.get("expected_fire", True):
            return plant

    return None


def score(plants, findings, repo_root):
    """
    Match findings to plants. Compute:
      - true_positives: findings on lines where expected_fire=true
      - false_positives: findings with no matching plant (or matching expected_fire=false)
      - false_negatives: plants with expected_fire=true not matched by any finding
      - true_negatives: plants with expected_fire=false not matched (implicit)
    """
    # Normalize finding paths
    for f in findings:
        f["file_path"] = normalize_path(f["file_path"], repo_root)

    # Bucket plants by file
    plants_by_file = defaultdict(list)
    for p in plants:
        plants_by_file[p["file"]].append(p)

    # Track which plants got matched
    matched_plants = set()

    # Classify each finding
    tp = []
    fp = []
    for finding in findings:
        plant = match_finding_to_plant(finding, plants_by_file)
        if plant is None:
            fp.append(finding)
            continue
        plant_key = (plant["file"], plant.get("line", 0))
        if plant.get("expected_fire", True):
            # Detector ID match check (lenient — finding's detector_id may differ from plant's)
            if "detector_id" in plant and plant["detector_id"]:
                if finding["detector_id"] != plant["detector_id"]:
                    # Still a TP, but wrong detector fired — note this
                    finding["_wrong_detector"] = True
            tp.append({"finding": finding, "plant": plant})
            matched_plants.add(plant_key)
        else:
            # Plant says should NOT fire — this is an FP
            fp.append({**finding, "_planted_negative": True, "_plant_notes": plant.get("notes", "")})

    # FNs: positive plants with no matching finding
    fn = []
    for p in plants:
        if not p.get("expected_fire", True):
            continue
        if (p["file"], p.get("line", 0)) not in matched_plants:
            fn.append(p)

    # Negative plants correctly NOT flagged (implicit TN — just count them)
    tn_count = sum(1 for p in plants if not p.get("expected_fire", True)) - sum(
        1 for x in fp if isinstance(x, dict) and x.get("_planted_negative")
    )

    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn_count": tn_count,
    }


def compute_metrics(s):
    tp = len(s["tp"])
    fp = len(s["fp"])
    fn = len(s["fn"])
    tn = s["tn_count"]
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    return {
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "true_negatives": tn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
    }


def per_detector_breakdown(s):
    """Group results by detector ID."""
    by_det = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    for entry in s["tp"]:
        det = entry["finding"]["detector_id"]
        by_det[det]["tp"] += 1
    for entry in s["fp"]:
        if isinstance(entry, dict):
            det = entry.get("detector_id", "unknown")
        else:
            det = "unknown"
        by_det[det]["fp"] += 1
    for plant in s["fn"]:
        det = plant.get("detector_id", "unknown")
        by_det[det]["fn"] += 1

    rows = []
    for det, counts in sorted(by_det.items(), key=lambda x: x[0] or ""):
        tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
        p = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        r = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        rows.append({"detector": det, "tp": tp, "fp": fp, "fn": fn, "precision": p, "recall": r})
    return rows


def print_report(metrics, duration, file_count, byte_count, breakdown, s, max_listing=20):
    print()
    print("=" * 78)
    print(" GitHog Scanner Precision/Recall Eval")
    print("=" * 78)
    print(f" Scan duration: {duration:.2f}s ({file_count} files, {byte_count / 1024 / 1024:.1f} MB)")
    print(f" Throughput:    {file_count / duration:.0f} files/sec, {byte_count / duration / 1024 / 1024:.1f} MB/sec")
    print()
    print(f" True positives:  {metrics['true_positives']:5d}")
    print(f" False positives: {metrics['false_positives']:5d}")
    print(f" False negatives: {metrics['false_negatives']:5d}")
    print(f" True negatives:  {metrics['true_negatives']:5d}")
    print()
    print(f" Precision: {metrics['precision'] * 100:6.2f}%   (TP / (TP+FP))")
    print(f" Recall:    {metrics['recall'] * 100:6.2f}%   (TP / (TP+FN))")
    print(f" F1 score:  {metrics['f1'] * 100:6.2f}%")
    print()

    if s["fp"]:
        print(f" Top {min(max_listing, len(s['fp']))} false positives:")
        for fp in s["fp"][:max_listing]:
            if isinstance(fp, dict):
                det = fp.get("detector_id", "?")
                fpath = fp.get("file_path", "?")
                line = fp.get("line_number", "?")
                txt = (fp.get("matched_text", "") or "")[:50]
                marker = " (planted negative)" if fp.get("_planted_negative") else ""
                print(f"   {det:35s} {fpath}:{line}  {txt}{marker}")
        if len(s["fp"]) > max_listing:
            print(f"   ... and {len(s['fp']) - max_listing} more")
        print()

    if s["fn"]:
        print(f" Top {min(max_listing, len(s['fn']))} false negatives (missed plants):")
        for fn in s["fn"][:max_listing]:
            det = fn.get("detector_id", "?")
            fpath = fn.get("file", "?")
            line = fn.get("line", "?")
            notes = (fn.get("notes", "") or "")[:50]
            print(f"   {det:35s} {fpath}:{line}  {notes}")
        if len(s["fn"]) > max_listing:
            print(f"   ... and {len(s['fn']) - max_listing} more")
        print()

    print(" Per-detector breakdown (top issues first):")
    sorted_rows = sorted(breakdown, key=lambda r: (r["fn"] + r["fp"]), reverse=True)
    print(f" {'Detector':35s} {'TP':>4s} {'FP':>4s} {'FN':>4s} {'Prec':>7s} {'Rec':>7s}")
    print(f" {'-'*35} {'-'*4} {'-'*4} {'-'*4} {'-'*7} {'-'*7}")
    for row in sorted_rows[:30]:
        if row["fp"] == 0 and row["fn"] == 0:
            continue
        print(
            f" {row['detector']:35s} {row['tp']:4d} {row['fp']:4d} {row['fn']:4d} "
            f"{row['precision']*100:6.1f}% {row['recall']*100:6.1f}%"
        )
    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scanner", required=True, help="Path to githog scanner binary")
    ap.add_argument("--repo", default=".", help="Path to this eval repo (default: current dir)")
    ap.add_argument("--manifest", default="MANIFEST.yaml", help="Manifest file (relative to repo)")
    ap.add_argument("--output", default=None, help="Write JSON score to this path")
    ap.add_argument("--list-cap", type=int, default=20, help="Max FPs/FNs to print")
    args = ap.parse_args()

    repo_root = Path(args.repo).resolve()
    manifest_path = repo_root / args.manifest

    if not manifest_path.exists():
        print(f"[ERROR] manifest not found at {manifest_path}", file=sys.stderr)
        sys.exit(2)

    print(f"[INFO] loading manifest: {manifest_path}")
    plants = parse_yaml_manifest(manifest_path)
    print(f"[INFO] {len(plants)} planted entries")

    print(f"[INFO] running scanner: {args.scanner} scan --repo {repo_root}")
    findings, duration, stderr_text = run_scanner(args.scanner, repo_root)
    print(f"[INFO] scanner returned {len(findings)} findings in {duration:.2f}s")

    # Pull file/byte counts from scanner stderr if available
    file_count = len([p for p in repo_root.rglob("*") if p.is_file()])
    byte_count = sum(p.stat().st_size for p in repo_root.rglob("*") if p.is_file())

    s = score(plants, findings, repo_root)
    metrics = compute_metrics(s)
    breakdown = per_detector_breakdown(s)

    print_report(metrics, duration, file_count, byte_count, breakdown, s, max_listing=args.list_cap)

    if args.output:
        out = {
            "metrics": metrics,
            "duration_seconds": duration,
            "files_scanned": file_count,
            "bytes_scanned": byte_count,
            "throughput_files_per_sec": round(file_count / duration, 2),
            "throughput_mb_per_sec": round(byte_count / duration / 1024 / 1024, 2),
            "per_detector": breakdown,
            "false_positives": [
                {
                    "detector_id": fp.get("detector_id") if isinstance(fp, dict) else None,
                    "file_path": fp.get("file_path") if isinstance(fp, dict) else None,
                    "line_number": fp.get("line_number") if isinstance(fp, dict) else None,
                    "matched_text": fp.get("matched_text") if isinstance(fp, dict) else None,
                    "planted_negative": fp.get("_planted_negative", False) if isinstance(fp, dict) else False,
                }
                for fp in s["fp"]
            ],
            "false_negatives": [
                {
                    "detector_id": p.get("detector_id"),
                    "file": p.get("file"),
                    "line": p.get("line"),
                    "notes": p.get("notes"),
                }
                for p in s["fn"]
            ],
        }
        with open(args.output, "w") as f:
            json.dump(out, f, indent=2)
        print(f"[INFO] wrote score to {args.output}")

    # Exit code: 0 if F1 >= 0.95, 1 otherwise — useful for CI
    sys.exit(0 if metrics["f1"] >= 0.95 else 1)


if __name__ == "__main__":
    main()
