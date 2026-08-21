from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


MEDIA_ADAPTER_CONTRACT_VERSION = 1


@dataclass(frozen=True)
class MediaAdapterDescriptor:
    """Versioned source boundary used by normalization, diagnostics, and future adapters."""

    adapter_id: str
    version: int
    domains: tuple[str, ...]
    supports_page_url: bool = True
    supports_direct_media: bool = True
    notes: str = ""

    def matches(self, url: str) -> bool:
        host = (urlparse(str(url or "")).hostname or "").lower().rstrip(".")
        return any(host == domain or host.endswith(f".{domain}") for domain in self.domains)

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.adapter_id,
            "version": self.version,
            "domains": list(self.domains),
            "supports_page_url": self.supports_page_url,
            "supports_direct_media": self.supports_direct_media,
            "notes": self.notes,
        }


MEDIA_ADAPTERS: tuple[MediaAdapterDescriptor, ...] = (
    MediaAdapterDescriptor(
        adapter_id="bilibili",
        version=1,
        domains=("bilibili.com", "b23.tv"),
        notes="yt-dlp first; browser handoff can add authenticated playback evidence.",
    ),
    MediaAdapterDescriptor(
        adapter_id="youtube",
        version=1,
        domains=("youtube.com", "youtu.be"),
        notes="yt-dlp first; only process pages the user is authorized to access.",
    ),
    MediaAdapterDescriptor(
        adapter_id="chaoxing",
        version=1,
        domains=("chaoxing.com", "xuexitong.com", "mooc1.com", "mooc2.com"),
        notes="Authorized browser handoff only; preserve login boundary and never bypass DRM or course progress controls.",
    ),
    MediaAdapterDescriptor(
        adapter_id="web",
        version=1,
        domains=(),
        notes="Generic direct media, manifest, iframe, player-request, or local fallback path.",
    ),
)


def media_adapter_for_url(url: str) -> MediaAdapterDescriptor:
    for descriptor in MEDIA_ADAPTERS:
        if descriptor.adapter_id != "web" and descriptor.matches(url):
            return descriptor
    return next(descriptor for descriptor in MEDIA_ADAPTERS if descriptor.adapter_id == "web")


def media_adapter_descriptors() -> list[dict[str, object]]:
    return [
        {
            "contract_version": MEDIA_ADAPTER_CONTRACT_VERSION,
            **descriptor.as_dict(),
        }
        for descriptor in MEDIA_ADAPTERS
    ]
