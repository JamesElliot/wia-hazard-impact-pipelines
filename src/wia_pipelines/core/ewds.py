from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def _require(name: str):
    import importlib

    return importlib.import_module(name)


# Public, non-sensitive endpoint; only the API key is a secret. GloFAS
# historical is served from the Early Warning Data Store, a separate service
# from the classic Climate Data Store already configured (~/.cdsapirc) for
# this repo's SPEI/UTCI pipelines, so it gets its own credential file rather
# than overloading the existing one.
DEFAULT_EWDS_URL = "https://ewds.climate.copernicus.eu/api"
DEFAULT_EWDS_RC_PATH = Path("~/.ewdsapirc").expanduser()


def read_ewds_credentials(rc_path: str | Path | None = None) -> dict[str, str] | None:
    """Read a `~/.ewdsapirc`-style file (same `url:`/`key:` format as cdsapi)."""

    path = Path(rc_path).expanduser() if rc_path else DEFAULT_EWDS_RC_PATH
    if not path.exists():
        return None

    url: str | None = None
    key: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        field, _, value = stripped.partition(":")
        field = field.strip().lower()
        value = value.strip()
        if field == "url":
            url = value
        elif field == "key":
            key = value
    if key:
        return {"url": url or DEFAULT_EWDS_URL, "key": key}
    return None


def resolve_ewds_credentials(
    url: str | None = None,
    key: str | None = None,
    rc_path: str | Path | None = None,
) -> tuple[str | None, str | None]:
    resolved_url = url or os.environ.get("EWDS_API_URL")
    resolved_key = key or os.environ.get("EWDS_API_KEY")
    if resolved_key:
        return resolved_url or DEFAULT_EWDS_URL, resolved_key

    creds = read_ewds_credentials(rc_path)
    if creds:
        return resolved_url or creds["url"], creds["key"]
    return resolved_url, resolved_key


def download_ewds(
    dataset: str,
    request: dict[str, Any],
    out_zip: Path,
    url: str | None = None,
    key: str | None = None,
    rc_path: str | Path | None = None,
) -> tuple[bool, str | None]:
    cdsapi = _require("cdsapi")
    out_zip.parent.mkdir(parents=True, exist_ok=True)

    resolved_url, resolved_key = resolve_ewds_credentials(url=url, key=key, rc_path=rc_path)
    if not resolved_key:
        return False, (
            "No EWDS credentials found. Configure ~/.ewdsapirc (url/key, same "
            "format as ~/.cdsapirc), set EWDS_API_KEY (and optionally "
            "EWDS_API_URL), or pass explicit url/key. GloFAS historical is "
            "served from the Early Warning Data Store, a separate endpoint "
            "from the classic CDS credentials already configured for this "
            "repo's SPEI/UTCI pipelines."
        )

    try:
        client = cdsapi.Client(url=resolved_url, key=resolved_key)
        result = client.retrieve(dataset, request)
        result.download(target=str(out_zip))
        return True, None
    except Exception as exc:  # pragma: no cover - network/auth failures are runtime dependent
        return False, str(exc)
