# RAY-78 Evidence - DO-P4864 硬件与协议基线（P0 前置）

- Issue: RAY-78 — DO-P4864 硬件与协议基线（P0 前置）
- URL: https://linear.app/ray-app/issue/RAY-78/do-p4864-硬件与协议基线p0-前置
- Captured at: 2026-07-21T06:17:31Z
- Snapshot: In Progress; P0：硬件基线; Urgent
- Relations: blocks RAY-80 and RAY-81; related to RAY-82

## Acceptance snapshot

- [x] True serial port observed: CH340 `/dev/cu.usbserial-130`, VID:PID `1A86:7523`, 1,000,000 baud, 8N1.
- [x] Non-human empty-board and controlled left/right-load raw serial captures produced.
- [ ] Manual 6151-byte / 12-bit / about-12-Hz assertions are contradicted by this hardware capture and cannot remain a production parsing baseline.
- [ ] Physical golden fixture is captured but not promoted: CheckSum coverage and payload encoding are still unverified.
- [x] Physical 10-minute empty-board sustained raw-link observation.
- [x] Timestamped 10-minute host-receipt cadence observation. This is limited to structural candidates and host receipt time; it is not device timing or validated parser timing.
- [ ] In the 10-minute run, measure per-frame arrival jitter, checksum failures, and resynchronisation. The present raw recorder has no per-frame arrival timestamps and the CheckSum profile is unverified.
- [ ] Calibration, units, bad pixels, drift, and device identity.
- [ ] Reproducible final hardware baseline report.

## Observed hardware result

All candidate frames use `FF AA 0C 07 01 … FA` and are 3079 bytes apart.
The field `0C07` equals 3079 only when read big-endian. This conflicts with the
manual-derived 6151-byte baseline and blocks promotion of the existing 6151-byte
parser to production.

## User-provided protocol structure

The user supplied [a protocol-structure screenshot](user-provided-frame-structure-20260721.png)
(SHA-256 `97508e5d530bc04403348791dd45f97f5d1287ff31f624457a390e489d6de45d`).
It specifies the target legacy format as a 6,151-byte total frame:

| Offset | Size | Target value / interpretation |
|---:|---:|---|
| 0 | 2 | header `FF AA` |
| 2 | 2 | documented total length `0x1807` |
| 4 | 1 | function `01` |
| 5 | 6,144 | 3,072 row-major samples, `uint16` little-endian, 12-bit effective value |
| 6,149 | 1 | CheckSum |
| 6,150 | 1 | tail `FA` |

The documented CheckSum helper returns the two's complement of the byte sum
(`256 - (sum % 256)`). The user clarified that its `pBuf`/`len` arguments are
the content field only: in a matching 6,151-byte frame it covers exactly the
6,144 bytes `frame[5:6149]`, and compares the result with `frame[6149]`.

This confirms how a matching 6,151-byte capture must be decoded: reshape the
little-endian `uint16` payload in row-major order into `(48, 64)` and mask to
the documented 12-bit range. It does not validate the currently captured
stream: that stream contains recurring `FF AA 0C 07 01 … FA` structures at
3,079-byte intervals. Neither byte order for `0C 07` equals documented
`0x1807`, and the observed structure has only 3,072 bytes after the function
before CheckSum/tail. It therefore must not be converted into the documented
12-bit pressure array without a matching 6,151-byte golden fixture or vendor
confirmation of a separate compact-mode protocol.

Ignoring the length field entirely gives the same result. In the timestamped
10-minute raw file, 12,358 observed structures had `FA` at offset 3,078 and a
new `FF AA 0C 07 01` immediately at offset 3,079; zero observed headers had
`FA` at the 6,151-byte target-frame tail offset (6,150). Thus a new complete
frame starts within the supposed 6,144-byte content region of the documented
format. The actual content boundary is structurally 3,072 bytes after the
function byte, before a candidate CheckSum and `FA`. See
[`frame-boundary-analysis-20260721.json`](frame-boundary-analysis-20260721.json).

### CheckSum validation status

The correct target test is
`frame[6149] == (256 - (sum(frame[5:6149]) % 256)) % 256`. The observed
3,079-byte structure contains only 3,072 bytes after its function byte, so it
cannot supply the required 6,144-byte content field. Its candidate byte at
offset 3,077 is therefore not the documented protocol's `frame[6149]`, and no
valid CheckSum test of the documented rule can be performed on this capture.

