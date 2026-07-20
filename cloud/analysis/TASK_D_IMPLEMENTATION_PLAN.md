# Task D Cloud Analysis, Reporting, and Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the P4-P5 cloud analysis, immutable complete-report, PDF-artifact, and operations core without changing ingestion, device parsing, or the client workflow.

**Architecture:** `cloud.analysis` consumes the approved `session.ingested.v1` boundary through typed ports, rebuilds deterministic versioned features, gates every algorithm by session validity, sampling rate, calibration, duration, and algorithm validation, then persists an idempotent `AnalysisRun`. `cloud.reporting` maps only approved supported results into a public-safe `ReportDocument`, appends an immutable `CLOUD_COMPLETE` version under the session's existing `report_id`, and stores a hashed PDF artifact. `cloud.observability` receives safe structured events, evaluates deduplicated alerts, and builds a privacy-filtered diagnostic archive through an encryption port.

**Tech Stack:** Python 3.11+ standard library (`dataclasses`, `decimal`, `hashlib`, `json`, `zipfile`, `unittest`) plus PostgreSQL DDL. No new repository-wide dependencies or shared configuration files.

## Linear Execution Order

Only one issue moves to `In Progress` at a time. Each issue ships its own `docs/evidence/linear/<ISSUE-ID>/README.md` and remains `In Review` whenever external validation is still missing.

1. `RAY-93` — metric descriptors and capability gates; foundation for all downstream publication.
2. `RAY-102` — complete-session analysis pipeline, versioned features, idempotent runs, and recomputation.
3. `RAY-95` — shared report identity, immutable `CLOUD_COMPLETE` versions, and PDF artifacts.
4. `RAY-94` — approved professional metrics and curves in the same report.
5. `RAY-103` — structured failure telemetry, SLI/alerts, and support diagnostics across the implemented flow.

## Global Constraints

- Baseline commit is `c0e4f38`.
- Hardware truth is 48x64 DO-P4864 at 1 Mbps and approximately 12 Hz.
- The product provides health screening and risk prompts, not disease diagnosis.
- Cloud analysis consumes only complete sessions from `session.ingested.v1`.
- Every metric is gated by session validity, actual sampling rate, calibration, duration, test protocol, and algorithm validation state.
- Internal quality, capability reasons, debug data, stack traces, and raw pressure data never enter customer report documents or PDF artifacts.
- A local basic report and cloud complete report share one `report_id`; all report versions and artifacts are immutable.
- Retries and recomputation are idempotent for identical input and version tuples; a new version creates a new run and report version.
- This task may modify only `cloud/analysis`, `cloud/reporting`, `cloud/observability`, their migrations, and related tests.
- Automated tests do not constitute real PostgreSQL/S3/queue deployment, hardware, PDF visual, or printer validation.

---

### Task 1: Versioned feature pipeline and capability gates

**Files:**
- Create: `cloud/analysis/models.py`
- Create: `cloud/analysis/features.py`
- Create: `cloud/analysis/gates.py`
- Test: `tests/cloud/analysis/test_features.py`
- Test: `tests/cloud/analysis/test_gates.py`

**Interfaces:**
- Consumes: `RawSession`, `SessionContext`, `AlgorithmDescriptor`.
- Produces: `FeatureSet`, `CapabilityDecision`, and `MetricResult` types used by the orchestrator and report builder.

- [ ] Write tests proving feature cache keys include manifest, pipeline, calibration, and parameter digests; extraction is deterministic for 48x64 frames.
- [ ] Run `python3 -m unittest tests.cloud.analysis.test_features -v`; expect failure because analysis modules do not exist.
- [ ] Implement immutable analysis value types and a deterministic first-level feature pipeline for total load, left/right and anterior/posterior load, contact area, COP sequence, and duration.
- [ ] Re-run the feature tests; expect all pass.
- [ ] Write table-driven tests for invalid session, low sampling rate, insufficient calibration, short duration, wrong protocol, unapproved algorithm, and a fully supported case.
- [ ] Run `python3 -m unittest tests.cloud.analysis.test_gates -v`; expect failure because gate behavior is missing.
- [ ] Implement gate evaluation that returns safe public status plus internal reason codes without calculating unsupported metrics.
- [ ] Re-run feature and gate tests; expect all pass.

### Task 2: Idempotent and recomputable AnalysisRun orchestration

**Files:**
- Create: `cloud/analysis/ports.py`
- Create: `cloud/analysis/orchestrator.py`
- Test: `tests/cloud/analysis/test_orchestrator.py`

**Interfaces:**
- Consumes: `SessionIngestedEvent`, `RawSessionLoader`, `AnalysisRepository`, `FeatureStore`, `TelemetrySink`.
- Produces: persisted `AnalysisRun`; emits `analysis.started.v1`, `analysis.completed.v1`, or `analysis.failed.v1` after persistence.

