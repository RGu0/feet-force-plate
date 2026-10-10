# RAY-101 Operator End-to-End Acceptance Evidence Index

**Status (2026-10-10): field workflow reported complete by the user; formal acceptance evidence remains incomplete.** P-01–P-11 are recorded as user-reported, not independently verified. The actual tested package identity and recovery-action result are not yet established.

## Scope and requirement

- Linear issue: RAY-101, current requirement revision R1, In Progress.
- Registered delivery scope: `operator-end-to-end-acceptance` (the only scope for this issue).
- Scope branch and worktree: `linear/ray-101/operator-end-to-end-acceptance` / `.worktrees/ray-101/operator-end-to-end-acceptance`.
- Scope HEAD at preparation: `db04c072f8611007ddb5be9d9326024ab3fbce5a`.
- Master at the 2026-09-30 package-preparation date: `94d0610d920e377d036061177519541bbe30c71e`.
- GitHub current master as checked on 2026-10-10: `fe1c1eb5716eb41657697b62424992c397ce53c0`. PR #61's dynamic-mask change is in master at merge commit `70bf6455f7a8694bdbd4eae4dcb017944f0403e0`; current master is 14 commits beyond that merge.
- This scope was not rebased or merged. The 94d0610 package below is a preparation candidate only; the user has not confirmed that it was the package used for the reported field run.

## Windows package prepared on 2026-09-30 (field-use identity unconfirmed)

| Field | Value |
|---|---|
| ZIP | `FeetForcePlate-0.1.0-windows-x86_64.zip` |
| Local package path | `C:\FeetForcePlate\ray101-windows-main-94d0610-20260930-7a71fdbf\release\FeetForcePlate-0.1.0-windows-x86_64.zip` |
| Release manifest | `C:\FeetForcePlate\ray101-windows-main-94d0610-20260930-7a71fdbf\release\release-manifest.json` |
| App version / target | `0.1.0` / `windows-x86_64` |
| Source commit | `94d0610d920e377d036061177519541bbe30c71e` |
| Archive SHA-256 | `5f8f582449903513b288244afa232a7c417b8d4c6d1e480c766669b8f1145bf9` |
| Archive size | 147,459,592 bytes |
| Signing status | `unsigned-development`; internal acceptance only, not production/customer delivery |

The committed Windows `dev.ps1 build` portable packaging path ran through the governed `project_command.py --project-root <main> --action build` entry. The package script generated the manifest and ran `verify-portable-release.ps1 -AllowUnsignedDevelopment`. The manifest SHA-256, `.sha256` sidecar, and independent archive hash matched. PyInstaller emitted optional/platform import warnings, recorded in the local build output's `warn-FeetForcePlate.txt`. The application was not launched; no EXE runtime or UI result is claimed.

A separate PR #61 Windows archive was prepared from PR head `b03ad4d05013ad6a77675a99cf89704c3fa4faa8`, SHA-256 `7a1ca6d0ee5651fd2ccc23579b12a748a5e4ac2dc95e047d3727aa98f1adf297`, also `unsigned-development`. Its source tree matches the PR #61 merge tree, but its manifest is not for current master `fe1c1eb`. Neither package is claimed as the package used in the user's reported field run.

R11 (`d3488438a6417cddc811fe961f8ebff810a43466`) and R10 are historical packages and are not substitutes for this `94d0610` candidate. The current package may be referenced as a common master baseline by RAY-546; no RAY-546 artifact or worktree was modified.

## Site readiness and pending acceptance

As checked on 2026-09-30:

- Windows exposed 0 serial ports; the physical pressure device is unavailable on this host.
- Four printer queues were present, including HP LaserJet Pro MFP 4104. Queue presence does not establish that a physical printer can print or that paper output is acceptable.
- No independent non-technical account readiness evidence is available.
- The current controlled configuration evidence targets `db04c072f8611007ddb5be9d9326024ab3fbce5a`, not the package source commit `94d0610d920e377d036061177519541bbe30c71e`. Configuration/package compatibility is unproven; an authorized configuration lead must revalidate it.
- No login, activation, acquisition, upload, PDF export, or physical print was performed.
- The P-07 heel-stripe appearance remains a field observation item. RAY-119 PR #61 merged on 2026-09-30 and wired the frozen dynamic defect-mask snapshot into formal live capture; it did not add real-time display mask application. The reported field run has no specific stripe observation recorded.

## User-reported field result (2026-10-10)

The user confirmed that acceptance was completed and that the full process was performed independently without encountering problems. A redacted user-report record is stored at `.project-context/evidence/ray-101/operator-end-to-end-acceptance/acceptance/2026-10-10-user-reported-operator-acceptance.md`. It records P-01–P-11 as user-reported PASS and preserves unknowns instead of inferring them.

Remaining evidence gaps: the tested ZIP SHA/source commit and its signing/approval status; confirmation of the non-technical operator/account and target-site equipment conditions; the specific P-07 heel-stripe observation; second-person review; and a recovery action. Since no problem occurred, no recovery action was triggered; this is recorded as `NOT TRIGGERED`, not as a recovery pass. The requirement owner must decide whether an approved controlled recovery scenario is required.

Before real acquisition or any cloud/print effect, obtain explicit action-time confirmation from the site owner. Do not store names, account identifiers, raw measurements, unique equipment identifiers, activation credentials, cloud parameters, PDFs or print images here.

## Supporting preparation records

The detailed run sheet and blank redacted record template are in the scope's linked shared evidence library:

- `.project-context/evidence/ray-101/operator-end-to-end-acceptance/acceptance/2026-09-30-windows-field-acceptance-preparation.md`
- `.project-context/evidence/ray-101/operator-end-to-end-acceptance/acceptance/redacted-operator-acceptance-record-template.md`
- `.project-context/evidence/ray-101/operator-end-to-end-acceptance/handoffs/2026-09-30-main-build-and-field-acceptance-preparation.md`

The field run is user-reported complete, but the exact package and several acceptance details remain unverified. PR #62 is still Draft; review, updated CI for the revised index, merge, and scope receipt remain pending. Do not mark RAY-101 Done until the current R1 criteria and the PR/scope completion gates are satisfied.
