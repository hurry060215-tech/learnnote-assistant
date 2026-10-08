"""Run backend contracts with external network attempts rejected locally.

Tests may use a loopback server, but a missed fixture/mock must never contact
a real website, model provider or model-download service.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
import os
from pathlib import Path
import socket
import subprocess
import sys
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


@contextmanager
def offline_network():
    import requests
    # yt-dlp subclasses Popen at import time; load it before applying the guard.
    import yt_dlp  # noqa: F401

    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_resolve = socket.getaddrinfo
    real_send = requests.adapters.HTTPAdapter.send

    def check_address(address):
        if isinstance(address, tuple) and address[0] not in LOCAL_HOSTS:
            raise OSError("Offline tests forbid external network")

    def connect(sock, address):
        check_address(address)
        return real_connect(sock, address)

    def connect_ex(sock, address):
        check_address(address)
        return real_connect_ex(sock, address)

    def resolve(host, *args, **kwargs):
        if host not in LOCAL_HOSTS and host is not None:
            raise OSError("Offline tests forbid external DNS")
        return real_resolve(host, *args, **kwargs)

    def send(adapter, request, *args, **kwargs):
        if urlsplit(request.url).hostname not in LOCAL_HOSTS:
            raise requests.ConnectionError("Offline tests forbid external HTTP")
        return real_send(adapter, request, *args, **kwargs)

    class OfflinePopen(subprocess.Popen):
        def __init__(self, args, *other, **kwargs):
            if isinstance(args, (list, tuple)) and any("yt_dlp" in str(value) or "yt-dlp" in str(value) for value in args):
                if any(str(value).startswith(("http://", "https://")) and urlsplit(str(value)).hostname not in LOCAL_HOSTS for value in args):
                    raise OSError("Offline tests forbid external yt-dlp")
            super().__init__(args, *other, **kwargs)

    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}))
        stack.enter_context(patch.object(socket.socket, "connect", connect))
        stack.enter_context(patch.object(socket.socket, "connect_ex", connect_ex))
        stack.enter_context(patch.object(socket, "getaddrinfo", resolve))
        stack.enter_context(patch.object(requests.adapters.HTTPAdapter, "send", send))
        stack.enter_context(patch.object(subprocess, "Popen", OfflinePopen))
        yield


def main() -> int:
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "backend"))
    os.environ["PYTHONPATH"] = os.pathsep.join(filter(None, (str(ROOT / "backend"), str(ROOT), os.environ.get("PYTHONPATH", ""))))
    with offline_network():
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover("backend/tests"))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
