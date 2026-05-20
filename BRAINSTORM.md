# God-tier engine plan — brainstorming + execution order

> Plan for pushing GitHog from "F1 97.76% with caveats" to "100/100 on
> synthetic + first-in-industry real-world benchmark". Four interlocking
> workstreams. Order matters.

## The four directives (verbatim)

1. **Detector expansion (A + B + C)** — long-tail TruffleHog parity + modern
   2026 stack vendors + non-regex structured detectors. Stay ahead.
2. **Verified vs Unverified tier system** — confirmed product direction.
   Three-or-four tier UX with audit trail.
3. **Infra + UX changes** — what specifically needs to change to support
   the tier system end-to-end (scanner output, backend API, frontend).
4. **God-tier (100/100) on synthetic FIRST** — fix every FN/FP cluster on
   the planted-secret eval before chasing real-world. Then real-world.

## Where we are right now (current baseline)

| Metric | Current | God-tier target |
|---|---:|---:|
| Detector count | 727 | ≥870 (TH parity) + 40 modern + 15 structured = **~925** |
| Precision | 99.57% (with AI verify) | **≥99.5%** ✓ already hit |
| Recall | 96.02% | **≥98.5%** (need +2.5pp = +24 TPs) |
| F1 | 97.76% | **≥99%** |
| Speed | 700-2000 f/s | **≥1500 f/s sustained** (currently variable) |
| Live-verify vendors | 20 | **40+** |
| Real-world eval | none | **published benchmark on curated repos** |

## FN cluster analysis (the 38 remaining)

Most impactful FN clusters by count and fix difficulty:

| Cluster | FN count | Fix difficulty | Workstream |
|---|---:|---|---|
| Connection strings split across env-var lines | ~12 | Medium — multi-line aggregation | Task #11 |
| Long-tail vendor edge cases | ~9 | Hard — per-vendor tuning | A/B expansion |
| AWS access key needing paired secret | ~6 | Medium — cross-finding pairing | Task #12 |
| Multi-line PEM body cases | ~5 | Easy — state machine fix | Task #13 |
| Azure connection-string variants | ~5 | Easy — broaden regex | Combined w/ #11 |
| Doppler regex edge | ~3 | Trivial — already fixed but eval lag | Re-eval |
| Test fixture FPs that AI now correctly drops | -3 | Already done by AI verify | Counted as gain |

## FP cluster analysis (the 4 remaining)

| FP | Cause | Fix |
|---|---|---|
| Clerk in `placeholders.md` | Doc example with real shape | AI catches at 0.7 threshold ✓ |
| AWS in `test_secrets.py` | Test fixture file | File-type aware filter |
| GitHub PAT in JSDoc | `@example` block | AI catches at 0.7 threshold ✓ |
| Mailchimp in `examples_in_docs.md` | Doc example | AI catches at 0.7 threshold ✓ |

Conclusion: 3 of 4 FPs are AI-droppable; 1 needs a file-type aware filter.
Combined fix gets us to 0 FPs → precision 100%.

## Workstream 1: Detector expansion (A, B, C)

### Vector A — long-tail TruffleHog parity

Remaining ~150 TruffleHog vendors we haven't ported. Approach:
- Skip vendors with last-commit > 3 years (dead products)
- Skip vendors with regex too generic (16-char alphanumeric, no anchor)
- Realistic addable: ~80-100

Already have research file `/tmp/trufflehog_patterns_batch3.md` with 209
extracted; ~90 worth porting after dedup. Effort: 1-2 days via the same
agent-driven batch we did for Wave 5.

### Vector B — modern 2026 stack (these don't exist in TruffleHog)

Critical 2026 vendors. Listed in priority order (highest customer leak rate first):

**Fintech / banking (10):**
- Mercury (mercury.com) — bearer tokens
- Brex (brex.com) — corporate cards
- Lithic (lithic.com) — card issuing API
- Modern Treasury (moderntreasury.com) — payment ops
- Increase (increase.com) — banking-as-a-service
- Column (column.com) — bank API
- Unit (unit.co) — embedded banking
- Worldpay (worldpay.com)
- Tipalti (tipalti.com)
- Wise (wise.com)

