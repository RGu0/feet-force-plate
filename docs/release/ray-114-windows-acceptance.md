# RAY-114 Windows acceptance index

## Scope and source

- Scope: `windows-real-device-acceptance`
- Requirement revision: `R2`
- Source commit: `0da022523fc6e7240c423631925010c536a19d7b`
- Authoritative acceptance record: `.project-context/evidence/ray-114/windows-real-device-acceptance/acceptance/windows-p00-cloud-default-ui-20260903.json`

## Accepted Windows evidence

- Cloud-default validation used `https://39.105.216.113:7443` with integration mode enabled and key identifier `license/1`.
- At 175% display scaling, the P-00 login-precondition page was readable without overlap.
- The operator confirmed the keyboard focus order: `机构账号` → `登录密码` → `登录` → `重新检查硬件` → `无法登录？` → `使用 License 注册`.
- The operator confirmed independent hardware recovery: after disconnecting the device, recheck reported `未发现可用压力设备`; after reconnecting it, recheck reported `已连接可用压力设备`.

## Boundary

This index contains no secrets and records no login, collection, activation, participant, screening session, measurement, device identifier, report, or upload data.
