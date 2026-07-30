# RAY-88 Evidence — 内部回放与故障复现工具

- Issue: RAY-88 — 内部回放与故障复现工具
- URL: https://linear.app/ray-app/issue/RAY-88/内部回放与故障复现工具
- Captured at: 2026-07-29
- Snapshot: In Progress; P1：可靠采集; High

## Acceptance snapshot

- [x] 从已提交的加密不可变 raw segments 与 `manifest.json` 读取。
- [x] 输出实时采集同一 `RawFrame` 契约；不构造算法结果或改写持久化数据。
- [x] 在回放前验证 manifest 摘要、分段身份/密文摘要、版本快照、帧数、source_index 和主机单调时间轴。
- [x] 支持逐帧、按 source index 跳转、闭区间、循环与变速时间换算。
- [x] 从加密派生观测读取通信质量事件计数和重建计数，供内部热力图/COP/曲线消费者关联；本模块不实现客户 UI。
- [x] 可在确定帧边界重现断线、校验错误、缺段和算法失败；不会伪造 raw frame。
- [x] 诊断摘要默认仅含版本、摘要、计数和时间范围，不含矩阵、密钥或受试者数据。
- [x] 客户 UI 和报告未接入该模块。

## Implementation and decisions

- `client/device/session_replay.py` implements `InternalSessionReplay`.
- Replay accepts only an existing committed session under `data/sessions/<session_id>/`.
- `ReplayVerificationError` has stable internal codes for manifest, missing segment, encrypted segment,
  timeline and derived-observation failures. `ReplayInjectedFailure` makes repeatable support tests
  possible without modifying encrypted evidence.
- `ReplayDiagnosticSummary` is the only export-shaped object; raw arrays are available only to an
  internal caller that intentionally iterates `RawFrame` values.

## Verification

```text
./scripts/local-env.sh python -m pytest tests/device/test_session_replay.py tests/device tests/spool tests/hardware_standardization -q
```

Expected coverage includes verified open, frame stepping/ranges/loops, source-index seek, diagnostic
redaction, deterministic failure injection, missing segment and manifest tampering.

Result: **147 passed in 1.22s** on 2026-07-29. `git diff --check` over the implementation,
tests and RAY-86/RAY-88 evidence also passed. Commit SHA will be recorded after the implementation
commit is created.

## Automatic / physical / manual boundary

- Automated tests create temporary encrypted sessions with an ephemeral test key.
- This tool is intentionally internal and has no customer UI, report or cloud upload integration.
- A future UI/support workflow may render a heatmap, COP and curves from this source, but it must keep
  internal quality details out of customer-facing views.

## Commit

Implementation and evidence: `6090c4b` — `Add verified internal hardware session replay`.