**AI/ML inference (12):**
- Together AI (together.ai)
- Modal (modal.com)
- Lambda Labs (lambdalabs.com)
- Cerebras (cerebras.ai)
- FAL AI (fal.ai)
- Vapi (vapi.ai) — voice agents
- Cartesia (cartesia.ai) — voice
- Murf (murf.ai) — voice
- Hume AI (hume.ai) — emotion
- Mem0 (mem0.ai) — agent memory
- E2B (e2b.dev) — code execution
- Tavus (tavus.io) — AI video

**Data infra (8):**
- Tinybird (tinybird.co)
- Materialize (materialize.com)
- Singlestore (singlestore.com)
- Redpanda (redpanda.com)
- Yugabyte (yugabyte.com)
- Turso (turso.tech) — edge SQLite
- Xata (xata.io)
- PlanetScale OAuth (additional variant)

**Observability (6):**
- Cribl (cribl.io)
- Better Stack (betterstack.com)
- Highlight.io
- Axiom (axiom.co)
- Logtail
- Vector.dev

**Auth/identity (8):**
- Stytch admin (we have project; missing admin)
- Kinde (kinde.com)
- Frontegg (frontegg.com)
- Descope (descope.com)
- SuperTokens (supertokens.com)
- Logto (logto.io)
- Hanko (hanko.io)
- Better-Auth (better-auth.com)

**AI dev tools (6):**
- Bolt.new
- Lovable (lovable.dev)
- Cursor (cursor.sh)
- Windsurf (windsurf.dev)
- Devin (cognition.ai)
- Replit (replit.com)

Total: **50 modern vendors**, not 40. Each needs research from vendor docs
to find published key format. ~3-4 hours research + 1 day implementation.

### Vector C — structured detectors (non-regex)

The novel category. Pattern: don't match on individual lines, match on
file-level structure or multi-line context.

**Concrete C-detectors to ship:**

1. **GitHub Actions: hardcoded secrets in `with:` blocks**
   ```yaml
   - uses: peter-evans/create-pull-request@v5
     with:
       token: ${{ secrets.GITHUB_TOKEN }}  # OK
       token: ghp_xxxxxxxxxxxx              # FLAG
   ```

2. **GitHub Actions: unpinned action versions**
   ```yaml
   uses: actions/checkout@master  # FLAG (mutable ref)
   uses: actions/checkout@v4       # OK (tag)
   uses: actions/checkout@a1b2c3   # OK (SHA pin)
   ```

3. **GitHub Actions: `pull_request_target` with checkout of PR code**
   ```yaml
   on: pull_request_target
   ...
   - uses: actions/checkout@v4
     with:
       ref: ${{ github.event.pull_request.head.sha }}  # FLAG
   ```

4. **Dockerfile: ARG/ENV with secret-shaped values**
   ```dockerfile
   ARG SECRET_KEY=sk-xxxxxxxxxxxx     # FLAG (build arg leaks into layer)
   ENV API_TOKEN=ghp_xxxxxxxxxxxx     # FLAG (env var in image)
   ```

5. **Helm charts: `stringData:` blocks**
   ```yaml
   apiVersion: v1
   kind: Secret
   stringData:
     password: HARDCODED-PLAINTEXT-VALUE  # FLAG
   ```

6. **Terraform state files (.tfstate)**
   - JSON with `"sensitive": true` fields containing raw values
   - Real leak pattern: developers commit .tfstate by mistake

7. **Terraform vars (.tfvars)**
   - Often contains `aws_access_key = "..."` patterns
   - Variable definitions with sensitive defaults

8. **Source maps (.js.map)**
   - Contains original source with secrets embedded
   - Often deployed to production then committed

9. **CircleCI / GitLab CI: hardcoded env in config**
   ```yaml
   variables:
     DATABASE_URL: postgres://prod:passwordhere@...  # FLAG
   ```

10. **Database dumps (.sql)**
    - `INSERT INTO users VALUES ('admin', 'plaintext_password', ...)`
    - Connection strings in `BACKUP DATABASE` statements

