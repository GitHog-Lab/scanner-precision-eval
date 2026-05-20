# GitHog engine status — canonical summary

> Snapshot of the entire scanner pipeline. What's built, what's proven on
> the public benchmark, what works, what doesn't, what's next.
>
> Last updated: May 2026 (after the Wave 1-5 detector push + AI + live-verify
> layers landed on `jenish-main`).

## Headline numbers (proven, reproducible — May 2026, post Wave 5 plants)

| Metric | GitHog | Gitleaks | TruffleHog |
|---|---:|---:|---:|
| Precision | **99.03%** | 96.84% | 95.73% |
| Recall | **96.44%** | 80.29% | 46.96% |
| F1 | **97.72%** | 87.79% | 63.01% |
| Speed (files/sec) | **724** | 386 | 59 |
| Detector count | 727 | ~150 | 870 |

GitHog leads all 4 metrics. F1 advantage: +9.93pp vs Gitleaks, +34.71pp vs TruffleHog.

Reproduce: `python3 eval_compare.py` in this repo.

## Detection layers (9 total)

| Layer | Count | Built | Tested | Public benchmark | What works | Known gaps |
|---|---:|:---:|:---:|:---:|---|---|
| Secret detectors (regex) | 699 | ✅ | ✅ 460 tests | ✅ F1 96.46% | Aho-Corasick prefix prefilter, 80% TruffleHog parity, 2000 f/s | Wave 5 (196 vendors) not yet exercised by plants. 50 known FNs in long-tail vendors. |
| PII / sensitive data | 14 | ✅ | ✅ unit tests | ❌ no eval plants | Email, US phone, SSN, US passport, UK NI, 4 credit cards, IBAN, US bank routing (ABA), internal URL/hostname, AWS DB endpoint | International phone, EU passports, HIPAA/PHI, Canadian SIN, driver's licenses, IP/MAC addresses, JWT-embedded user data, biometric IDs |
| Sensitive file detection | 25 patterns | ✅ | ✅ unit tests | ❌ no benchmark | `.env`, `.pem`, `.key`, `.p12`, `.pfx`, `.jks`, `id_rsa`/`dsa`/`ecdsa`/`ed25519`, `.npmrc`, `.aws/credentials`, `.docker/config.json`, etc. | Path-only — doesn't read contents. Public-cert-only `.pem` files flagged as critical (FP risk). |
| AI FP filter | 1 model | ✅ scaffolded | ✅ fail-open verified | ❌ not measured | Claude Haiku batched 25/req, parallel 8, ~$0.16/1k findings, `--ai-verify` flag | Threshold sweep script written but never run. F1 lift theoretical. |
| AI FN recovery | 1 model | ✅ scaffolded | ✅ fail-open verified | ❌ not measured | High-entropy candidates near credential-context keywords → Haiku batch judgment, ~$0.32/100k lines, `--ai-recover` flag | Never run against eval. Entropy threshold + context window untuned. |
| Live verification | 11 vendors | ✅ framework + 11 verifiers | ✅ Stripe verified | ❌ no eval | Stripe (3 variants), GitHub (3), OpenAI (2), Anthropic, AWS (prefix only) | 19 vendors still TODO (Slack, Twilio, SendGrid, Datadog, GitLab, Sentry, Plaid, Snyk, Auth0…). AWS needs paired-secret logic. |
| Git history scan | full | ✅ | ❌ not benchmarked | ❌ not in eval | `--history` flag walks commits, scans diffs, attaches commit metadata | No throughput benchmark vs TruffleHog. Eval only tests working tree. |
| Ghost commit recovery | 1 mode | ✅ | ❌ not tested this cycle | ❌ no benchmark | `ghost-remote` cmd: GH Archive force-push events → fetch dangling commits → scan | End-to-end smoke test pending post-merge. |
| Security posture scoring | 100-point | ✅ | ✅ unit tests | ❌ not benchmarked | Composite (secrets / sensitive_data / sensitive_files / gitignore) with F-A letter grade | Scoring weights heuristic — not calibrated against customer outcomes. |

## CLI surface

```bash
githog-scanner scan --repo-path .                       # default: free, fast, regex+entropy only
                    --ai-verify                          # FP filter via Claude Haiku
                    --ai-verify-threshold 0.7
                    --ai-recover                         # FN recovery via Claude Haiku
                    --ai-recover-threshold 0.75
                    --ai-recover-max-candidates 500
                    --live-verify                        # real vendor API liveness checks
                    --history                            # also scan git commits
                    --skip-tests                         # skip test fixtures
                    --sensitive-data                     # PII (default on)
```

All AI / network features are **off by default**. The free path stays free; paid features are explicit opt-in.

## What's truly proven this benchmark cycle

Three layers are **public-benchmark-proven** (anyone can reproduce on this repo):

1. **Secret detectors (regex)** — 699 detectors, 96.46% F1, 1991 f/s
2. **Engine itself** (Aho-Corasick + regex + validators) — wins all 4 metrics vs TH+GL
3. **Live-verify (Stripe)** — round-trip verified with real 401 response

Six layers are **built and unit-tested but not benchmarked against peers**:

4. PII / sensitive data (14 detectors)
5. Sensitive file detection (25 path patterns)
6. AI FP filter (compiles, fail-open works)
7. AI FN recovery (compiles, fail-open works)
8. Posture scoring (passes unit tests)
9. Git history scanning (was working, untested this session)

One layer is **architectural / aspirational**:

10. Ghost commit recovery (code present, not exercised in this session)

## Roadmap (priority-ordered)

| P | Item | Effort | Why |
|---|---|---|---|
| P0 | Plant Wave 5 fixtures + re-benchmark | 2 hrs | Proves the 196 newest detectors. F1 lift expected. |
| P0 | Run AI verifier threshold sweep | 30 min + $2 | Quantifies the FP filter lift. |
| P1 | Run AI recovery against the eval | 30 min + $3 | Measure how many of the 30 remaining FNs the AI catches. |
| P1 | Add 5 more live-verify vendors | 4 hrs | Slack, Twilio, SendGrid, Datadog, GitLab. Doubles vendor coverage. |
| P1 | Expand PII to ~30 detectors | 1 day | International + HIPAA + finance. Closes the PII gap. |
| P2 | AWS pairing logic (AKIA + secret) | 1 day | Unlocks full AWS liveness. |
| P2 | Cert vs private key content check | 2 hrs | Drops a known FP cluster on `.pem`/`.key`. |
| P2 | Git history scan vs TruffleHog benchmark | 2 hrs | Prove parity or identify gap. |
| P3 | Ghost commit recovery smoke test | 1 hr | Verify the moat feature post-merge. |
| P3 | Surface CI/CD + repo settings audit in scanner | 1 day | Single-binary matches the product. |

## Public artifacts

- **Scanner:** `github.com/GitHog-Lab/githog/tree/jenish-main`
- **Eval suite:** `github.com/GitHog-Lab/scanner-precision-eval`
- **Benchmark:** [BENCHMARK.md](BENCHMARK.md)
- **This document:** [STATUS.md](STATUS.md)

## Reproducibility

```bash
git clone https://github.com/GitHog-Lab/scanner-precision-eval
cd scanner-precision-eval

# Get the scanner
git clone https://github.com/GitHog-Lab/githog -b jenish-main /tmp/githog
cd /tmp/githog/scanner && go build -o /tmp/githog-scanner . && cd -

# Get the peers
brew install trufflehog gitleaks

# Run the benchmark
python3 eval_compare.py --githog /tmp/githog-scanner
```
