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
- [ ] Physical 30-minute rate/jitter/checksum/resync run.
- [x] Physical 10-minute empty-board sustained raw-link observation (partial evidence only; it does not substitute for the required 30-minute run).
- [ ] Calibration, units, bad pixels, drift, and device identity.
- [ ] Reproducible final hardware baseline report.

## Observed hardware result

All candidate frames use `FF AA 0C 07 01 … FA` and are 3079 bytes apart.
The field `0C07` equals 3079 only when read big-endian. This conflicts with the
manual-derived 6151-byte baseline and blocks promotion of the existing 6151-byte
parser to production.

| Capture | Scenario | Bytes | Candidate frames | Result |
|---|---:|---:|---:|---|
| `71b636…e8264c` | 20s empty board | 1,277,952 | 414 | startup prefix 1,767 bytes, then 3079-byte structure |
| `98d829…bad791` | 60s empty board | 3,825,664 | 1,242 | 20.7 Hz, 1,241 consecutive 3079-byte gaps |
| `143eaa…fb470` | 20s left load | 1,277,952 | 414 | candidate payload byte 846 rose by about 4.53 vs empty |
| `e4c04c…bbefd` | 20s right load | 1,277,952 | 413 | no byte averaged +1; one 5,980-byte non-contiguous gap |
| `826120…ac85e` | 20s right load, pressed | 1,277,952 | 415 | weak centre-line response, max about +0.64 |
| `6b84cc…53515` | 20s empty board after removal | 1,277,952 | 415 | low-amplitude state returned; max drift about +0.41 |
| `2c2022…ea8f63` | 10m empty board sustained link | 38,199,296 | 12,389 | 20.648 Hz; 12,372/12,388 adjacent candidate gaps were exactly 3,079 bytes; 16 were non-contiguous |

The 3072 bytes between function byte and CheckSum/tail candidate change under
left load. Treating it as a row-major 48x64 byte array is an observation-only
diagnostic: it is not a confirmed data encoding, sensor coordinate mapping, or
physical pressure unit. The asymmetric left/right response is a hardware-risk
observation requiring retest with a calibrated load and vendor clarification.

For the 60-second capture, direct two's-complement candidates over byte ranges
`0..3076` and `1..3076` matched only 785/1242 and 210/1242 frames respectively;
no tested starts `2..5` matched. CheckSum coverage therefore remains unknown.

## Sustained-link observation

The user requested the original 30-minute test be shortened to 10 minutes. The
completed raw capture duration is 600.0 seconds, with SHA-256
`2c2022170a226344b1c33fb5e004c4e9ddf1dd90c240831f3831bbaa9aea8f63`.
It contained 12,389 `FF AA … FA` structural candidates (20.648 Hz). Of 12,388
adjacent candidate gaps, 12,372 were exactly 3,079 bytes (99.871%); 16 gaps
were non-contiguous, with observed byte distances
`5872, 6010, 6102, 6106, 6112, 6114, 6130, 6140, 6144` (twice), `6146,
6148, 6151, 6152, 6154, 9177`.

These are structural continuity measurements only. Because the protocol profile
and checksum coverage are unverified and this raw recorder stores no per-frame
arrival timestamps, this result cannot quantify jitter, identify the loss side,
or satisfy the required 30-minute checksum/resynchronisation acceptance.

Verification command:

```sh
.venv/bin/python /private/tmp/feetforceplate_pyserial_capture.py \
  --port /dev/cu.usbserial-130 --seconds 600 --output-dir tmp/hardware
```

## Sensitive-data boundary

All listed captures used user-confirmed non-human test load or an empty board.
Raw files are retained only under ignored `tmp/hardware/` and are not committed
or uploaded. The reported SHA-256 values permit local re-identification without
placing raw pressure data in evidence.

## Next hardware steps

1. Repeat left/right/centre with a calibrated, known load and fixed coordinates.
2. Obtain vendor protocol clarification for 3079-byte frame format and CheckSum coverage.
3. Promote only a non-sensitive representative raw fixture after repeated checksum validation.
4. Run the required 30-minute capture after the verified profile exists; record rate, per-frame arrival jitter, invalid/resync counts, storage behaviour, and memory.

## Commit

Pending; this issue remains In Progress because fixture promotion, checksum, calibration, and 30-minute evidence are incomplete.