For a strict negative layout check, the documented calculation was nevertheless
applied literally to every raw 6,151-byte window beginning at an observed
`FF AA`: `raw[i+6149] == -sum(raw[i+5:i+6149]) mod 256`. It matched 0 of
12,402 windows, and `raw[i+6150]` was `FA` in 0 of 12,402 windows. This does
not invalidate the documented algorithm; it confirms that none of the observed
windows is a frame of the documented 6,151-byte layout. See
[`checksum-analysis-20260721.json`](checksum-analysis-20260721.json).

### Provisional 3,079-byte compact-frame validation

Under the user-directed compact-frame hypothesis, the timestamped capture has
12,359 structurally consistent frames:
`FF AA | 0C 07 | 01 | 3,072 bytes | candidate CheckSum | FA`. Every candidate
has function byte `01` and tail `FA`. The 3,072-byte content field can be
reshaped row-major as a `(48, 64)` **raw uint8 byte grid**; in this empty-board
capture its bytes range from 0 to 2 (mean 0.006412). This verifies a structural
byte-grid mapping only, not 12-bit pressure encoding or calibrated units.

The documented two's-complement function was re-evaluated against this compact
hypothesis. Neither content-only coverage `frame[5:3077]` nor
function-plus-content coverage `frame[4:3077]` matches the candidate byte at
offset 3,077 in any of the 12,359 frames. The compact frame format therefore
has a stable boundary but an unverified CheckSum rule and payload encoding. See
[`compact-frame-validation-20260721.json`](compact-frame-validation-20260721.json).

### Observed compact hardware-interface mode

The client now exposes `ProtocolProfile.observed_compact_8bit(...)` for this
observed 3,079-byte structure. It deliberately does **not** treat the
contradictory `0C07` length field as an enforced wire-length assertion, and it
uses the candidate CheckSum in `OBSERVE` mode rather than as a hard frame-drop
filter. Each structurally complete candidate is decoded as the immutable,
row-major `uint8` grid `frame[5:3077].reshape(48, 64)`.

For traceability, every candidate CheckSum is counted and a mismatch produces
the quality flags `CHECKSUM_NOT_ENFORCED` and
`CHECKSUM_MISMATCH_OBSERVED`; the compact mapping also carries
`COMPACT_8BIT_PAYLOAD_UNVERIFIED` and `PROTOCOL_PROFILE_UNVERIFIED`. This
allows later forensic analysis without falsely claiming that CheckSum, payload
semantics, or calibrated pressure values are known.

An automated replay of the timestamped non-human raw capture through this
profile decoded 12,359 frames with monotonic `source_index` 0 through 12,358.
All 12,359 CheckSums were observed and mismatched under the currently tested
rule, while hard CheckSum failures remained zero; the structural parser
reported 59 resynchronisations. The replay is an interface audit, not a new
live-device capture or protocol verification. Machine-readable result:
[`compact-parser-replay-20260721.json`](compact-parser-replay-20260721.json).

| Capture | Scenario | Bytes | Candidate frames | Result |
|---|---:|---:|---:|---|
| `71b636…e8264c` | 20s empty board | 1,277,952 | 414 | startup prefix 1,767 bytes, then 3079-byte structure |
| `98d829…bad791` | 60s empty board | 3,825,664 | 1,242 | 20.7 Hz, 1,241 consecutive 3079-byte gaps |
| `143eaa…fb470` | 20s left load | 1,277,952 | 414 | candidate payload byte 846 rose by about 4.53 vs empty |
| `e4c04c…bbefd` | 20s right load | 1,277,952 | 413 | no byte averaged +1; one 5,980-byte non-contiguous gap |
| `826120…ac85e` | 20s right load, pressed | 1,277,952 | 415 | weak centre-line response, max about +0.64 |
| `6b84cc…53515` | 20s empty board after removal | 1,277,952 | 415 | low-amplitude state returned; max drift about +0.41 |
| `2c2022…ea8f63` | 10m empty board sustained link | 38,199,296 | 12,389 | 20.648 Hz; 12,372/12,388 adjacent candidate gaps were exactly 3,079 bytes; 16 were non-contiguous |
| `8858c4…75e14b` | 10m empty board, host-timestamped candidates | 38,187,663 | 12,359 | 20.598 Hz; raw scan found 12,317/12,358 consecutive 3,079-byte gaps; 41 were non-contiguous |

