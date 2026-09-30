# RAY-101 Operator End-to-End Acceptance Evidence Index

**Status: preparation complete; field acceptance not run.** This index records package identity and outstanding operator acceptance evidence. It does not mark any workflow step as passed.

## Scope and requirement

- Linear issue: RAY-101, current requirement revision R1, In Progress.
- Registered delivery scope: `operator-end-to-end-acceptance` (the only scope for this issue).
- Scope branch and worktree: `linear/ray-101/operator-end-to-end-acceptance` / `.worktrees/ray-101/operator-end-to-end-acceptance`.
- Scope HEAD at preparation: `db04c072f8611007ddb5be9d9326024ab3fbce5a`.
- Current master used for the acceptance package: `94d0610d920e377d036061177519541bbe30c71e`.
- The scope HEAD is an ancestor of master. GitHub comparison reports master ahead by 58 commits, 0 behind; 106 changed files (+9,074/-117). This scope was not rebased or merged. The build below used the explicit master commit.

## Candidate Windows package

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

R11 (`d3488438a6417cddc811fe961f8ebff810a43466`) and R10 are historical packages and are not substitutes for this `94d0610` candidate. The current package may be referenced as a common master baseline by RAY-546; no RAY-546 artifact or worktree was modified.

## Site readiness and pending acceptance

As checked on 2026-09-30:

- Windows exposed 0 serial ports; the physical pressure device is unavailable on this host.
- Four printer queues were present, including HP LaserJet Pro MFP 4104. Queue presence does not establish that a physical printer can print or that paper output is acceptable.
- No independent non-technical account readiness evidence is available.
- The current controlled configuration evidence targets `db04c072f8611007ddb5be9d9326024ab3fbce5a`, not the package source commit `94d0610d920e377d036061177519541bbe30c71e`. Configuration/package compatibility is unproven; an authorized configuration lead must revalidate it.
- No login, activation, acquisition, upload, PDF export, or physical print was performed.
- The P-07 heel-stripe appearance remains an observation item. RAY-119's dynamic-mask review is pending; this index does not claim a fix.

The following Linear acceptance remains open and requires the target site and an independent non-technical operator:

- Independently install and launch this exact ZIP after the site owner approves use of the unsigned internal candidate.
- Complete P-01–P-11 with the physical pressure device and formal station adapters; document one primary recovery action without substituting automated, fixture, replay, or process-presence evidence.
- Inspect P-07 heel-stripe visibility/stability against the actual live view without retaining raw measurements or heatmap screenshots.
- Verify the report, PDF and physical paper output at P-10.
- Save a second-person-reviewed, redacted operator record and update this index with the actual results.

Before real acquisition or any cloud/print effect, obtain explicit action-time confirmation from the site owner. Do not store names, account identifiers, raw measurements, unique equipment identifiers, activation credentials, cloud parameters, PDFs or print images here.

## Supporting preparation records

The detailed run sheet and blank redacted record template are in the scope's linked shared evidence library:

- `.project-context/evidence/ray-101/operator-end-to-end-acceptance/acceptance/2026-09-30-windows-field-acceptance-preparation.md`
- `.project-context/evidence/ray-101/operator-end-to-end-acceptance/acceptance/redacted-operator-acceptance-record-template.md`
- `.project-context/evidence/ray-101/operator-end-to-end-acceptance/handoffs/2026-09-30-main-build-and-field-acceptance-preparation.md`

The RAY-101 field criterion and the PR/review/CI/merge/scope-receipt chain remain incomplete. Until field and EXE-level evidence is available, a PR carrying this preparation index must remain Draft.