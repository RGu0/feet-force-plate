# RAY-119 manual device-ID design

## Scope

Replace the engineering-maintenance device-ID requirement that depends on a
CH340 USB serial identity.  An authorised engineer can add an asset ID by
manual entry or select a previously registered ID.  The last selected ID is
restored after application restart and after device reconnect.

QR-code scanning is not implemented in this change.  It may later populate the
same manual-entry value without changing storage or selection semantics.

## Data and service behaviour

`EngineeringDeviceBindingStore` becomes an engineering device-ID registry.  It
stores a schema version, the selected device ID, and the registered IDs.  It
does not store a serial-port path, USB descriptor, VID/PID, USB location, or
hardware fingerprint.  A reader of an older binding file retains the known
device IDs and selected device ID while ignoring legacy connection IDs.

`EngineeringMaintenanceService.bind_current_device()` retains its public entry
point for the existing UI but treats the supplied ID as an engineer-managed
asset ID.  It requires the existing engineering confirmation and configured
registry, but no connected-device identity.  `read_distribution()` uses the
selected ID when the matching mask store is available.  A reconnect neither
clears nor revalidates the selected ID; the engineering UI exposes that current
selection so the engineer can change it.

## Boundaries and errors

The ordinary operator UI remains unable to access the registry or mask-health
details.  Missing engineering confirmation, no configured registry, no
selected device ID, or a missing/mismatched mask store continue to fail closed.
Manual selection is an operational audit responsibility, not an automatic
proof of physical-board identity.

## Verification

Tests will first demonstrate that an engineer can add, select and restore an
asset ID when no USB identity provider exists.  They will also demonstrate that
a changed/reconnected identity does not invalidate a manually selected ID, and
that the existing confirmation and unbound-device protections remain intact.
The RAY-119 evidence README and Linear acceptance checklist will record the
fresh automated results.  The outstanding physical acceptance is an engineer's
manual inspection of bad-point distribution on a connected device.
