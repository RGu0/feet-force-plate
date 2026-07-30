# RAY-80 Evidence - 设备接入与可靠采集

- Issue: RAY-80 — 设备接入与可靠采集
- URL: https://linear.app/ray-app/issue/RAY-80/设备接入与可靠采集
- Original Linear snapshot: 2026-07-20T10:12:10Z — In Review; milestone P1：可靠采集; priority High
- Local acceptance updated: 2026-07-30T03:44:02Z — PASS; Linear status was not changed from this workspace.
- Relations: blocked by RAY-78

## Acceptance snapshot

- [x] CH340 enumeration and conservative availability probing are covered with injected port/serial fakes.
- [x] Physical CH340 enumeration: current CH340 `1A86:7523` was found at `/dev/cu.usbserial-1140` and was available after the probe.
- [x] Physical occupied-port behavior: while a separate exclusive owner held that port, discovery returned `BUSY_OR_UNAVAILABLE` with a `SerialException`; after owner release, it returned `AVAILABLE`.
- [x] Physical unplug and reconnect behavior: the real cable-removal run invalidated and discarded the active session; a later real reconnect started a fresh window at `source_index=0` (linked evidence below).
- [x] Serial adapter configures 1,000,000 baud, 8N1, blocking reads with timeout, and runs through an independent worker thread.
- [x] Connection state machine implements `DISCONNECTED / CONNECTING / READY / ACQUIRING / ERROR` with guarded transitions.
- [x] Parser-provided host monotonic time, wall time, and `source_index` survive the acquisition handoff.
- [x] Bounded durable-storage FIFO and single-slot latest-frame mailbox are separate; durable handoff always precedes latest publication.
- [x] Transport disconnect and storage-handoff failure return `INCOMPLETE`.
- [x] Reconnect stops at `READY`; a failed acquisition runner is single-use so pre/post-disconnect data cannot be stitched into one formal session.
- [x] Hardware serial and simulator implement the same `ByteTransport` contract.

## Implementation and key decisions

- `client/device/acquisition.py`
  - Defines the guarded connection lifecycle, one-shot blocking acquisition runner, and thread worker.
  - Uses a bounded FIFO for storage backpressure. A frame is sent to the latest mailbox only after the durable sink accepts it; there is no silent storage-path drop.
  - Makes runners single-use. Reconnect changes only connection state; a caller must create a new parser/runner and session boundary.
- `client/device/serial_transport.py`
  - Discovers CH340/CH341 by WCH VID `0x1A86` or explicit CH340/CH341 identity text.
  - Uses 1,000,000 baud, 8 data bits, no parity, one stop bit, a finite read timeout, and POSIX-exclusive opens. This prevents a concurrently owned POSIX TTY from being incorrectly reported as available; Windows retains its OS-level COM-port exclusivity.
  - Reports a failed probe as `BUSY_OR_UNAVAILABLE`; without OS/hardware evidence it does not claim that every open failure specifically means occupancy.
  - Imports pyserial lazily so simulator and automated tests remain usable without a physical-device dependency installed.
- `tests/device/test_acquisition.py`, `tests/device/test_serial_transport.py`
  - Cover storage-before-latest ordering, audit fields, disconnect, storage failure, reconnect isolation, independent thread execution, discovery/probing, 8N1 configuration, and error mapping.

The on-wire length byte order and CheckSum coverage are not selected here. Production parsing remains gated on the physical fixture required by RAY-78/RAY-81.

## Verification

Detailed output: [verification.txt](verification.txt)

| Command | Result |
|---|---|
| `./scripts/local-env.sh python -m pytest tests/device/test_serial_transport.py tests/device/test_acquisition.py tests/device/test_session_runtime.py -q` | PASS — 22 tests |
| `./scripts/local-env.sh python -m pytest tests/device tests/spool tests/hardware_standardization -q` | PASS — 148 tests (1.31s) |
| `git diff --check` | PASS |

## Automatic / physical / manual boundary

- Automated: the listed tests use byte-level simulators or injected fakes and verify lifecycle, ordering, POSIX exclusivity and cleanup semantics.
- Physical: `physical-port-acceptance-20260730.json` records today's CH340 enumeration, occupied-port rejection and post-release availability. The 10-minute 1 Mbps production-composition run is documented in [`../RAY-86/real-device-runtime-continuity-10m-20260723.json`](../RAY-86/real-device-runtime-continuity-10m-20260723.json). Actual cable removal is documented in [`../RAY-86/cable-removal-runtime-20260728.json`](../RAY-86/cable-removal-runtime-20260728.json); the real reconnect and fresh-session boundary are documented in [`../RAY-113/2026-07-28-live-acceptance.md`](../RAY-113/2026-07-28-live-acceptance.md).
- Manual: no operator-facing UI acceptance was claimed; it is outside RAY-80 ownership.
- RAY-78's protocol-profile/vendor confirmation remains independently open. It does not weaken this item’s transport connection, ownership, session-boundary, storage-ordering or physical-disconnect acceptance.

## Failures and limits

- A probe failure is intentionally grouped as busy or unavailable because permission, driver, disappearance, and genuine occupancy can produce similar open errors.
- The storage FIFO is an acquisition boundary, not the encrypted disk spool; durable segment writes and crash recovery belong to RAY-87/RAY-89.
- Broader `client/tests` remain outside this evidence because concurrent RAY-101/RAY-92 files currently require unavailable PySide6/shared symbols; no files in those task-owned directories were modified.

## Commit

Prior implementation/tests commit: `c470478455349fc6afb2d1e13a96f106ade3080e`.

The current local acceptance adds the POSIX-exclusive port ownership fix, its
regression coverage and the physical-port evidence.

## 2026-07-23 redesign implementation update

The current accepted software path is `ByteTransport → incremental parser → encrypted
temporary session → whole-session quality gate → formal valid-session storage`.
`client/device/acquisition.py` now has an explicit `INVALID` state/outcome and discards
temporary capture data on transport disconnect, storage failure, parser integrity
failure/resynchronization, or a configured host-arrival gap. `client/device/session_runtime.py`
is the composition root: it connects the parser, durable staging sink, independent latest-frame
mailbox and whole-session gate, without importing UI, network upload, reports or product
algorithms.

Automated verification on 2026-07-23:

- `./scripts/local-env.sh python -m pytest tests/device tests/spool tests/hardware_standardization -q` — **98 passed**.
- `git diff --check` — passed.

This remains an automated result. Physical CH340 enumeration, target-machine 1 Mbps sustained
read, cable removal, actual disk-full/power-loss behavior and a real baseline/quality run remain
required before this issue can be marked Done.