11. **Lockfiles with registry credentials**
    - `package-lock.json` with `_authToken` in resolved URLs
    - `Pipfile.lock` with index-url containing credentials

12. **AWS CloudFormation templates**
    - `Parameters` with `Default:` containing keys
    - Hardcoded `Resource:` ARNs with embedded credentials

13. **Kubernetes Secret manifests committed as YAML**
    - `data:` fields with base64-encoded but easily-decoded secrets
    - Need to base64-decode the contents and run secret detectors on the result

14. **`.npmrc` files with registry tokens**
    - `//npm.pkg.github.com/:_authToken=...`
    - Currently we flag the file path but don't extract the token

15. **Encoded secrets in image alt-text / svg / yaml comments**
    - `# Production key: ...` patterns in YAML comments
    - Secrets hidden in non-code fields of config files

Each C-detector is a small Go module that knows the file structure.
Effort: ~2 hours each = 30 hours for all 15. Realistic batch: top 8 in
~1-2 days, rest later.

## Workstream 2: Verification tier system

### The data model

```go
// VerificationTier classifies a finding's confidence after all gates.
type VerificationTier string

const (
    TierVerified   VerificationTier = "verified"     // regex + AI + live-verify all passed
    TierLikely     VerificationTier = "likely"       // regex + AI passed, live-verify n/a
    TierNeedsReview VerificationTier = "needs_review" // regex passed, AI low-confidence
    TierSuppressed VerificationTier = "suppressed"   // regex passed, AI strong reject
)

type Finding struct {
    // ... existing fields ...
    VerificationTier VerificationTier `json:"verification_tier"`
    AIReason         string           `json:"ai_reason,omitempty"`
    AIConfidence     float64          `json:"ai_confidence,omitempty"`
    LiveStatus       string           `json:"live_status,omitempty"` // existing
}
```

### Tier assignment logic

```
Default (no AI, no live-verify):           Likely
+ AI verify says is_real=true (conf>=0.7): Likely
+ AI verify says is_real=true (conf>=0.9): Likely → upgrade if live OK
+ AI verify says is_real=true (conf<0.7):  NeedsReview
+ AI verify says is_real=false:            Suppressed (with reason)
+ Live verify status=live:                 Verified (overrides AI)
+ Live verify status=revoked:              Verified (still real, just dead)
+ Live verify status=unknown:              keep current (AI-determined)
+ Live verify status=no_verifier:          keep current (AI-determined)
```

### CLI output changes

Current:
```json
{"findings": [{detector_id, file_path, line, ...}, ...]}
```

New:
```json
{
  "findings": [...],  // ALL findings, each with verification_tier
  "summary": {
    "verified": 12,
    "likely": 87,
    "needs_review": 3,
    "suppressed": 18
  }
}
```

CLI flags:
- `--show-suppressed` — include suppressed in default output (off by default)
- `--tier verified,likely` — filter to specific tiers
- `--json-summary-only` — emit only the summary, not full findings

### Infra changes required

**Scanner (Go) — done by us:**
- Add VerificationTier enum to types.Finding
- AI verify assigns tier instead of dropping
- Live verify upgrades tier on status=live
- Update output JSON schema
- Add `--show-suppressed`, `--tier` flags

**Backend API (Python/FastAPI):**
- Models need `verification_tier` column on findings table (migration)
- API endpoints return tier in finding objects
- Aggregation endpoints (counts by tier)
- Filter query params on /findings (?tier=verified)

**Frontend (React/TypeScript):**
- New tier badges (color-coded chips)
- Default view filter (verified + likely + needs_review, suppressed hidden)
- "Show suppressed" toggle in scan results page
- Per-tier counts in scan summary card
- AI reason text shown as tooltip on hover for needs_review/suppressed

**Database:**
- Migration: ALTER TABLE findings ADD COLUMN verification_tier TEXT
- Migration: ALTER TABLE findings ADD COLUMN ai_confidence REAL
- Migration: ALTER TABLE findings ADD COLUMN ai_reason TEXT
- Migration: ALTER TABLE findings ADD COLUMN live_status_json TEXT

