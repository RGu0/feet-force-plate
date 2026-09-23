"""Prevent elevated Windows processes from creating user-vault-bound data."""

from __future__ import annotations

import ctypes
import os
from collections.abc import Callable


def require_standard_user_process(
    *, is_elevated: Callable[[], bool] | None = None
) -> None:
    """Fail closed before Credential Manager access uses another integrity context."""

    elevated = (is_elevated or _is_windows_process_elevated)()
    if elevated:
        raise RuntimeError(
            "FeetForcePlate must not run as administrator because local encrypted "
            "data is bound to the standard-user credential vault"
        )


def _is_windows_process_elevated() -> bool:
    if os.name != "nt":
        return False
    return bool(ctypes.windll.shell32.IsUserAnAdmin())
