import json
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class IdCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        identifier = dict(attrs).get("id")
        if identifier:
            self.ids.add(identifier)


def test_static_site_has_each_doim_directory_view() -> None:
    parser = IdCollector()
    parser.feed((ROOT / "site/index.html").read_text(encoding="utf-8"))

    assert {
        "view-overview",
        "view-faculty",
        "view-expertise",
        "view-publications",
        "view-ask",
        "view-health",
    } <= parser.ids


def test_static_site_reads_the_versioned_doim_documents() -> None:
    html = (ROOT / "site/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")

    assert 'href="./assets/styles.css"' in html
    assert 'src="./assets/app.js"' in html
    assert 'const DIRECTORY_URL = "./data/directory.json"' in javascript
    assert 'const PUBLICATIONS_URL = "./data/publications.json"' in javascript
    assert 'const PUBLICATION_DETAILS_URL = "./data/publication-details.json"' in javascript
    assert 'directory.document_type !== "doim-directory"' in javascript
    assert 'value.document_type !== "doim-publications"' in javascript


def test_static_site_replaces_the_legacy_insightnet_views_and_language() -> None:
    html = (ROOT / "site/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")

    assert "DOIM Explorer" in html
    assert "University of Utah Department of Internal Medicine" in html
    assert "InsightNet" not in html
    assert "snapshot.organizations" not in javascript
    assert "snapshot.researchers" not in javascript
    for legacy_view in ("tools", "partners", "centers"):
        assert f'data-view="{legacy_view}"' not in html
        assert f'data-view-panel="{legacy_view}"' not in html


def test_faculty_expertise_publications_and_ask_are_available_without_cloud_configuration() -> None:
    html = (ROOT / "site/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")

    for identifier in (
        "faculty-filters",
        "faculty-list",
        "expertise-form",
        "expertise-results",
        "publication-filters",
        "publication-list",
        "ask-form",
        "ask-results",
        "health-body",
    ):
        assert f'id="{identifier}"' in html
    assert "Your query stays in this browser." in html
    assert "function search(" in javascript
    assert "Google Cloud" not in html
    assert "run.app" not in javascript


def test_publication_details_are_loaded_only_when_a_reader_requests_an_abstract() -> None:
    javascript = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")

    assert "function loadPublicationDetails()" in javascript
    assert "data-load-details" in javascript
    assert "fetchJson(PUBLICATION_DETAILS_URL)" in javascript


def test_static_site_is_unofficial_and_links_to_the_department() -> None:
    html = (ROOT / "site/index.html").read_text(encoding="utf-8")

    assert "This is an unofficial University of Utah Department of Internal Medicine explorer." in html
    assert 'href="https://medicine.utah.edu/internal-medicine"' in html


def test_published_doim_documents_match_the_static_site_copies() -> None:
    for name, document_type in (
        ("directory.json", "doim-directory"),
        ("publications.json", "doim-publications"),
        ("publication-details.json", "doim-publication-details"),
    ):
        canonical = json.loads((ROOT / "data" / name).read_text(encoding="utf-8"))
        static = json.loads((ROOT / "site" / "data" / name).read_text(encoding="utf-8"))
        assert static == canonical
        assert canonical["document_type"] == document_type
