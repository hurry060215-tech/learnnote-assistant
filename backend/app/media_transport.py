"""Validated, pinned transport for browser-discovered media URLs."""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
from contextlib import contextmanager
from urllib.parse import urljoin, urlparse, urlunparse

import requests

from .downloader_policy import UnsafeMediaTarget


def _safe_header_value(value: object) -> str:
    return " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())


def _url_origin(url: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlparse(url or "")
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return None
        if parsed.username is not None or parsed.password is not None:
            return None
        host = parsed.hostname.rstrip(".").lower()
        if "%" in host:
            return None
        try:
            host = ipaddress.ip_address(host).compressed
        except ValueError:
            host = host.encode("idna").decode("ascii")
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    except (UnicodeError, ValueError):
        return None
    return parsed.scheme.lower(), host, port


def _trusted_page_for_target(target_url: str, *page_urls: str) -> str:
    target_origin = _url_origin(target_url)
    for page_url in page_urls:
        if target_origin and _url_origin(page_url) == target_origin:
            return page_url
    return next((page_url for page_url in page_urls if page_url), "")


def _validated_media_target(url: str, trusted_page_url: str) -> tuple[str, str, str, int]:
    """Validate a media URL and pin one of its already-checked destination IPs."""
    if any(ord(character) < 32 for character in (url or "")):
        raise UnsafeMediaTarget("媒体地址包含无效控制字符。")
    origin = _url_origin(url)
    if not origin:
        raise UnsafeMediaTarget("媒体地址必须是无用户名或密码的 HTTP(S) URL。")
    scheme, host, port = origin
    parsed = urlparse(url)
    try:
        address_info = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise UnsafeMediaTarget(f"媒体地址无法解析：{host}") from exc

    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for item in address_info:
        raw_address = item[4][0].split("%", 1)[0]
        try:
            address = ipaddress.ip_address(raw_address)
        except ValueError as exc:
            raise UnsafeMediaTarget("媒体地址解析结果无效。") from exc
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise UnsafeMediaTarget("媒体地址没有可连接的目标地址。")

    local_addresses = [address for address in addresses if not address.is_global]
    for address in local_addresses:
        if address.is_unspecified or address.is_multicast or address.is_link_local or address.is_reserved:
            raise UnsafeMediaTarget("媒体地址指向不可访问的本地或保留网络。")
    if local_addresses:
        trusted_origin = _url_origin(trusted_page_url)
        if trusted_origin != origin or len(local_addresses) != len(addresses):
            raise UnsafeMediaTarget("媒体地址指向本机或私有网络，但与当前页面不同源。")

    normalized_url = urlunparse(parsed._replace(fragment=""))
    return normalized_url, addresses[0].compressed, host, port


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, pinned_address: str, port: int, timeout: int):
        super().__init__(host, port=port, timeout=timeout, context=ssl.create_default_context())
        self._pinned_address = pinned_address

    def connect(self) -> None:
        self.sock = socket.create_connection((self._pinned_address, self.port), self.timeout, self.source_address)
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


class _PinnedHTTPResponse:
    def __init__(self, response: http.client.HTTPResponse, connection: http.client.HTTPConnection, url: str):
        self._response = response
        self._connection = connection
        self.status_code = response.status
        self.headers = requests.structures.CaseInsensitiveDict(response.getheaders())
        self.url = url

    def iter_content(self, chunk_size: int = 8192):
        while True:
            chunk = self._response.read(chunk_size)
            if not chunk:
                break
            yield chunk

    def close(self) -> None:
        try:
            self._response.close()
        finally:
            self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


def _request_path(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse(("", "", parsed.path or "/", parsed.params, parsed.query, ""))


def _host_header(host: str, port: int, scheme: str) -> str:
    rendered_host = f"[{host}]" if ":" in host else host
    default_port = 443 if scheme == "https" else 80
    return rendered_host if port == default_port else f"{rendered_host}:{port}"


@contextmanager
def open_validated_media_response(
    method: str,
    url: str,
    *,
    trusted_page_url: str,
    headers: dict[str, str],
    body: bytes | None,
    timeout: int,
):
    current_url = url
    current_method = (method or "GET").upper()
    current_body = body
    current_headers = {name: _safe_header_value(value) for name, value in headers.items() if value}
    if current_method not in {"GET", "HEAD", "POST", "PUT", "PATCH"}:
        raise UnsafeMediaTarget("媒体预检使用了不允许的 HTTP 方法。")

    response_wrapper: _PinnedHTTPResponse | None = None
    try:
        for _ in range(6):
            safe_url, pinned_address, host, port = _validated_media_target(current_url, trusted_page_url)
            scheme = urlparse(safe_url).scheme.lower()
            request_headers = dict(current_headers)
            request_headers["Host"] = _host_header(host, port, scheme)
            request_headers["Accept-Encoding"] = "identity"
            connection: http.client.HTTPConnection
            if scheme == "https":
                connection = _PinnedHTTPSConnection(host, pinned_address, port, timeout)
            else:
                connection = http.client.HTTPConnection(pinned_address, port=port, timeout=timeout)
            try:
                connection.request(current_method, _request_path(safe_url), body=current_body, headers=request_headers)
                raw_response = connection.getresponse()
            except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
                connection.close()
                raise requests.ConnectionError(f"媒体预检连接失败：{exc}") from exc

            response_wrapper = _PinnedHTTPResponse(raw_response, connection, safe_url)
            location = response_wrapper.headers.get("location", "")
            if response_wrapper.status_code not in {301, 302, 303, 307, 308} or not location:
                yield response_wrapper
                return

            next_url = urljoin(safe_url, location)
            if _url_origin(next_url) != _url_origin(safe_url):
                for sensitive_header in ("Authorization", "Cookie", "Origin"):
                    current_headers.pop(sensitive_header, None)
            if response_wrapper.status_code == 303 or (response_wrapper.status_code in {301, 302} and current_method == "POST"):
                current_method = "GET"
                current_body = None
                current_headers.pop("Content-Type", None)
                current_headers.pop("Content-Length", None)
            response_wrapper.close()
            response_wrapper = None
            current_url = next_url
        raise requests.TooManyRedirects("媒体地址重定向次数过多。")
    finally:
        if response_wrapper is not None:
            response_wrapper.close()


__all__ = ["_trusted_page_for_target", "open_validated_media_response"]
