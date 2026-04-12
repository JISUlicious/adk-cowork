"""``http.fetch`` — safe GET with scheme + size + redirect caps.

This is the only outbound-HTTP surface in core. Restrictions:

* Only ``http://`` and ``https://``. ``file://``, ``data:``, etc. rejected.
* Size capped at ``_MAX_BYTES`` (2 MiB) — bodies larger than that are
  truncated and the result is marked ``truncated: true``.
* Redirects capped at 5.
* Response bodies are returned as text (utf-8 best-effort). Binary downloads
  should use ``python_exec`` with an explicit ``network=True`` snippet.

A hostname allowlist is out of scope for v0.1 (spec says ``allow = ["*"]``);
if/when tightened, the check lives here.
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx
from google.adk.tools.tool_context import ToolContext

_MAX_BYTES = 2 * 1024 * 1024
_MAX_REDIRECTS = 5
_DEFAULT_TIMEOUT = 20.0


def http_fetch(
    url: str,
    tool_context: ToolContext,
    timeout_sec: float = _DEFAULT_TIMEOUT,
) -> dict[str, object]:
    """Fetch a URL via HTTPS/HTTP and return the response body as text.

    Args:
        url: Absolute ``http://`` or ``https://`` URL.
        timeout_sec: Per-request timeout in seconds (capped at 60).

    Returns:
        ``{"url", "status", "headers", "content", "truncated"}`` or
        ``{"error": ...}``.
    """
    del tool_context  # no per-session state needed yet
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return {"error": f"unsupported scheme: {parsed.scheme!r}"}
    if not parsed.netloc:
        return {"error": f"missing host: {url!r}"}
    timeout = max(1.0, min(float(timeout_sec), 60.0))
    try:
        with httpx.Client(
            follow_redirects=True,
            max_redirects=_MAX_REDIRECTS,
            timeout=timeout,
        ) as client:
            resp = client.get(url)
    except httpx.HTTPError as e:
        return {"error": f"http error: {e}"}

    raw = resp.content or b""
    truncated = len(raw) > _MAX_BYTES
    if truncated:
        raw = raw[:_MAX_BYTES]
    return {
        "url": str(resp.url),
        "status": resp.status_code,
        "headers": {k.lower(): v for k, v in resp.headers.items()},
        "content": raw.decode("utf-8", errors="replace"),
        "truncated": truncated,
    }
