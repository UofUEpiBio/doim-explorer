"""Publish and validate the static site's public branding document."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from doim_explorer.config import BRANDING_CONFIG_VERSION, ProfileError

BRANDING_DOCUMENT_TYPE = "doim-branding"


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def build_branding_document(
    config: Mapping[str, Any], *, generated_at: str | None = None
) -> dict[str, Any]:
    """Return the small public document consumed before the directory loads."""

    if config.get("schema_version") != BRANDING_CONFIG_VERSION:
        raise ProfileError(f"Branding configuration schema_version must be {BRANDING_CONFIG_VERSION}")
    document = {
        "document_type": BRANDING_DOCUMENT_TYPE,
        "schema_version": BRANDING_CONFIG_VERSION,
        "generated_at": generated_at or _now(),
        "site": deepcopy(dict(config["site"])),
        "theme": deepcopy(dict(config["theme"])),
        "assets": deepcopy(dict(config["assets"])),
        "analytics": deepcopy(dict(config["analytics"])),
    }
    validate_branding_document(document)
    return document


def validate_branding_document(document: Mapping[str, Any]) -> None:
    """Reject a malformed branding document before it reaches a visitor's browser."""

    if document.get("document_type") != BRANDING_DOCUMENT_TYPE:
        raise ProfileError("branding document_type is not supported")
    if document.get("schema_version") != BRANDING_CONFIG_VERSION:
        raise ProfileError(f"branding schema_version must be {BRANDING_CONFIG_VERSION}")
    if not isinstance(document.get("generated_at"), str) or not document["generated_at"]:
        raise ProfileError("branding.generated_at must be a non-empty string")
    for table in ("site", "theme", "assets", "analytics"):
        if not isinstance(document.get(table), Mapping):
            raise ProfileError(f"branding.{table} must be a table")
