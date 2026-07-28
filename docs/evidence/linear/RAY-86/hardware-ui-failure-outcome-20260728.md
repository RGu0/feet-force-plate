# RAY-86 Hardware to UI Failure Outcome Evidence

- Issue: RAY-86 — 可靠采集监控与 P1 验收
- URL: https://linear.app/ray-app/issue/RAY-86/可靠采集监控与-p1-验收
- Captured at: 2026-07-28
- Snapshot: In Progress; P1：可靠采集; Urgent

## Implemented boundary

`HardwareSessionRuntime` now returns a `HardwareSessionResult.ui_failure` for an invalid
hardware session. It is separate from the hardware-to-algorithm physical-force-field
contract and contains only:

```text
code + recovery_action + retry_allowed + operator_message_key
```

The UI must use the stable code/message key and must not expose raw serial paths, exception
classes, bytes or local storage implementation details. Detailed reasons remain in the
hardware audit path. Invalid sessions remain discarded and never generate an algorithm input.

## Covered mappings

| Source | UI code | Recovery action |
| --- | --- | --- |
| Transport disconnect | `DEVICE_DISCONNECTED` | `RECONNECT_DEVICE` |
| Five seconds without valid decoded signal | `NO_VALID_SIGNAL` | `CHECK_SENSOR_AND_RETRY` |
| Storage handoff failure | `LOCAL_STORAGE_UNAVAILABLE` | `FREE_LOCAL_STORAGE` |
| Quality-gate unusable sensor data | `SENSOR_DATA_UNUSABLE` | `CHECK_SENSOR_AND_RETRY` |
| Force conversion/saturation failure | `FORCE_CONVERSION_FAILED` | `CHECK_SENSOR_AND_RETRY` |
| Valid-session finalization failure | `LOCAL_FINALIZATION_FAILED` | `CONTACT_SUPPORT` |
| Unexpected hardware processing failure | `HARDWARE_PROCESSING_FAILED` | `CONTACT_SUPPORT` |

`SENSOR_DATA_UNUSABLE` deliberately does not diagnose a physical device failure. The UI should
ask the operator to inspect the pressure board and retry; maintenance escalation is appropriate
only if the problem persists.

## Implementation files

- `client/device/session_ui.py`
- `client/device/session_runtime.py`
- `tests/device/test_session_ui.py`
- `docs/algorithm/00-hardware-algorithm-interaction-v1.md`
- `docs/algorithm/physical-input-interface-v1.md`

## Automated verification

Command:

```text
./scripts/local-env.sh python -m pytest tests/device/test_session_ui.py tests/device/test_session_runtime.py
```

Result: **10 passed** on 2026-07-28.

The dedicated result-code unit test accounts for five cases; the existing session-runtime suite
was also run as a compatibility regression and is not modified by this evidence item.

`git diff --check` passed for all files in this evidence item.

## Boundaries and remaining work

The hardware port is implemented and tested. UI controller/view binding and localized copy are
owned by the software/UI layer; they must consume `ui_failure` rather than the raw `reason`
string. No real-device claim is made by this automated mapping test. The existing physical
cable-removal and disk-full evidence remains separate acceptance evidence for the underlying
failure handling.

## Commit

The associated commit SHA is recorded in the RAY-86 Linear completion comment after commit.
