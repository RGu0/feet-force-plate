# RAY-80 Evidence - 设备接入与可靠采集

- Issue: RAY-80 — 设备接入与可靠采集
- URL: https://linear.app/ray-app/issue/RAY-80/设备接入与可靠采集
- Captured at: 2026-07-20T10:07:22Z
- Snapshot: In Progress; milestone P1：可靠采集; priority High
- Relations: blocked by RAY-78

## Acceptance snapshot

- [x] CH340 enumeration and conservative availability probing are covered with injected port/serial fakes.
- [ ] Physical CH340 enumeration, true occupied-port behavior, and unplug behavior need hardware verification.
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
  - Uses 1,000,000 baud, 8 data bits, no parity, one stop bit, and a finite read timeout.
  - Reports a failed probe as `BUSY_OR_UNAVAILABLE`; without OS/hardware evidence it does not claim that every open failure specifically means occupancy.
  - Imports pyserial lazily so simulator and automated tests remain usable without a physical-device dependency installed.
- `tests/device/test_acquisition.py`, `tests/device/test_serial_transport.py`
  - Cover storage-before-latest ordering, audit fields, disconnect, storage failure, reconnect isolation, independent thread execution, discovery/probing, 8N1 configuration, and error mapping.

The on-wire length byte order and CheckSum coverage are not selected here. Production parsing remains gated on the physical fixture required by RAY-78/RAY-81.

## Verification

Detailed output: [verification.txt](verification.txt)

| Command | Result |
|---|---|
| bundled Python `-m unittest tests.device.test_acquisition tests.device.test_serial_transport` | PASS — 11 tests |
| bundled Python `-m unittest discover -s tests -p 'test_*.py'` | PASS — 30 owned tests (0.029s) |
| bundled Python `-m compileall -q client/device tests/device` | PASS — exit 0 |

## Automatic / physical / manual boundary

- Automated: all results above used the byte-level simulator or injected fake serial/port providers. They prove host lifecycle and ordering semantics, not physical USB behavior.
- Physical not run: no DO-P4864/CH340 hardware was available in this task. Port enumeration, busy-port diagnosis, sustained 1 Mbps reads, cable removal, driver differences, and reconnect must be verified on the target machine.
- Manual not run: operator-facing prompts and workflow behavior are outside this directory ownership and were not changed.
- External blocker: RAY-78 must provide a redacted raw serial fixture before the physical protocol profile can be accepted.

## Failures and limits

- A probe failure is intentionally grouped as busy or unavailable because permission, driver, disappearance, and genuine occupancy can produce similar open errors.
- The storage FIFO is an acquisition boundary, not the encrypted disk spool; durable segment writes and crash recovery belong to RAY-87/RAY-89.
- Broader `client/tests` remain outside this evidence because concurrent RAY-101/RAY-92 files currently require unavailable PySide6/shared symbols; no files in those task-owned directories were modified.

## Commit

Implementation/evidence commit: `c5cf0e0eca95671f4a839ee6336efef3162b3dd5`.

Concurrency note: the shared Git index was changed between this task's explicit
RAY-80 staging check and its commit command. A concurrent RAY-91 metadata commit
captured the six staged RAY-80 paths along with one RAY-91 evidence update. The
RAY-80 path set is complete and verified above, but the implementation commit is
not issue-isolated. History was not rewritten because that would modify another
task's completed commit.
