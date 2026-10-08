# RAY-277 Windows foundation release-baseline investigation

- Issue: `RAY-277`
- Title: 调查 Windows Foundation 发布基线 P95 性能预算失败
- Requirement revision: `R3`
- Delivery scope: `windows-p95-baseline-investigation`
- Status observed 2026-10-07: `In Progress`
- Detailed records (shared context): `.project-context/evidence/ray-277/windows-p95-baseline-investigation/`
  - `handoffs/2026-09-02T03-22-25Z.md` — diagnosis checkpoint
  - `acceptance/2026-10-07-windows-p95-measurement.md` and `acceptance/2026-10-07-windows-release-performance.json` — Windows measurement

This scope is an investigation. It changes no FeetForcePlate code or configuration; the code under test lives in the independent private library `RGu0/techflex-cloud-foundation`.

## Conclusion

The Windows failure was a **measurement artefact**, not a product performance regression.

- The failing job (foundation Actions run `32830557116`, commit `6be920c1`) actually reported `peak memory regressed by more than 10%`, not the P95 message quoted in the Issue.
- Cause: first-request HTTPX initialisation was counted in the `tracemalloc` peak. The foundation repository fixed this by warming both transports and resetting the peak before the measured workload (`4a67d483`), and by measuring 9 paired rounds of 1,000-operation averages (`6be920c1`).

## Acceptance snapshot (2026-10-07)

- [x] Windows P95 measurement, comparison baseline and environment recorded. Foundation run `37634399572` (`main`, head `78cf1549`, 2026-10-07): Windows / Python 3.11.9 / uv 0.12.23, 9 × 1,000 operations, P95 593.75 µs, peak 191,288 bytes, baseline workload `legacy-httpx-client/1` @ `6e76234f`. The gate passed on the first measurement. The baseline is re-measured inside the same job and its numeric values are not persisted, so this run records a pass but no ratio; the only recorded ratio is the 2026-09-02 Ubuntu artefact of run `32930906174` (P95 +1.17 %, peak −0.39 %).
- [x] Root cause attributed: measurement instability (see Conclusion).
- [x] No real regression to fix in this repository.
- [ ] Budget/baseline changes only after a confirmed Linear revision — **pending owner judgement.** After the original failure the foundation gate gained a single re-measure on failure (RAY-349, `9c982d6`, 2026-09-02) and a 100 µs absolute P95 floor (RAY-368 R2, `970512c`, 2026-09-03), so the P95 limit is now `baseline × 1.05 + 100 µs`. Both came through their own foundation-project revisions; the workload and the 5 % / 10 % relative budgets are unchanged.
- [x] `dev.ps1` behaviour and pytest-qt lifecycle logic (RAY-276) untouched.

## Related

- RAY-335 (techflex-cloud-foundation, Done 2026-09-03): persists the redacted Windows release-performance artefact used above.
- RAY-340: the macOS counterpart.
- `scripts/record_foundation_release_baseline.py` was removed from this repository on 2026-08-25 (`333c438`); the gate now runs only in the foundation repository.
