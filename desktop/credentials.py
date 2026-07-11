from __future__ import annotations

import ctypes
import os
from ctypes import wintypes


CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168


class CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


PCREDENTIALW = ctypes.POINTER(CREDENTIALW)


def _advapi32():
    if os.name != "nt":
        raise RuntimeError("Windows Credential Manager is only available on Windows.")
    library = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    library.CredWriteW.argtypes = [PCREDENTIALW, wintypes.DWORD]
    library.CredWriteW.restype = wintypes.BOOL
    library.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(PCREDENTIALW)]
    library.CredReadW.restype = wintypes.BOOL
    library.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    library.CredDeleteW.restype = wintypes.BOOL
    library.CredFree.argtypes = [ctypes.c_void_p]
    library.CredFree.restype = None
    return library


def credential_target(provider: str) -> str:
    safe = "".join(char for char in str(provider or "default").lower() if char.isalnum() or char in ".-_")
    return f"LearnNote/model/{safe or 'default'}"


def write_secret(provider: str, secret: str) -> None:
    value = str(secret or "")
    if not value:
        raise ValueError("API Key cannot be empty.")
    encoded = value.encode("utf-16-le")
    blob = (ctypes.c_ubyte * len(encoded)).from_buffer_copy(encoded)
    credential = CREDENTIALW()
    credential.Type = CRED_TYPE_GENERIC
    credential.TargetName = credential_target(provider)
    credential.CredentialBlobSize = len(encoded)
    credential.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
    credential.Persist = CRED_PERSIST_LOCAL_MACHINE
    credential.UserName = "LearnNote"
    if not _advapi32().CredWriteW(ctypes.byref(credential), 0):
        raise ctypes.WinError(ctypes.get_last_error())


def read_secret(provider: str) -> str:
    library = _advapi32()
    pointer = PCREDENTIALW()
    if not library.CredReadW(credential_target(provider), CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
        error = ctypes.get_last_error()
        if error == ERROR_NOT_FOUND:
            return ""
        raise ctypes.WinError(error)
    try:
        size = int(pointer.contents.CredentialBlobSize)
        if not size:
            return ""
        raw = ctypes.string_at(pointer.contents.CredentialBlob, size)
        return raw.decode("utf-16-le")
    finally:
        library.CredFree(pointer)


def delete_secret(provider: str) -> bool:
    library = _advapi32()
    if library.CredDeleteW(credential_target(provider), CRED_TYPE_GENERIC, 0):
        return True
    error = ctypes.get_last_error()
    if error == ERROR_NOT_FOUND:
        return False
    raise ctypes.WinError(error)
