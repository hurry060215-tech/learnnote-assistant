"""Serve a new synthetic acceptance workspace with loopback-only networking."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--model-base", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    data = Path(args.data_dir).resolve()
    # The caller owns this freshly created directory and its eventual cleanup.
    if not data.is_dir() or any(data.iterdir()):
        raise ValueError("Acceptance data directory must exist and be empty")
    from urllib.parse import urlsplit
    endpoint = urlsplit(args.model_base)
    if endpoint.scheme != "http" or endpoint.hostname != "127.0.0.1" or not endpoint.port:
        raise ValueError("The mocked model must use an explicit loopback port")
    for name in list(os.environ):
        if name.startswith(("LEARNNOTE_", "OPENAI_", "AZURE_", "ANTHROPIC_")) or name.upper().endswith("_PROXY"):
            del os.environ[name]
    os.environ.update(LEARNNOTE_DATA_DIR=str(data), LEARNNOTE_DEPLOYMENT_MODE="local",
                      LEARNNOTE_LLM_BASE_URL=args.model_base, LEARNNOTE_LLM_MODEL="mocked-acceptance-model",
                      LEARNNOTE_LLM_API_KEY="", PYTHONUTF8="1")
    sys.path.insert(0, str(root / "backend"))
    spec = importlib.util.spec_from_file_location("offline_acceptance", root / "scripts/test-backend-offline.py")
    offline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(offline)
    # Apply the existing test guard before importing uvicorn or the application.
    with offline.offline_network():
        import uvicorn
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(128)
            port = listener.getsockname()[1]
            os.environ["LEARNNOTE_BACKEND_ORIGIN"] = f"http://127.0.0.1:{port}"
            print(json.dumps({"fixture_origin": os.environ["LEARNNOTE_BACKEND_ORIGIN"],
                              "offline_network": True}), flush=True)
            server = uvicorn.Server(uvicorn.Config("app.main:app", host="127.0.0.1", port=port, log_level="warning"))
            server.run(sockets=[listener])


if __name__ == "__main__":
    main()
