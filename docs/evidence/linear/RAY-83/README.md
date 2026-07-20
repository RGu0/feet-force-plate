# RAY-83 Evidence - 数据处理管线：48×64@约12Hz、标定与显示解耦

- Issue: RAY-83 — 数据处理管线：48×64@约12Hz、标定与显示解耦
- URL: https://linear.app/ray-app/issue/RAY-83/数据处理管线4864约12hz标定与显示解耦
- Captured at: 2026-07-20T10:18:44Z
- Snapshot: In Progress; milestone P1：可靠采集; priority High
- Relations: none recorded in Linear

## Acceptance snapshot

- [x] Fixed-slot bounded storage buffer applies backpressure or an explicit `Full` error; it never evicts an accepted raw frame.
- [x] Raw frames remain immutable 48×64 `uint16` counts; a display projection is a separate read-only array.
- [x] Physical output units require a calibration version, fixture SHA-256, and explicit transform. Current profile remains `raw_count` only.
- [x] Algorithm/filter/bad-point/interpolation versions and immutable parameter content contribute to the processing identity.
- [x] Storage path has zero silent-drop semantics; latest-display mailbox may replace stale display-only frames and audits replacements.
- [x] Display refresh cadence is configured independently from the nominal 12 Hz input cadence.
- [x] Serializable session manifest contains data, device, protocol, calibration, algorithm, filter, bad-point, interpolation, test-protocol, and acquisition-mode versions.
- [x] Automatic synthetic benchmark covers a deliberately slow storage consumer, stalled display consumer, and parallel upload-like read/hash workload.
- [ ] Real disk, concurrent sealed-segment upload, physical 1 Mbps acquisition, and human UI-stall performance remain unverified.

## Implementation and key decisions

- `client/device/pipeline.py`
  - Adds a preallocated ring buffer with blocking backpressure, explicit timeout failure, FIFO ordering, and bounded counters.
  - Defines raw-only processing profiles, parameter identity SHA-256, separate display projections, session-version manifest serialization, and an independent display cadence.
  - Does not implement an unapproved filter, bad-point repair, interpolation algorithm, calibration curve, or physical unit conversion.
- `client/device/acquisition.py`
  - Adds `publish_count` and `replacement_count` to the single-slot latest-frame mailbox without changing storage ordering.
- `client/device/pipeline_benchmark.py`
  - Provides a short repeatable synthetic stress runner. It uses a slow in-memory consumer and a parallel read/hash workload; this is not a real disk or cloud-upload benchmark.
- `tests/device/test_pipeline.py`, `tests/device/test_pipeline_benchmark.py`
  - Cover fixed capacity, explicit full behavior, zero silent-drop metric, display replacement audit, calibration gate, raw immutability, parameter identity, version round trip, cadence separation, and stress invariants.

The DO-P4864 CheckSum coverage, length-field byte order, physical calibration, and real filter parameters remain external evidence gates. No value is guessed here.

## Verification

Detailed command output: [verification.txt](verification.txt)

Machine-readable benchmark: [benchmark.json](benchmark.json)

| Command | Result |
|---|---|
| bundled Python `-m unittest tests.device.test_pipeline tests.device.test_pipeline_benchmark` | PASS — 8 tests (0.047s) |
| bundled Python `-m unittest discover -s tests -p 'test_*.py'` | PASS — 38 owned tests (0.047s) |
| bundled Python `-m compileall -q client/device tests/device` | PASS — exit 0 |
| bundled Python `-m client.device.pipeline_benchmark --frames 120 --capacity 4 --storage-delay 0.001` | PASS — 120/120 ordered storage frames, 0 silent drops, 116 producer waits, 119 display replacements |

## Automatic / physical / manual boundary

- Automated: the unit/integration tests and benchmark use synthetic `RawFrame` objects, an in-memory fixed-slot buffer, a sleeping consumer, a stalled latest-frame reader, and a local hash thread.
- Physical not run: no DO-P4864/CH340 fixture, USB stream, real disk pressure, device timing, or cable-removal test was run.
- Upload not run: no cloud API is implemented or invoked. The parallel reader only approximates local contention from an uploader reading immutable data.
- Manual/UI not run: UI is outside this task's ownership. The cadence contract is tested, but no rendered interface or operator workflow was assessed.
- Persistence integration pending: RAY-87/RAY-89 must store the session-version manifest with encrypted segment/SQLite state.

## Failures and limits

- `elapsed_seconds` and parallel-reader iteration count are host-dependent observations, not acceptance thresholds.
- A full storage buffer never silently drops, but an explicit timeout failure still requires the acquisition coordinator to mark the session incomplete; RAY-80 covers that storage-handoff failure path.
- Algorithm version fields describe provenance contracts only; approved processing algorithms and calibration artifacts do not yet exist in this repository slice.

## Commit

Implementation/tests/benchmark/evidence commit:
`83b0357cbee8d3c339fdd19f7003785ec87477bb`.
