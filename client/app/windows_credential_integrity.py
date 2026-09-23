"""Prevent elevated Windows processes from creating user-vault-bound data."""

from __future__ import annotations

import ctypes
import os
from collections.abc import Callable


def require_standard_user_process(
    *, is_elevated: Callable[[], bool] | None = None
) -> None:
    """Fail closed before Credential Manager access uses another integrity context."""

    try:
        elevated = (is_elevated or _is_windows_process_elevated)()
    except Exception:
        raise RuntimeError("unable to verify Windows process integrity") from None
    if elevated:
        raise RuntimeError(
            "FeetForcePlate must not run as administrator because local encrypted "
            "data is bound to the standard-user credential vault"
        )


def _is_windows_process_elevated() -> bool:
    if os.name != "nt":
        return False
    ctypes.set_last_error(0)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    elevated = bool(shell32.IsUserAnAdmin())
    if elevated:
        return True
    if ctypes.get_last_error() != 0:
        raise RuntimeError("Windows elevation probe failed")
    return False
