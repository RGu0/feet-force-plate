# 2026-07-28 real storage-exhaustion result

## Scope

This was a physical DO-P4864 runtime run, not a simulator. The device node was
`/dev/cu.usbserial-1120`. The output root was a disposable 8 MB HFS+ disk image
mounted at `/Volumes/FeetForcePlateStorageFault`; a 7 MB filler left about
788 KB available before the run. No project or normal user data volume was
filled.

## Observed result

The acceptance runner ended without a JSON summary. Inspection of the isolated
volume found no formal SQLite session, segment, or derived-artifact records:

```text
sessions: 0
segments: 0
session_artifacts: 0
```

However, six encrypted `.ffps` files remained below the active staging directory.
The runtime directory used 556 KB and the test volume had only 344 KB remaining.
No raw matrix, key file, or staging file has been copied into repository evidence.

## Result boundary

This is an inconclusive acceptance result, not proof that the storage-failure
path is safe. The absence of a formal session is correct, but the missing
sanitized summary means the observation cannot distinguish a completed
storage-handoff failure from an interrupted runner. The acquisition path already
owns a `discard(...)` call for invalidation; no production cleanup change is
justified from this incomplete observation alone.

The acceptance runner has since gained an external `--summary-output` option
with an automated regression: its sanitized failure result is written outside
the deliberately full volume and contains no raw matrix, key material, or
exception text. The physical test must now be repeated before drawing a disk-full
conclusion.

## External-summary rerun — accepted

The same disposable-volume method was repeated after the runner change. The 8 MB
HFS+ image was prefilled to approximately 356 KB free and then reached 100% usage
during a real capture on `/dev/cu.usbserial-1120`. The external sanitized summary
reported `INVALID` with `acceptance runner failed: OSError`; its SHA-256 is
`6637f551e87aca4cc95ccd5e417b1f3257918ba94c2ccb3a4847e2ae84dcf851` and its
repository copy is `storage-exhaustion-runtime-20260728.json`.

After the run, the constrained volume contained only the filler and SQLite state
files: no `.staging` files remained. SQLite queries returned zero formal sessions,
segments, and derived artifacts. This is accepted evidence that a host-observable
storage exhaustion does not publish a partial formal session and cleans temporary
capture data. It does not expose raw matrices, key material, or the OS exception
text in repository evidence.
