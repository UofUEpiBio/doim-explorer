import json
from pathlib import Path

from doim_explorer.branding import BRANDING_DOCUMENT_TYPE, build_branding_document
from doim_explorer.config import load_branding_config
from doim_explorer.update import branding_main


def test_branding_document_keeps_analytics_opt_in_and_local_assets() -> None:
    document = build_branding_document(
        load_branding_config(), generated_at="2026-09-10T00:00:00Z"
    )

    assert document["document_type"] == BRANDING_DOCUMENT_TYPE
    assert document["theme"]["primary"] == "#BE0000"
    assert document["assets"]["mark"] == ""
    assert document["analytics"] == {"measurement_id": ""}


def test_branding_command_publishes_matching_static_configuration(tmp_path: Path) -> None:
    output = tmp_path / "data" / "branding.json"
    site_dir = tmp_path / "site-data"

    assert branding_main(["--output", str(output), "--site-dir", str(site_dir)]) == 0

    canonical = json.loads(output.read_text(encoding="utf-8"))
    static = json.loads((site_dir / "branding.json").read_text(encoding="utf-8"))
    assert canonical == static
    assert canonical["document_type"] == BRANDING_DOCUMENT_TYPE
