from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

import requests


CHROME_UPLOAD = "https://chromewebstore.googleapis.com/upload/v2/publishers/{publisher}/items/{item}:upload"
CHROME_PUBLISH = "https://chromewebstore.googleapis.com/v2/publishers/{publisher}/items/{item}:publish"
EDGE_ROOT = "https://api.addons.microsoftedge.microsoft.com/v1.1"


def env_value(name: str) -> str:
    return str(os.getenv(name) or "").strip()


def package_metadata(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def required_environment(provider: str) -> dict[str, str]:
    if provider == "chrome":
        names = {
            "access_token": "LEARNNOTE_CHROME_ACCESS_TOKEN",
            "publisher_id": "LEARNNOTE_CHROME_PUBLISHER_ID",
            "item_id": "LEARNNOTE_CHROME_ITEM_ID",
        }
    else:
        names = {
            "api_key": "LEARNNOTE_EDGE_API_KEY",
            "client_id": "LEARNNOTE_EDGE_CLIENT_ID",
            "product_id": "LEARNNOTE_EDGE_PRODUCT_ID",
        }
    return {key: env_value(name) for key, name in names.items()}


def request_headers(provider: str, values: dict[str, str], *, package: bool = False) -> dict[str, str]:
    if provider == "chrome":
        headers = {"Authorization": f"Bearer {values['access_token']}"}
    else:
        headers = {
            "Authorization": f"ApiKey {values['api_key']}",
            "X-ClientID": values["client_id"],
        }
    if package:
        headers["Content-Type"] = "application/zip"
    return headers


def endpoint(provider: str, values: dict[str, str], operation: str) -> str:
    if provider == "chrome":
        template = CHROME_PUBLISH if operation == "publish" else CHROME_UPLOAD
        return template.format(publisher=values["publisher_id"], item=values["item_id"])
    suffix = "/products/{product}/submissions".format(product=values["product_id"])
    return EDGE_ROOT + (suffix if operation == "publish" else suffix + "/draft/package")


def submit(provider: str, package: Path, values: dict[str, str], *, publish: bool, edge_notes: str) -> dict[str, object]:
    upload_response = requests.post(
        endpoint(provider, values, "upload"),
        headers=request_headers(provider, values, package=True),
        data=package.read_bytes(),
        timeout=120,
    )
    result: dict[str, object] = {
        "upload_status": upload_response.status_code,
        "upload_location": upload_response.headers.get("Location", ""),
    }
    if not upload_response.ok:
        result["status"] = "failed"
        result["error"] = "upload_failed"
        return result
    if publish:
        body = edge_notes.encode("utf-8") if provider == "edge" else b"{}"
        publish_response = requests.post(
            endpoint(provider, values, "publish"),
            headers={**request_headers(provider, values), "Content-Type": "text/plain" if provider == "edge" else "application/json"},
            data=body,
            timeout=120,
        )
        result.update({
            "publish_status": publish_response.status_code,
            "publish_location": publish_response.headers.get("Location", ""),
            "status": "submitted" if publish_response.ok else "failed",
            "error": "publish_failed" if not publish_response.ok else "",
        })
    else:
        result.update({"status": "uploaded_draft", "publish_status": None, "error": ""})
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely preflight or explicitly submit a LearnNote browser-store package.")
    parser.add_argument("--provider", choices=("chrome", "edge"), required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--apply", action="store_true", help="Actually upload the package; without this flag no network request is made.")
    parser.add_argument("--publish", action="store_true", help="Publish the uploaded draft; requires --apply.")
    parser.add_argument("--edge-notes", default="LearnNote release package; see the submitted privacy and permission materials.")
    parser.add_argument("--output", type=Path, default=Path("build/store-submit/report.json"))
    args = parser.parse_args()
    if args.publish and not args.apply:
        parser.error("--publish requires --apply")
    package = args.package.expanduser().resolve()
    if not package.is_file() or package.suffix.lower() != ".zip":
        parser.error("--package must point to an existing .zip file")
    values = required_environment(args.provider)
    missing = sorted(key for key, value in values.items() if not value)
    report: dict[str, object] = {
        "provider": args.provider,
        "mode": "apply" if args.apply else "preflight",
        "publish_requested": args.publish,
        "package": package_metadata(package),
        "missing_credentials": missing,
        "network_called": False,
        "status": "ready" if not args.apply else ("blocked_missing_credentials" if missing else "ready"),
    }
    if args.apply:
        if missing:
            report["status"] = "blocked_missing_credentials"
        else:
            report.update(submit(args.provider, package, values, publish=args.publish, edge_notes=args.edge_notes))
            report["network_called"] = True
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if not args.apply or report["status"] in {"ready", "uploaded_draft", "submitted"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
