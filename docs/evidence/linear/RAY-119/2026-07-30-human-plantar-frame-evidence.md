# RAY-119 — 真人足底动态数据的逐帧坏点证据累计

- Issue: `RAY-119` — 动态坏点掩码、修复与设备健康门控
- Milestone: `P1：可靠采集`
- Evaluated: 2026-07-30
- Implementation commit: `c650311` (`Accumulate dynamic bad-point frame evidence`)

## Acceptance interpretation

This verification follows the current P1 acceptance clarification: physical
force calibration files and a manual calibrated load are not prerequisites for
dynamic sensor-health evidence. The input is a real dynamic human-plantar
capture. The test is whether a location stays abnormally unresponsive while
its supported neighbours respond over time, not whether the observation can be
converted to a calibrated physical force.

The device-health store records only hardware evidence counts. It stores no raw
matrix, timestamped frame sequence, participant identity, contact pose, or
calibration value. A `source_index` remains inside the device-private mask only
because a later quality gate must know which sensor is affected.

## Implemented accumulation and correction boundary

For a candidate supported by dynamic neighbours, the next per-device mask
snapshot now accumulates:

- `positive_frame_observations`: frames where the candidate is low despite
  supported neighbours;
- `supported_frame_opportunities`: frames in which the required neighbour
  support existed;
- `confirmed_observations`: independent session observations.

The policy remains conservative: two independent corroborating sessions are
needed before an isolated point becomes `REPAIRABLE`; `SUSPECT` does not alter
the current session. A later session loads the frozen prior mask and can combine
that accumulated evidence with its current frames. Raw capture data is never
rewritten.

Board-edge candidates receive stricter support (all available orthogonal
neighbours must be loaded). If repeated edge evidence reaches `REPAIRABLE`, the
device is `HEALTH_UNAVAILABLE`; it is not sent to spatial interpolation, since
the repair algorithm has no symmetric neighbourhood at that edge.

Policy `dynamic-defect-mask/generic-grid/2` also suppresses a session that
contains more than eight simultaneously eligible cells. It records only the
raw-data-free audit event `SUSPECT_FLOOD_SUPPRESSED`; it does not persist those
locations as long-term evidence. The mask schema is now
`dynamic-defect-mask/3`; it reads the prior `/2` schema with zero historical
frame counters.

## Real-capture replay result

The local-only fourth window from the 2026-07-30 connected-device capture was
replayed through the observed 3,079-byte parser profile and the new policy in
an isolated `/private/tmp` data root. The validation identifier was explicitly
unbound and was not a production physical-device binding.

| Measure | Result |
| --- | --- |
| Decoded real frames | 1,240 |
| Frozen / updated mask version | v0 / v0 |
| Retained candidates | 0 |
| Suppressed broad candidates | 2,138 |
| `SUSPECT` / `REPAIRABLE` entries | 0 / 0 |
| Device health decision | `READY` |
| SQLite health audit | one `SUSPECT_FLOOD_SUPPRESSED`, candidate count 2,138 |
| Raw or participant data in audit | no |

This is the intended result for this capture: widespread changing human contact
does not become a permanent defect mask. It neither identifies a physical bad
point nor proves that the board has none. Evidence for a genuine isolated point
still requires repeated independent sessions; this replay contains no such
validated isolated pattern.

## Automated verification

```text
bash scripts/local-env.sh python -m pytest tests/hardware_standardization/test_dynamic_defect_mask.py tests/hardware_standardization/test_quality_gate.py tests/device tests/spool tests/hardware_standardization -q
```

Result: **151 passed in 1.36s**.

The dynamic-mask tests cover isolated interior promotion with 6/6 then 12/12
positive/support-frame counters, strict edge evidence followed by health
unavailability, broad-candidate suppression and redacted audit persistence.
Configured `pre-commit`, `mypy`, `uv lock --check` and `git diff --check` also
passed. The configured mypy target is the serial/parser contract only, not this
hardware-standardization module.

## Remaining boundary

The current result does not bind the validation identifier to a real production
device, demonstrate the product UI's selection/add/restore flow, or provide
multiple independent people/sessions with the same isolated point. Those are
the remaining RAY-119 acceptance items. RAY-119 therefore remains `In Review`.
