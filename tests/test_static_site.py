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


def test_static_site_lands_on_ask_and_labels_the_division_view() -> None:
    html = (ROOT / "site/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")

    assert 'href="#ask" aria-label="DOIM Explorer home"' in html
    assert '<button class="nav-link is-active" type="button" data-view="ask">Ask</button>' in html
    assert '<button class="nav-link" type="button" data-view="overview">Divisions</button>' in html
    assert html.index('data-view="ask"') < html.index('data-view="overview"')
    assert '<section class="view is-active" id="view-ask" data-view-panel="ask">' in html
    assert '<section class="view" id="view-overview" data-view-panel="overview" hidden>' in html
    assert 'const VIEWS = ["ask", "overview", "faculty", "expertise", "publications", "health"]' in javascript
    assert 'const active = VIEWS.includes(view) ? view : "ask";' in javascript


def test_static_site_reads_the_versioned_doim_documents() -> None:
    html = (ROOT / "site/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")

    assert 'href="./assets/styles.css"' in html
    assert 'src="./assets/app.js"' in html
    assert 'const BRANDING_URL = "./data/branding.json"' in javascript
    assert 'const DIRECTORY_URL = "./data/directory.json"' in javascript
    assert 'const PUBLICATIONS_URL = "./data/publications.json"' in javascript
    assert 'const PUBLICATION_DETAILS_URL = "./data/publication-details.json"' in javascript
    assert ".toml" not in javascript
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


def test_faculty_expertise_and_publications_are_available_without_cloud_configuration() -> None:
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
    # Ask degrades to that same in-browser search whenever the assistant cannot answer,
    # so no view depends on the deployed service being reachable.
    assert "function askFallback(" in javascript
    assert 'search(query, "ask-summary", "ask-results")' in javascript


def test_ask_sends_the_question_to_the_deployed_service_and_cites_published_records() -> None:
    html = (ROOT / "site/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")

    for identifier in ("ask-status", "ask-answer", "ask-citations", "ask-fallback"):
        assert f'id="{identifier}"' in html
    # The expertise view promises the query stays local, so the Ask view has to say plainly
    # that this one does not.
    assert "Your question is sent to Google Cloud to be answered" in html
    assert "askQuestion(byId(\"ask-query\").value)" in javascript
    assert "JSON.stringify({ question })" in javascript
    # Citations are rendered from the published documents the page already loaded, never
    # from markers invented by the model.
    assert "publicationsById.get(entry.work_id)" in javascript
    assert "function citedInOrder(" in javascript


def test_publication_details_are_loaded_only_when_a_reader_requests_an_abstract() -> None:
    javascript = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")

    assert "function loadPublicationDetails()" in javascript
    assert "data-load-details" in javascript
    assert "fetchJson(PUBLICATION_DETAILS_URL)" in javascript


def test_static_site_is_unofficial_and_links_to_the_department() -> None:
    html = (ROOT / "site/index.html").read_text(encoding="utf-8")

    assert "This is an unofficial University of Utah Department of Internal Medicine explorer." in html
    assert 'href="https://medicine.utah.edu/internal-medicine"' in html


def test_static_site_applies_configured_theme_assets_and_opt_in_analytics() -> None:
    html = (ROOT / "site/index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "site/assets/app.js").read_text(encoding="utf-8")
    css = (ROOT / "site/assets/styles.css").read_text(encoding="utf-8")

    assert 'id="brand-mark"' in html
    assert 'id="unofficial-notice"' in html
    assert 'id="official-site-link"' in html
    assert 'id="og-image"' in html
    assert "function applyBranding(" in javascript
    assert "function loadAnalytics(" in javascript
    assert "data-doim-analytics" in javascript
    assert "googletagmanager.com/gtag/js" not in html
    assert "--brand-primary: #be0000;" in css
    assert "ForeSITE" not in css
    assert (ROOT / "site/assets/doim-explorer-social-card.png").exists()


def test_published_doim_documents_match_the_static_site_copies() -> None:
    for name, document_type in (
        ("branding.json", "doim-branding"),
        ("directory.json", "doim-directory"),
        ("publications.json", "doim-publications"),
        ("publication-details.json", "doim-publication-details"),
    ):
        canonical = json.loads((ROOT / "data" / name).read_text(encoding="utf-8"))
        static = json.loads((ROOT / "site" / "data" / name).read_text(encoding="utf-8"))
        assert static == canonical
        assert canonical["document_type"] == document_type
