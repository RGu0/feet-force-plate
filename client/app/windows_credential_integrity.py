"""Prevent elevated Windows processes from creating user-vault-bound data."""

from __future__ import annotations

import ctypes
import os
from collections.abc import Callable
from ctypes import wintypes


_TOKEN_QUERY = 0x0008
_TOKEN_ELEVATION = 20


class _TokenElevation(ctypes.Structure):
    _fields_ = [("TokenIsElevated", wintypes.DWORD)]


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


def _is_windows_process_elevated(*, kernel32=None, advapi32=None) -> bool:
    if os.name != "nt":
        return False
    if kernel32 is None or advapi32 is None:
        default_kernel32, default_advapi32 = _windows_token_apis()
        kernel32 = kernel32 or default_kernel32
        advapi32 = advapi32 or default_advapi32
    token = wintypes.HANDLE()
    if not kernel32.OpenProcessToken(
        kernel32.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token)
    ):
        raise RuntimeError("Windows token elevation query failed")
    try:
        elevation = _TokenElevation()
        returned = wintypes.DWORD()
        if not advapi32.GetTokenInformation(
            token,
            _TOKEN_ELEVATION,
            ctypes.byref(elevation),
            ctypes.sizeof(elevation),
            ctypes.byref(returned),
        ):
            raise RuntimeError("Windows token elevation query failed")
        return bool(elevation.TokenIsElevated)
    finally:
        if token.value and not kernel32.CloseHandle(token):
            raise RuntimeError("Windows token elevation query failed")


def _windows_token_apis():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    kernel32.OpenProcessToken.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    return kernel32, advapi32
