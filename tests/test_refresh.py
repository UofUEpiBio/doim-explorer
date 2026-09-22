"""Incremental refresh orchestration without live profile or embedding requests."""

from __future__ import annotations

from pathlib import Path

import pytest
from research_explorer import rag

from doim_explorer.config import load_directory_config
from doim_explorer.contracts import (
    build_directory_document,
    build_publications_snapshot,
    split_publications_snapshot,
)
from doim_explorer.directory import collect_directory_snapshot
from doim_explorer.refresh import RefreshError, main, parse_faculty_ids, refresh
from doim_explorer.update import write_snapshot


class StubEmbedder:
    def __call__(self, texts, _task_type):
        return [[0.1] * rag.DEFAULT_DIMS for _ in texts]


class Response:
    def __init__(self, url: str, text: str) -> None:
        self.url = url
        self.text = text


class Client:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages

    def get(self, url: str, *, respect_robots: bool = True) -> Response:
        del respect_robots
        return Response(url, self.pages.get(url, PROFILE))


PRIMARY = """
<main><section id="faculty-panel-primary"><div class="gls-card">
<h3 class="gls-card-title">Primary Faculty, MD</h3><p>Professor</p>
<a href="/faculty/mddetail/u0012345">View Full Profile</a>
</div></section></main>
"""
DEDICATED = """
<main><div class="gls-card"><h3 class="gls-card-title">Primary Faculty, MD</h3><p>Professor</p>
<a href="/faculty/mddetail/u0012345">View Full Profile</a></div></main>
"""
PROFILE = """
<main><h1>Primary Faculty, MD</h1><section><div class="gls-width-expand">Biography</div></section></main>
"""


def _accepted_documents(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path, Path]:
    manifest = load_directory_config()
    pages = {
        division["faculty_url"]: PRIMARY if division["id"] != "infectious-diseases" else DEDICATED
        for division in manifest["divisions"]
    }
    collected = collect_directory_snapshot(manifest, Client(pages))
    faculty = [{**member, "collect_publications": False} for member in collected["faculty"]]
    directory = build_directory_document(manifest, faculty, collected["health"])
    publication_snapshot = build_publications_snapshot(directory, client=object())
    publications, details = split_publications_snapshot(publication_snapshot)
    data = tmp_path / "data"
    site = tmp_path / "site-data"
    directory_path = data / "directory.json"
    publications_path = data / "publications.json"
    details_path = data / "publication-details.json"
    collaboration_path = data / "collaboration.json"
    write_snapshot(directory, directory_path)
    write_snapshot(publications, publications_path)
    write_snapshot(details, details_path)
    return directory_path, publications_path, details_path, collaboration_path, site, data / "rag"


def test_parse_faculty_ids_normalizes_and_rejects_invalid_values() -> None:
    assert parse_faculty_ids("U0012345, u0076543 u0012345") == ["u0012345", "u0076543"]
    with pytest.raises(RefreshError, match="must name"):
        parse_faculty_ids("  ")
    with pytest.raises(RefreshError, match="must look"):
        parse_faculty_ids("faculty-1")
    assert main(["--faculty-ids", ""]) == 1


def test_targeted_refresh_stages_complete_artifacts_and_reuses_index_shape(
    tmp_path, monkeypatch
) -> None:
    directory_path, publications_path, details_path, collaboration_path, site_dir, rag_dir = (
        _accepted_documents(tmp_path)
    )
    monkeypatch.setattr("doim_explorer.refresh.rag.vertex_embedder", lambda: StubEmbedder())
    monkeypatch.setattr(
        "doim_explorer.refresh.refresh_selected_profiles",
        lambda _manifest, previous, _ids, **_kwargs: previous,
    )

    directory, publications, details, collaboration, index = refresh(
        mode="targeted",
        faculty_ids=["u0012345"],
        config_path=Path("config/directory.toml"),
        overrides_path=Path("config/faculty-overrides.toml"),
        directory_path=directory_path,
        publications_path=publications_path,
        details_path=details_path,
        collaboration_path=collaboration_path,
        site_dir=site_dir,
        rag_dir=rag_dir,
    )

    assert directory["faculty"]
    assert publications["document_type"] == "doim-publications"
    assert details["document_type"] == "doim-publication-details"
    assert collaboration["document_type"] == "doim-collaboration"
    assert index["embedded"] > 0
    assert (site_dir / "directory.json").is_file()
    assert (site_dir / "collaboration.json").is_file()
    assert (rag_dir / "manifest.json").is_file()