- [ ] Write tests proving duplicate delivery returns the same run, version changes create a new run, unsupported inputs create `UNSUPPORTED`, failures persist safe `E-ALG-*` evidence, and identity fields are not accepted by the runtime contract.
- [ ] Run `python3 -m unittest tests.cloud.analysis.test_orchestrator -v`; expect failure because the orchestrator is absent.
- [ ] Implement an in-memory reference repository with the same unique run key as the approved database design and an orchestrator that finalizes results before emitting completion.
- [ ] Re-run all analysis tests; expect all pass.

### Task 3: Immutable CLOUD_COMPLETE report and PDF artifact

**Files:**
- Create: `cloud/reporting/models.py`
- Create: `cloud/reporting/builder.py`
- Create: `cloud/reporting/pdf.py`
- Create: `cloud/reporting/service.py`
- Test: `tests/cloud/reporting/test_reporting.py`

**Interfaces:**
- Consumes: successful `AnalysisRun`, report identity resolver/repository, artifact store, approved metric catalog.
- Produces: immutable `ReportVersion(kind=CLOUD_COMPLETE)` and `ReportArtifact(application/pdf)` under the existing `report_id`.

- [ ] Write tests proving a seeded BASIC version and cloud version share `report_id`, duplicate completion is idempotent, recomputation appends a version, invalid/unsupported runs publish nothing, only supported approved metrics appear, forbidden internal fields cannot enter the document, and the artifact starts with `%PDF-` and matches its SHA-256.
- [ ] Run `python3 -m unittest tests.cloud.reporting.test_reporting -v`; expect failure because reporting modules do not exist.
- [ ] Implement the strict public report schema, allowlisted mapper, atomic in-memory reference repository, deterministic PDF renderer, and artifact storage port.
- [ ] Re-run reporting and analysis tests; expect all pass.

### Task 4: Safe telemetry, monitoring alerts, and diagnostics

**Files:**
- Create: `cloud/observability/events.py`
- Create: `cloud/observability/alerts.py`
- Create: `cloud/observability/diagnostics.py`
- Test: `tests/cloud/observability/test_events.py`
- Test: `tests/cloud/observability/test_alerts.py`
- Test: `tests/cloud/observability/test_diagnostics.py`

**Interfaces:**
- Consumes: structured component events, numeric metric samples, safe system summaries, `EnvelopeEncryptor`.
- Produces: scrubbed telemetry events, deduplicated `AlertIncident` records with severity/runbook, and encrypted diagnostic artifacts with plaintext/ciphertext hashes.

- [ ] Write failing tests for strict safe-context keys, recursive secret/identity rejection, failure-event helpers, threshold windows, cooldown deduplication, recovery, diagnostic allowlists, archive determinism, and exclusion of raw session/report content.
- [ ] Run `python3 -m unittest tests.cloud.observability.test_events tests.cloud.observability.test_alerts tests.cloud.observability.test_diagnostics -v`; expect failure because modules do not exist.
- [ ] Implement the minimal telemetry, alert, and diagnostic components; require encryption through a port rather than inventing cryptography.
- [ ] Re-run all observability tests; expect all pass.

### Task 5: PostgreSQL migrations and contract checks

**Files:**
- Create: `cloud/analysis/migrations/0001_analysis.sql`
- Create: `cloud/reporting/migrations/0001_reporting.sql`
- Create: `cloud/observability/migrations/0001_ops.sql`
- Test: `tests/cloud/test_migrations.py`

**Interfaces:**
- Produces: `analysis`, `reporting`, and Task-D-owned `ops` tables, constraints, indexes, RLS policies, immutable-row triggers, and transactional outbox references matching the approved schema.

- [ ] Write failing contract tests for required schemas, tenant-first unique constraints, AnalysisRun idempotency tuple, metric value exclusivity, one report per tenant/session, immutable version/artifact rows, alert dedupe keys, diagnostic hashes, and RLS enablement.
- [ ] Run `python3 -m unittest tests.cloud.test_migrations -v`; expect failure because migrations are absent.
- [ ] Add forward-only idempotent migration files without touching ingestion/session tables.
- [ ] Re-run migration and full tests; expect all pass.

### Task 6: Verification and scoped commit

**Files:**
- Verify only Task D paths from the global constraint list.

- [x] Run the four scoped entrypoints below; expect 62 tests and zero failures. Root-level discovery is not evidence because the baseline has no root discovery package/harness and reports 0 tests.
  - `python3 -m unittest discover -s tests/cloud/analysis -v`
  - `python3 -m unittest discover -s tests/cloud/reporting -v`
  - `python3 -m unittest discover -s tests/cloud/observability -v`
  - `python3 -m unittest tests.cloud.test_migrations -v`
- [ ] Run `python3 -m compileall -q cloud tests`; expect exit code 0.
- [ ] Run `rg -n "name|phone|external_id|raw_frame|stack_trace|token|password" cloud/reporting cloud/observability`; inspect every match and confirm it is an explicit rejection/allowlist rule or harmless test fixture.
- [ ] Run `git diff --check`; expect no whitespace errors.
- [ ] Run `git status --short` and confirm only Task D files are present.
- [ ] Commit only Task D files with a focused message.
- [ ] Report automated evidence separately from unperformed PostgreSQL/S3/queue integration, hardware validation, PDF visual regression, and physical printer checks.
