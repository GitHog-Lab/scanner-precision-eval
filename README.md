# scanner-precision-eval

Planted-secret evaluation suite for the **GitHog** secret scanner.

> **All credentials in this repo are FAKE.** They are manufactured fixtures matching real key formats but generated from a random alphabet that ensures they cannot authenticate against any live vendor API. No live API call from any of these tokens will succeed.

## Purpose

GitHog targets 70-80% TruffleHog vendor coverage with higher precision per detector than any peer scanner. This repo is the precision/recall harness used to drive that goal.

For every detector in the GitHog registry, this repo contains:

- **At least 3 true-positive fixtures** in realistic file types (`.env`, `.yaml`, `.toml`, `.json`, `.py`, `.js`, `.go`, `.tf`, `.sh`, `.md`) with the credential planted in a real-world shape
- **At least 2 true-negative fixtures** that look like the credential but are documented placeholders, code identifiers, or non-secret data
- **Edge cases** specific to the detector (multi-line PEM, base64-padded tokens, prefix collisions, etc.)

Plus repo-wide:

- **`true_negatives/`** — strings that visually resemble secrets but are not (UUIDs in SQL migrations, git SHAs in version control, semver numbers, license keys for OSS software)
- **`edge_cases/`** — adversarial inputs (secrets-in-comments, secrets-in-test-fixtures-that-should-still-fire, secrets-inside-base64-blobs, secrets-split-across-lines)
- **`ghost_commits/`** — secrets planted then force-push-removed, testing GitHog's ghost commit recovery via GH Archive

## Repo layout

```
scanner-precision-eval/
├── README.md                   # This file
├── MANIFEST.yaml               # Machine-readable ground truth: file → line → detector
├── true_positives/             # Should fire
│   ├── ai_ml/
│   ├── auth/
│   ├── ci_cd/
│   ├── cloud/
│   ├── code_analysis/
│   ├── collaboration/
│   ├── communication/
│   ├── crypto/
│   ├── cryptocurrency/
│   ├── data_engineering/
│   ├── database/
│   ├── email/
│   ├── feature_flags/
│   ├── monitoring/
│   ├── payment/
│   ├── project_management/
│   ├── saas/
│   ├── secret_management/
│   ├── analytics/
│   ├── video_media/
│   └── cdn/
├── true_negatives/             # Must NOT fire
│   ├── placeholders.md         # YOUR_API_KEY, ${API_KEY}, your-token-here
│   ├── examples_in_docs.md     # Vendor docs example placeholders
│   ├── uuids_in_db_migrations.sql
│   ├── git_shas.py             # SHA-1, SHA-256, commit refs
│   ├── semver_versions.txt
│   ├── license_keys_oss.txt    # Real public license keys (e.g. for AGPL software)
│   └── test_fixtures/          # Files explicitly named *_test.go, *_test.py
├── edge_cases/
│   ├── multiline_pem.pem
│   ├── secret_in_comment.py
│   ├── secret_in_base64_blob.txt
│   ├── jwt_in_jwt.txt          # JWT containing a JWT in its payload
│   └── ...
└── ghost_commits/              # Branch with secrets that get force-pushed away
    └── (history-only; see git log)
```

## Manifest format

`MANIFEST.yaml` is the ground truth for every planted secret. Each entry:

```yaml
- file: true_positives/cloud/aws_keys.env
  line: 4
  detector_id: aws_access_key_id
  detector_name: AWS Access Key ID
  matched_text: AKIAIOSFODNN7EXAMPLE
  expected_fire: true
  notes: Real AWS-shape access key ID. The example value is from AWS docs but its character distribution matches real keys.
```

For true negatives:

```yaml
- file: true_negatives/uuids_in_db_migrations.sql
  line: 12
  detector_id: null
  matched_text: 9af72c81-d4b3-4c19-b8f5-2e76c1a948b3
  expected_fire: false
  notes: UUID used as a primary key in a CREATE TABLE statement. Surrounding SQL syntax must prevent any detector with UUID shape from firing.
```

## Running the eval

```bash
# Clone this repo
git clone https://github.com/GitHog-Lab/scanner-precision-eval.git

# Run GitHog scanner against the clone
githog-scanner --repo ./scanner-precision-eval --output findings.json

# Score against the manifest
githog-eval --manifest scanner-precision-eval/MANIFEST.yaml --findings findings.json
```

The eval tool reports:

```
Precision: 98.4% (true positives / total findings)
Recall:    96.1% (true positives caught / true positives planted)
F1:        97.2%
Speed:     2.3 seconds for 487 files (211 files/sec)

False positives: 8 findings on non-secret data
False negatives: 19 planted secrets not caught

Per-detector breakdown:
  aws_access_key_id        TP=12 FP=0  FN=0   precision=100% recall=100%
  openai_api_key           TP=8  FP=0  FN=1   precision=100% recall=89%
  ...
```

## Security

These are FAKE credentials in a PUBLIC repo. Anyone scanning this repo with TruffleHog/GitGuardian/Gitleaks will see findings. That's the point — this repo is a public benchmark.

The strings are constructed from a random alphabet that guarantees they will fail liveness verification against any vendor's API.
