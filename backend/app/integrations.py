from __future__ import annotations

from . import API_VERSION, APP_VERSION, TASK_SCHEMA_VERSION, UX_PROTOCOL_VERSION
from .adapters import MEDIA_ADAPTER_CONTRACT_VERSION, media_adapter_descriptors


INTEGRATION_MANIFEST_VERSION = 1


def integration_manifest() -> dict:
    return {
        "schema_version": INTEGRATION_MANIFEST_VERSION,
        "product": "learnnote-assistant",
        "app_version": APP_VERSION,
        "api_version": API_VERSION,
        "protocol_version": UX_PROTOCOL_VERSION,
        "task_schema_version": TASK_SCHEMA_VERSION,
        "media_adapter_contract_version": MEDIA_ADAPTER_CONTRACT_VERSION,
        "media_adapters": media_adapter_descriptors(),
        "exports": {
            "markdown": "/api/tasks/{task_id}/exports/markdown",
            "bundle": "/api/tasks/{task_id}/exports/bundle",
            "sanitized_bundle": "/api/tasks/{task_id}/exports/sanitized-bundle",
            "support_package": "/api/tasks/{task_id}/exports/support-package",
            "events": "/api/tasks/{task_id}/events",
        },
        "privacy": {
            "official_cloud": False,
            "accounts_required": False,
            "source_media_in_sanitized_bundle": False,
            "cookies_in_sanitized_bundle": False,
            "signed_urls_in_sanitized_bundle": False,
        },
    }
