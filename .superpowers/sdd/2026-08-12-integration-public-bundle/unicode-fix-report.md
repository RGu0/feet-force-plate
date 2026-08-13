# RAY-99 Unicode stdout injection fix

## Path and invariant

`build-integration-public-bundle.sh` accepts operator-supplied API endpoint,
License key ID, and public bundle root.  It persists the first two in
`cloud-default.json`, then loads and prints the normalized endpoint and key ID
to stdout.  `load_packaged_cloud_defaults()` later loads the persisted fields.

The invariant is that API endpoint, License key ID, and output root where it is
accepted cannot contain Unicode categories `Cc`, `Zl`, or `Zp`.  Printable
Unicode remains valid.

## Evidence

- Red: `uv run --locked --extra dev python -m pytest client/tests/test_packaged_cloud_defaults.py -k unsafe_unicode` failed before the predicate change.  The U+2028 and U+2029 cases did not raise; the pre-existing Cc cases still raised with the former message.
- Green: `uv run --locked --extra dev python -m pytest client/tests/test_packaged_cloud_defaults.py && bash -n deploy/aliyun/seed/build-integration-public-bundle.sh && python3 -c 'import unicodedata; assert unicodedata.category("\u2028") == "Zl"; assert unicodedata.category("\u2029") == "Zp"; print("unicode category controls verified")'` passed: 10 tests passed, shell syntax passed, and category controls were verified.
- Positive control: `test_loader_accepts_printable_unicode_license_key_id` accepts `license/授权-✓`.
- Governed test: `project_command.py --project-root /Users/rui/Developer/Projects/feet-force-plate/.worktrees/ray-99/lossy-network-acceptance --action test` passed (1,077 collected).
- Governed lint: same command with `--action lint` passed (ruff and mypy).
- Governed build: same command with `--action build` passed (compile build).

## Files and commit

- `deploy/aliyun/seed/build-integration-public-bundle.sh`
- `client/cloud/packaged_defaults.py`
- `client/tests/test_packaged_cloud_defaults.py`
- This report.

Commit: final Git `HEAD` at handoff (`fix(ray-99): reject Unicode output separators`).

## Residual uncertainty

The normal integration bundle command was not executed against a real root-owned
publication directory or production credentials.  The embedded helper predicate
was syntax-checked and mirrors the loader regression-covered `Cc`/`Zl`/`Zp`
invariant; live deployment behavior remains an operator validation boundary.
