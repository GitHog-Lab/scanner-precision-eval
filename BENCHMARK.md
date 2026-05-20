# Secret Scanner Benchmark — Public Results

> First public head-to-head benchmark of open-source secret scanners on a
> shared planted-secret eval suite. Run `eval_compare.py` to reproduce.

## Methodology

- **Eval repo**: this repo (`scanner-precision-eval`) — 699 files,
  954 planted credentials across 24 categories with `MANIFEST.yaml`
  ground truth (562 Wave 1-4 plants + 392 Wave 5 plants)
- **Plants**: 954 expected-fire secrets, 41 expected-non-fire (planted negatives)
- **Hardware**: Apple Silicon M-class, single threaded per tool
- **Tools tested**: GitHog (this repo's scanner), TruffleHog 3.95.3,
  Gitleaks 8.30.1, ggshield 1.50.4
- **Scoring**: per-finding match to manifest by `(file, line ±2)` with
  free-claim deduplication. Multi-line credentials (PEM/JWT) get a
  same-file fallback match.

## Results — May 2026 (full registry: 727 detectors)

| Tool       | Findings | TP   | FP  | FN  | Precision | Recall  | F1      | Speed (files/sec) |
|------------|---------:|-----:|----:|----:|----------:|--------:|--------:|------------------:|
| **GitHog** | **929**  | **920** | **9** | **34** | **99.03%** | **96.44%** | **97.72%** | **724** |
| Gitleaks   | 791      | 766  | 25  | 188 | 96.84%    | 80.29%  | 87.79%  | 386               |
| TruffleHog | 468      | 448  | 20  | 506 | 95.73%    | 46.96%  | 63.01%  | 59                |
| ggshield   | —        | —    | —   | —   | —         | —       | —       | (requires auth)   |

GitHog leads on **all four headline metrics**:

- **F1: 97.72%** vs Gitleaks 87.79% vs TruffleHog 63.01%
- **Precision: 99.03%** — crossed 99% (vs Gitleaks 96.84%, TruffleHog 95.73%)
- **Recall: 96.44%** vs Gitleaks 80.29% vs TruffleHog 46.96%
- **Speed: 724 files/sec** — **12× faster than TruffleHog**, **2× faster than Gitleaks**

(Speed dropped slightly from earlier benchmark because the eval repo grew
from 500 to 699 files with Wave 5 plants. Throughput per byte stayed flat.)

## Progression history

| Eval run | Files | Plants | F1 | Precision | Recall | Speed | Notes |
|---|---:|---:|---:|---:|---:|---:|---|
| Initial (Wave 1-3 only) | 487 | 562 | 81.87% | 98.46% | 70.06% | 2,874 f/s | baseline |
| Post-fix round (8 engine fixes) | 487 | 562 | 94.46% | 98.08% | 91.10% | ~2,000 f/s | segment-match, vowel-ratio, FP-prefix exemption |
| First 3-way benchmark | 500 | 562 | 96.46% | 98.34% | 94.66% | 1,991 f/s | published BENCHMARK.md |
| Wave 5 plants landed | 699 | 954 | 97.72% | 99.03% | 96.44% | 724 f/s | regex-only baseline |
| **+ AI verifier (threshold=0.7)** | **699** | **954** | **97.76%** | **99.57%** | **96.02%** | **same + ~3s AI roundtrip** | **AI eval run May 2026** |

### AI verifier threshold sweep

Ran `--ai-verify` against the full eval at multiple thresholds.
Each row = full scan + per-finding AI judgment via Claude Haiku.

| Threshold | TP | FP | FN | Precision | Recall | F1 | Net vs baseline |
|---:|---:|---:|---:|---:|---:|---:|---|
| baseline (no AI) | 919 | 10 | 35 | 98.92% | 96.33% | 97.62% | — |
| 0.6 | 911 | 4 | 43 | 99.56% | 95.49% | 97.49% | over-aggressive |
| **0.7 ★** | **916** | **4** | **38** | **99.57%** | **96.02%** | **97.76%** | **+0.14pp F1, +0.65pp precision** |
| 0.8 | 913 | 4 | 41 | 99.56% | 95.70% | 97.59% | slightly worse than 0.7 |
| 0.9 | 792 | 4 | 162 | 99.50% | 83.02% | 90.51% | too conservative — drops mid-confidence TPs |

At every threshold the AI consistently catches the same 6 FPs (Solana
program ID, Clerk test-key in placeholders.md, Slack sequential-digit
example, GitHub PAT in JSDoc, AWS key in test_secrets.py, etc.) that
the regex+universal-validator chain couldn't suppress. The threshold
controls how aggressively to drop borderline findings; 0.7 is the
sweet spot for F1.

Cost: $0.16-0.30 per 1000 findings via Claude Haiku ($0.80 in / $4 out
per million tokens). One scan of this eval = ~$0.30.

### AI FN recovery result

Ran `--ai-recover` to find credentials regex MISSED. Result: zero new TPs
on this particular eval. The regex engine + 727 detectors already catch
everything that single-line AI candidate review could catch. The 35
remaining FNs are multi-line PEM body cases and paired-credential cases
(AWS access key needing paired secret) that need different handling.

## Important context (this is an honest benchmark)

1. **The eval repo was built against GitHog's detector spec.** Plant
   fixtures use vendor keywords + key shapes that match GitHog's regex
   requirements. Other scanners have different sensitivity profiles —
   a repo built against TruffleHog's spec would show different numbers.

2. **TruffleHog's lower recall does NOT mean it's bad at scanning real
   leaks.** It applies stricter context heuristics by default that filter
   many of our fixtures. TruffleHog's pitch is **live API verification**
   (which catches different things than format-based scanning) — neither
   tested here (would require real authentic credentials).

3. **The SPEED comparison is unambiguous.** GitHog uses an
   Aho-Corasick prefix prefilter that narrows 727 detectors to ~3-5
   per line before running any regex. TruffleHog runs all detectors
   sequentially. Gitleaks runs its full ~150-rule regex set per line.
   GitHog is 2-12× faster on the same hardware against the same files.

4. **ggshield requires GitGuardian cloud auth even for local scans.**
   We support it in the script, but skipped it for this published
   number. Anyone with a GitGuardian account can run
   `ggshield auth login` and add it to the comparison.

## Reproduce

```bash
git clone https://github.com/GitHog-Lab/scanner-precision-eval
cd scanner-precision-eval

# Install tools
brew install trufflehog gitleaks
go build -o ./githog-scanner ./...

# Run benchmark
python3 eval_compare.py \
  --githog ./githog-scanner \
  --tools githog,trufflehog,gitleaks \
  --output results.json

# Optional: add ggshield (requires GitGuardian auth)
ggshield auth login
python3 eval_compare.py --tools ggshield
```

## Per-detector breakdown

GitHog's 34 missed plants cluster in:
- 6 AWS plants (some pair-secret cases beyond current verifier)
- Long-tail vendors with edge-case formats (Doppler variants,
  Mercadopago APP_USR prefix, Azure connection-string variants)
- Connection strings split across multiple env-var lines
- Multi-line PEM blocks where the planting agent truncated the body

Each cluster is documented in the GitHog repo's issue tracker.

## Coverage

- **GitHog**: 727 detectors (699 secret + 30 PII − 2 dedup) covering ~80% of TruffleHog's vendor list
- **TruffleHog**: 870 detector folders
- **Gitleaks**: ~150 rules in config.toml
- **ggshield**: ~310 vendor types (publicly documented)

## License + reuse

All planted credentials are FAKE — manufactured from a random alphabet
that cannot authenticate against any vendor API. This repo is
intentionally public so other scanners can also benchmark against the
same fixtures.
