# RAY-100 Seed Access UI Evidence

This directory contains deterministic, simulated desktop UI evidence for the
seed-customer access flow. The capture script injects fixed hardware and access
state; it does not connect to a cloud endpoint or physical device.

Evidence scope: `simulated-access-ui`.

- `login.png`: institution account login and explicit integration label.
- `activation.png`: provider-provisioned account, one-time activation code,
  password confirmation, and masked physical hardware suffix. There is no
  institution search/create/join or customer-admin workflow.
- `locked.png`: full-window privacy mask; background services are outside the
  overlay lifecycle.
- `license-suspended.png`: new testing disabled while report access and upload
  continuity remain available.
- `manifest.json`: dimensions, state names, commit SHA, and evidence boundary.

These images prove rendering and client-state behavior only. They are not live
cloud, physical-hardware, production-security, operator, or clinical evidence.
