# RAY-113 Evidence

- Issue: `RAY-113` 5 秒空载数据采集与传感器基线校验
- Linear: https://linear.app/ray-app/issue/RAY-113/5-秒空载数据采集与传感器基线校验
- Design: `docs/superpowers/specs/2026-07-21-startup-device-validation-design.md` (`7c089a9`)
- Implementation plan: `docs/superpowers/plans/2026-07-21-startup-device-validation.md`
- Start status: `Todo`; implementation start was written to Linear and re-read as `In Progress` at 2026-07-22T02:47:59Z.

## Issue snapshot and dependency decision

The machine-readable snapshot is [`issue-snapshot.json`](issue-snapshot.json). RAY-113 is implemented before RAY-114 and RAY-115. The runtime contract follows the later communication/module-02/RAY-78 evidence: 3,079-byte `observed_compact_8bit`, immutable 48×64 column-major `uint8`, host monotonic timestamps, and CheckSum observation only. The older 6,151-byte/12 Hz architecture text is not used as the runtime contract.

## Implementation

- `client/startup_validation/models.py`: versioned `DeviceValidationRun`, PASS / RETRYABLE_FAIL / SERVICE_REQUIRED outcomes, stable reason codes, auditable receive statistics, and a safe summary without frame arrays.
- `client/startup_validation/rules.py`: versioned raw-count-only unloaded, receive-rate/gap, fixed-value, saturation, no-variation, local anomaly, temporal noise, and drift rules. No physical unit or calibration coefficient is produced.
- `client/startup_validation/service.py`: reads only through `ByteTransport`, feeds only `DaoOneP4864Parser`, waits for the first structurally valid unloaded `RawFrame`, then collects until `host_monotonic_ns - start >= 5_000_000_000`. The number of frames is observed, never prescribed.
- Every service instance is one run. A retry receives a new transport, parser, run ID, timer, and frame list; previous partial frames cannot be stitched into the next result.
- Load, disconnect, no-data, or host-gap interruption returns a retryable failure and marks the partial window discarded.

Versions used by the first implementation:

- run schema: `device-validation-run/1`
- rules: `startup-baseline/1`
- thresholds: `startup-baseline-thresholds/1`
- data mode: `48x64-uint8-column-major/1`
- unit label: `raw_count` only

The numeric thresholds are implementation inputs requiring real-device validation. They are intentionally absent from customer UI and safe telemetry summaries.

## TDD evidence

RED 1:

```text
./scripts/local-env.sh python -m pytest tests/startup_validation/test_models_and_rules.py -q
ModuleNotFoundError: No module named 'client.startup_validation'
```

GREEN 1 (2026-07-21 America/Los_Angeles):

```text
.......                                                                  [100%]
7 passed in 0.14s
```

RED 2:

```text
./scripts/local-env.sh python -m pytest tests/startup_validation/test_validation_service.py -q
ModuleNotFoundError: No module named 'client.startup_validation.service'
```

GREEN 2:

```text
............                                                             [100%]
12 passed in 0.18s
```

Production-chain regression:

```text
./scripts/local-env.sh python -m pytest \
  tests/device/test_protocol.py tests/device/test_simulator.py \
  tests/device/test_acquisition.py -q
............................                                             [100%]
28 passed in 0.16s
```

Covered automatically: normal unloaded pass, exact monotonic duration, frame-count independence, obvious load, partial-window discard, disconnect, empty-read stream stall, fresh retry, low rate, large gap, fixed values, saturation, persistent local fault, noise, drift, shape/dtype failure, parser and acquisition regressions.

## Verification boundary

Automated/synthetic evidence is complete for the implementation slice above. It does **not** establish:

- repeated cold starts with a physical DO-P4864 and CH340;
- load application/removal and cable unplug/reconnect on real hardware;
- that the current raw-count thresholds are suitable across devices, temperatures, aging, and sites;
- CheckSum coverage, raw-value physical meaning, pressure/force units, calibration coefficients, long-term drift, or bad-point acceptance;
- Windows serial driver timing, target-machine scheduling, high DPI, keyboard, or operator usability;
- production telemetry upload/backend diagnosis.

Therefore RAY-113 may move only to `In Review`, never `Done`, after commit SHA and final commands are backfilled.

## Commits

- Implementation, tests, plan, and initial evidence: `0fd1b4d`.
- Evidence SHA follow-up: this README-only follow-up commit.

## 2026-07-26 发布阻断复核

- 映射：机构编号查询索引由普通 SHA-256 改为受控 HMAC-SHA-256，索引输入包含 `tenant_id + issuer + id_type + normalized external_id`；SQLite 仅保存 HMAC，不保存可枚举的摘要。
- 实现：`client/app/local_store.py`；`client/tests/test_local_replay_store.py`。旧 replay 表会迁移；仅在可解密旧 payload 时使用明确的 `legacy-local / institution_record` 上下文重新索引，不能解密的旧记录保留但不可查找，避免猜测上下文导致误关联。
- 验证：上下文隔离、HMAC 非普通 SHA-256 断言已覆盖；全量 `336 passed in 28.03s`。
- 限制：本地 replay 密钥使用 OS credential vault；机构正式的 License 下发查询密钥和服务端 RLS 仍未接入。RAY-113 保持 In Review。
- Commit SHA：尚未创建；本轮未暂存。