The 3072 bytes between function byte and CheckSum/tail candidate change under
left load. Treating it as a row-major 48x64 byte array is an observation-only
diagnostic: it is not a confirmed data encoding, sensor coordinate mapping, or
physical pressure unit. The asymmetric left/right response is a hardware-risk
observation requiring retest with a calibrated load and vendor clarification.

For the 60-second capture, direct two's-complement candidates over byte ranges
`0..3076` and `1..3076` matched only 785/1242 and 210/1242 frames respectively;
no tested starts `2..5` matched. CheckSum coverage therefore remains unknown.

## Sustained-link observation

The acceptance duration was changed from 30 minutes to 10 minutes at the user's
direction. The completed raw capture duration is 600.0 seconds, with SHA-256
`2c2022170a226344b1c33fb5e004c4e9ddf1dd90c240831f3831bbaa9aea8f63`.
It contained 12,389 `FF AA … FA` structural candidates (20.648 Hz). Of 12,388
adjacent candidate gaps, 12,372 were exactly 3,079 bytes (99.871%); 16 gaps
were non-contiguous, with observed byte distances
`5872, 6010, 6102, 6106, 6112, 6114, 6130, 6140, 6144` (twice), `6146,
6148, 6151, 6152, 6154, 9177`.

These are structural continuity measurements only. Because the protocol profile
and checksum coverage are unverified and this raw recorder stores no per-frame
arrival timestamps, this result cannot quantify jitter, identify the loss side,
or satisfy the remaining 10-minute checksum/resynchronisation acceptance.

Verification command:

```sh
.venv/bin/python /private/tmp/feetforceplate_pyserial_capture.py \
  --port /dev/cu.usbserial-130 --seconds 600 --output-dir tmp/hardware
```

### Timestamped candidate-cadence observation

A second 600.001645-second empty-board capture used a 1 ms host polling bound
to assign host receipt timestamps to each structural `FF AA … FA` candidate.
The raw file SHA-256 is
`8858c434f34a9939034271a6d0b083e135aee5a89e2f0973306737c48c75e14b`.
It produced 12,359 candidates (20.5983 Hz). Host receipt intervals had p50
48.380417 ms, p95 48.639500 ms, p99 49.970625 ms, mean 48.543244 ms, and
maximum 219.956833 ms. The 48 microsecond minimum is an artefact of multiple
candidates being handled in one read batch, not a device-frame interval.

An independent raw-byte scan found 12,317 contiguous 3,079-byte intervals out
of 12,358 (99.668%) and 41 non-contiguous intervals. The recorder reported 88
structural realignments and 133,054 discarded bytes; neither count is a
validated protocol-parser resynchronisation count because the CheckSum profile
is unknown. Full machine-readable results are in
[`timed-capture-20260721.json`](timed-capture-20260721.json).

## Sensitive-data boundary

All listed captures used user-confirmed non-human test load or an empty board.
Raw files are retained only under ignored `tmp/hardware/` and are not committed
or uploaded. The reported SHA-256 values permit local re-identification without
placing raw pressure data in evidence.

The local file `tmp/hardware/dop4864-timed-20260721T064602Z-provisional-48x64.npz`
is a provisional `uint8` byte-grid export from the incompatible 3,079-byte
stream. It is retained for forensic comparison only and must not be used as
decoded or calibrated pressure data.

## Next hardware steps

1. Repeat left/right/centre with a calibrated, known load and fixed coordinates.
2. Obtain vendor confirmation of the `0C 07` / 3,079-byte stream or the command/mode needed to emit the documented 6,151-byte format.
3. Capture a non-sensitive 6,151-byte golden fixture and prove the CheckSum helper's caller coverage range.
4. Promote only a matching representative raw fixture after repeated checksum validation.
5. With a verified profile, complete the 10-minute validated-parser metric pass: per-frame arrival jitter, CheckSum failures, invalid/resync counts, storage behaviour, and memory.

## Commit

`779b08e` — hardware baseline evidence and non-human 10-minute sustained-link
measurement.
`75182e9` — changed the issue-local capture-duration requirement from 30 minutes
to 10 minutes, preserving the remaining metric requirements. This issue remains
In Progress because fixture promotion, checksum, per-frame
jitter/resynchronisation metrics, and calibration are incomplete.
