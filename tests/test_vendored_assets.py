"""The site loads no CDN scripts; third-party browser code is committed and pinned here.

`site/assets/vendor/VENDOR.md` documents how to update a pinned file; this test is the
guard that keeps the committed bytes and that document in agreement, so the library
cannot drift or be swapped without the change being visible in review.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR_DIR = ROOT / "site" / "assets" / "vendor"

PINNED_SHA256 = {
    "cytoscape.min.js": "5f3b5b529546d5af1fc5628590af033b74511a5b6f789f5f4682845863228b91",
}


def test_vendored_cytoscape_matches_its_pinned_hash() -> None:
    for name, expected in PINNED_SHA256.items():
        path = VENDOR_DIR / name
        assert path.exists(), f"{path} is missing"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == expected, f"{name} does not match its pinned hash; update VENDOR.md if this is intentional"


def test_vendored_cytoscape_carries_its_mit_license() -> None:
    license_text = (VENDOR_DIR / "cytoscape.LICENSE.txt").read_text(encoding="utf-8")
    assert "MIT" in license_text or "Permission is hereby granted" in license_text


def test_vendored_cytoscape_is_a_self_contained_umd_build() -> None:
    # No bundler runs against this file, so it must attach itself to `window` on its own
    # and must not `require()` or `import` anything else at runtime.
    script = (VENDOR_DIR / "cytoscape.min.js").read_text(encoding="utf-8")
    assert "typeof exports" in script and "typeof module" in script
    assert ".cytoscape=t()" in script or ").cytoscape=" in script


def test_vendor_readme_documents_the_pinned_version() -> None:
    readme = (VENDOR_DIR / "VENDOR.md").read_text(encoding="utf-8")
    assert "3.34.3" in readme
    for digest in PINNED_SHA256.values():
        assert digest in readme
