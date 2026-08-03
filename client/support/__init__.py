"""Privacy-safe support diagnostics for the packaged client."""

from .safe_events import (
    SafeClientCounters,
    SafeClientEvent,
    SafeClientEventName,
    SafeClientEventOutcome,
    SafeClientEventRecorder,
    SafeClientEventStore,
    SafeClientLogRecord,
)
from .diagnostic_export import (
    DiagnosticExportResult,
    PlatformFamily,
    SafeDiagnosticExporter,
    SafeDiagnosticMetadata,
    SupportRecipient,
)

__all__ = [
    "SafeClientEventName",
    "SafeClientEventOutcome",
    "SafeClientCounters",
    "SafeClientEvent",
    "SafeClientLogRecord",
    "SafeClientEventRecorder",
    "SafeClientEventStore",
    "PlatformFamily",
    "SupportRecipient",
    "SafeDiagnosticMetadata",
    "DiagnosticExportResult",
    "SafeDiagnosticExporter",
]
