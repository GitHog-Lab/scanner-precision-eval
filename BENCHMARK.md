# Secret Scanner Benchmark — Public Results

> First public head-to-head benchmark of open-source secret scanners on a
> shared planted-secret eval suite. Run `eval_compare.py` to reproduce.

## Methodology

- **Eval repo**: this repo (`scanner-precision-eval`) — 500 files,
  500+ planted credentials across 24 categories with `MANIFEST.yaml`
  ground truth
- **Plants**: 562 expected-fire secrets, 41 expected-non-fire (planted negatives)
- **Hardware**: Apple Silicon M-class, single threaded per tool
- **Tools tested**: GitHog (this repo's scanner), TruffleHog 3.95.3,
  Gitleaks 8.30.1, ggshield 1.50.4
- **Scoring**: per-finding match to manifest by `(file, line ±2)` with
  free-claim deduplication. Multi-line credentials (PEM/JWT) get a
  same-file fallback match. Plant detector IDs are GitHog's naming;
  cross-tool detector IDs are normalized away in stage A of the matcher.

## Results — single run, May 2026

| Tool       | Findings | TP   | FP  | FN  | Precision | Recall  | F1      | Speed (files/sec) |
|------------|---------:|-----:|----:|----:|----------:|--------:|--------:|------------------:|
| **GitHog** | **541**  | **532** | **9** | **30** | **98.34%** | **94.66%** | **96.46%** | **1,991** |
| Gitleaks   | 435      | 410  | 25  | 152 | 94.25%    | 72.95%  | 82.25%  | 381               |
| TruffleHog | 165      | 159  | 6   | 403 | 96.36%    | 28.29%  | 43.74%  | 77                |
| ggshield   | —        | —    | —   | —   | —         | —       | —       | (requires auth)   |

GitHog leads on **all four headline metrics**:

- **F1: 96.46%** vs Gitleaks 82.25% vs TruffleHog 43.74%
- **Recall: 94.66%** vs Gitleaks 72.95% vs TruffleHog 28.29%
- **Precision: 98.34%** vs TruffleHog 96.36% vs Gitleaks 94.25%
- **Speed: 1,991 files/sec** — **26× faster than TruffleHog**, **5× faster than Gitleaks**

## Important context (this is an honest benchmark)

1. **The eval repo was built against GitHog's detector spec.** Plant
   fixtures use vendor keywords + key shapes that match GitHog's regex
   requirements. Other scanners have different sensitivity profiles —
   for example, TruffleHog applies stricter context heuristics by
   default that filter many of our fixtures. A repo built against
   TruffleHog's spec would show different numbers.

2. **TruffleHog's 28% recall does NOT mean it's bad at scanning real
   leaks.** It means our plants are not in TruffleHog's preferred
   shapes/contexts. TruffleHog's stated strength is high precision
   via live API verification — neither tested here (we ran without
   `--only-verified` because that requires real working credentials).

3. **The SPEED comparison is unambiguous.** GitHog uses an
   Aho-Corasick prefix prefilter that narrows 699 detectors to ~3-5
   per line before running any regex. TruffleHog runs all detectors
   sequentially. Gitleaks runs its full ~150-rule regex set per line.
   GitHog is 5-26× faster on the same hardware against the same files.

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

GitHog's 30 missed plants cluster in:
- Long-tail vendors with edge-case formats (Doppler variants, Mercadopago
  APP_USR prefix, Discord webhook hostname variants)
- Connection strings split across multiple env-var lines (Azure
  Cosmos DB, RDS multi-field credentials)
- Multi-line PEM blocks where the planting agent truncated the body

Each of these is a known cluster — see issue tracking in the GitHog repo.

## Coverage

- **GitHog**: 699 named detectors (covers ~80% of TruffleHog's vendor list)
- **TruffleHog**: 870 detector folders
- **Gitleaks**: ~150 rules in config.toml
- **ggshield**: ~310 vendor types (publicly documented)

## License + reuse

All planted credentials are FAKE — manufactured from a random alphabet
that cannot authenticate against any vendor API. This repo is
intentionally public so other scanners can also benchmark against the
same fixtures.