Estimated effort:
- Scanner: 4 hours (this session)
- Backend: 4 hours (need DB migration + endpoint updates)
- Frontend: 6-8 hours (new components + filtering UI)
- Database: 1 hour (migration script)

**Total: ~16 hours of work across stack.** This is the biggest item.

## Workstream 3: Push synthetic eval to 100/100

The path:

| Fix | Expected impact | Effort |
|---|---|---|
| Multi-line connection-string aggregation (Task #11) | +10-12 TPs | 4 hrs |
| AWS pairing logic (Task #12) | +6 TPs | 3 hrs |
| Multi-line PEM body validator (Task #13) | +4-5 TPs | 2 hrs |
| Tier system (Task #14) | Cleans display, no F1 change | 16 hrs |
| Plant fixtures for new detectors (Wave 6 = A+B+C) | +N TPs as new detectors prove | 4-6 hrs |
| File-type aware FP filter (test_secrets.py path) | -1 FP | 1 hr |

Math:
- Current: 916 TP, 4 FP, 38 FN, F1=97.76%
- After #11+#12+#13: ~920+20=940 TP, 4 FP, 14 FN → F1≈99.05%
- After file-type filter: 940 TP, 3 FP, 14 FN → F1≈99.10%

So 99% F1 is realistically achievable with Tasks #11+#12+#13 + the file-type filter.

To hit 99.5%+, need new detectors to be planted AND fire correctly (Wave 6).

## Workstream 4: Real-world eval (after 100/100 on synthetic)

Deferred per user direction. Plan documented in earlier message:
- Curated public repos (trufflesecurity/test_keys, leak-research papers, etc.)
- Per-tool finding diff
- Manual review → ground-truth labels
- Published as supplementary benchmark

## Execution order (precise sequencing)

```
SESSION 1 (today, ~4 hrs):
  Task #14  Verification tier system (4 hrs)        ← do FIRST so AI work shows tier
  Task #11  Multi-line connection-string (parallel to #14 — different file)
  Task #12  AWS pairing logic
  Task #13  Multi-line PEM body
  Re-run eval → measure new F1

SESSION 2 (~6 hrs):
  Task #15  Wave B modern vendors (30-50)
  Plant Wave B fixtures
  Re-run eval

SESSION 3 (~6 hrs):
  Task #16  Wave A long-tail TruffleHog (80-100)
  Task #17  Wave C structured detectors (top 8)
  Plant Wave A+C fixtures
  Re-run eval

SESSION 4 (final):
  Task #18  Eval iteration to 99%+ F1
  Document the journey
  Push public benchmark update

SESSION 5+ (later):
  Real-world eval harness
  Backend + frontend infra for tier display
```

## Risks + things that could go wrong

1. **Tier system in scanner alone isn't enough** — backend/frontend changes
   are 10+ hours each. If we ship tier in scanner JSON without UI support,
   users see raw output. Mitigation: ship scanner-side first; document the
   JSON schema; frontend follows.

2. **Wave B modern vendors lack public key formats** — some 2026 vendors
   don't publish their key shapes. Will need to inspect real keys (which
   we don't have) or skip. Mitigation: build the ones with documented
   shapes; flag unknown-format vendors for future.

3. **Multi-line aggregation could blow up FP rate** — broadening regex to
   span 5 lines may catch unrelated fields nearby. Mitigation: require
   ALL of host+user+password (or AT LEAST 2 of 3) within the window.

4. **AWS pairing could mis-pair** — if a file has multiple access keys
   and secrets, naive pairing matches wrong combos. Mitigation: only pair
   when exactly 1 access key + 1 secret are in the same 10-line window.

5. **F1 99% might not be achievable on this specific synthetic eval**
   because the eval itself has noisy plants (the planting agent made
   some mistakes). Mitigation: also audit the manifest for plant errors,
   not just scanner errors.

## Decision points needing user input

None right now. The plan is concrete enough to execute. Resume on Q later if:
- Backend/frontend tier UI build is needed sooner
- Real-world eval timing changes

---

**Starting now: Task #14 (tier system) — biggest unblock, gates the AI verify display.**
