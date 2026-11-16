"""Prevent concurrent MemCard commands in the current Windows session."""

from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import os

from .paths import BackupError


@contextmanager
def single_instance(name: str = "Local\\MemCard.SingleInstance.v1"):
    if os.name != "nt":
        raise BackupError("MemCard currently supports Windows only")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateMutexW(None, False, name)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    already_exists = ctypes.get_last_error() == 183
    try:
        if already_exists:
            raise BackupError("Another MemCard instance is already running")
        yield
    finally:
        kernel.CloseHandle(handle)
