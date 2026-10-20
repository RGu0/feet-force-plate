"""Compatibility for application configuration predating foundation 0.2."""

from pathlib import Path

from techflex_cloud_foundation import InsecureTransportRejected


def foundation_verify(verify: bool | str) -> bytes | None:
    """Translate the existing system-trust/CA-path setting into foundation input."""
    if verify is True:
        return None
    if isinstance(verify, str):
        return Path(verify).read_bytes()
    raise InsecureTransportRejected("TLS verification cannot be disabled")
