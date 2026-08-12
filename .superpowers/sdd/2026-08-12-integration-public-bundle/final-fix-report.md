# RAY-99 Integration Public Bundle Final Fix Report

## Result

All three Important final-review findings were addressed in code commit
`109137b4e0e5d46694e801480e01e6ae6cfa3753` (`fix: close integration bundle
review findings`).

## Findings Addressed

1. **Exact 32-byte raw public keys are validated before text normalization.**
   Both the publication helper and `client.cloud.packaged_defaults` now accept
   an exact 32-byte payload unchanged, including leading or trailing bytes whose
   values are ASCII whitespace. Only non-32-byte inputs enter the ASCII
   decode/strip/strict-base64 branch. Tests cover a leading space byte and a
   trailing newline byte in both boundaries.
2. **The real root-only publication path is selected in GitHub quality CI.**
   The production `EUID` gate is unchanged. The Linux quality job first runs
   the functional file unprivileged to prove denial, then uses the runner's
   governed `sudo` capability with the absolute project-environment Python
   interpreter to execute the same real wrapper and publication tests as root.
   Windows/macOS retain the portable selective regression list without POSIX
   privilege assumptions.
3. **Success stdout is exact, normalized, ordered, and injection-safe.**
   The removed `bundle=` line cannot reappear without failing the complete
   stdout assertion. Output is exactly destination, normalized validated API
   endpoint, normalized validated License key ID, then the three fixed-name
   SHA-256 lines in order. Control characters are rejected in endpoint, key ID,
   source paths, and the public bundle root before filesystem publication. The
   production loader also rejects control characters in packaged metadata.

## Files Changed

- `.github/workflows/quality.yml`
- `client/cloud/packaged_defaults.py`
- `client/tests/test_packaged_cloud_defaults.py`
- `cloud/tests/test_deployment_assets.py`
- `cloud/tests/test_integration_public_bundle.py`
- `deploy/aliyun/seed/build-integration-public-bundle.sh`

## TDD Evidence

The first governed test run against test-only changes failed on the intended
boundaries:

```text
4 failed, 1054 passed, 16 skipped, 3 warnings in 65.19s
```

The four failures were the two exact-32-byte raw-key cases and the two packaged
metadata control-character cases. No production file had been changed before
this RED run.

## Governed Verification

All project commands used the active RAY-99 scope worktree and the committed
runtime gate:

```text
python3 /Users/rui/Documents/0-AgentSkills/git-worktree-linear-workflow/skills/initializing-agent-governance/scripts/project_command.py \
  --project-root /Users/rui/Developer/Projects/feet-force-plate/.worktrees/ray-99/lossy-network-acceptance \
  --action test
```

Result:

```text
1058 passed, 16 skipped, 3 warnings in 64.27s
```

Fifteen skips are the intentional root publication cases on the unprivileged
macOS process; the GitHub Linux root step added by this change selects them.
The remaining skip is the pre-existing live PostgreSQL DSN test.

```text
... project_command.py --project-root <active-worktree> --action lint
```

Result:

```text
All checks passed!
Success: no issues found in 13 source files
```

```text
... project_command.py --project-root <active-worktree> --action build
```

Result: exit `0`; the locked PyInstaller build dependencies were resolved and
installed without errors.

Additional checks:

```text
git diff --check                         # exit 0
bash -n deploy/aliyun/seed/build-integration-public-bundle.sh  # exit 0
```

## Self-Review

- Confirmed the shell root gate remains the first behavioral gate and no
  test-only production bypass was introduced.
- Confirmed the CI root invocation uses the project-synchronized interpreter,
  runs only on Linux, and executes the actual wrapper through pytest.
- Confirmed raw payload length is checked before any strip/decode operation in
  both validators; textual base64 remains strict and must decode to 32 bytes.
- Confirmed every stdout line is asserted literally and in order using
  independently computed digests; source paths and file contents are absent.
- Confirmed normalized endpoint and key ID are obtained from the successfully
  validated staged payload rather than echoed from raw CLI arguments.
- Confirmed control-character rejection occurs before destination creation and
  covers every CLI value that can reach a path, published payload, or stdout.
- Confirmed no credentials, private key material, public file contents, or
  operator source paths were added to tests, logs, workflow output, or this
  report.
