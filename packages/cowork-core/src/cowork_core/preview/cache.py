"""Content-hash-based preview cache under the workspace root."""

from __future__ import annotations

from pathlib import Path

from cowork_core.preview.converters import PreviewResult, content_hash, preview_file

# Bump when the rendered output format changes so stale entries are
# ignored on upgrade (e.g. markdown wrapper CSS rework).
_RENDER_VERSION = "v2"


class PreviewCache:
    def __init__(self, cache_dir: Path) -> None:
        self._dir = cache_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def get(self, file_path: Path) -> PreviewResult:
        chash = content_hash(file_path)
        ext = file_path.suffix.lower()
        cache_key = f"{chash}_{ext.lstrip('.')}_{_RENDER_VERSION}"
        cached = self._dir / cache_key

        if cached.exists():
            meta_path = self._dir / f"{cache_key}.meta"
            ct = "application/octet-stream"
            if meta_path.exists():
                ct = meta_path.read_text(encoding="utf-8").strip()
            return PreviewResult(body=cached.read_bytes(), content_type=ct, content_hash=chash)

        result = preview_file(file_path)
        cached.write_bytes(result.body)
        (self._dir / f"{cache_key}.meta").write_text(result.content_type, encoding="utf-8")
        return result
