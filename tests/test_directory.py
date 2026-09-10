from dataclasses import dataclass

import pytest
from research_explorer.models import collect_directory

from doim_explorer.config import load_directory_config
from doim_explorer.directory import (
    PublicFacultyProfileAdapter,
    RefreshGuardError,
    apply_pubmed_queries,
    assert_safe_directory_refresh,
    build_directory_adapter,
    build_pubmed_query,
    collect_directory_snapshot,
    faculty_id_from_profile_url,
)


@dataclass
class FakeResponse:
    url: str
    text: str


class FakeClient:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.seen: list[str] = []

    def get(self, url: str, *, respect_robots: bool = True) -> FakeResponse:
        del respect_robots
        self.seen.append(url)
        return FakeResponse(url=url, text=self.pages[url])


class FallbackClient(FakeClient):
    def get(self, url: str, *, respect_robots: bool = True) -> FakeResponse:
        del respect_robots
        self.seen.append(url)
        return FakeResponse(url=url, text=self.pages.get(url, PROFILE_PAGE))


PRIMARY_TAB_PAGE = """
<main>
  <section id="faculty-panel-primary">
    <div class="gls-card"><h3 class="gls-card-title">Primary Faculty, MD</h3>
      <p class="gls-text-muted">Professor</p>
      <a href="/faculty/mddetail/u0012345">View Full Profile</a></div>
  </section>
  <section id="faculty-panel-adjunct">
    <div class="gls-card"><h3 class="gls-card-title">Adjunct Faculty, PhD</h3>
      <a href="/faculty/mddetail/u0099999">View Full Profile</a></div>
  </section>
</main>
"""

DEDICATED_PRIMARY_PAGE = """
<main>
  <div class="gls-card"><h3 class="gls-card-title">Dedicated Faculty, MD</h3>
    <p>Assistant Professor</p>
    <a href="https://healthcare.utah.edu/fad/mddetail.php?physicianID=u0076543#tabAcademic">View Full Profile</a></div>
</main>
"""

PROFILE_PAGE = """
<html><body><main>
  <script>window.VWO.data.acquia={"title":"Primary Faculty [u0012345]"}</script>
  <h1>Primary Faculty, MD</h1>
  <section><div class="gls-width-expand"><p>Studies implementation science and health equity.</p></div></section>
  <section><h3>Academic Information</h3><p>Departments Primary - Internal Medicine</p></section>
  <section><h2>Education History</h2><p>University of Utah</p></section>
  <a href="https://orcid.org/0000-0002-1825-0097">ORCID</a>
</main></body></html>
"""


def test_builds_one_primary_faculty_adapter_for_each_configured_division() -> None:
    adapter = build_directory_adapter(load_directory_config(), FakeClient({}))

    assert set(adapter.adapters) == {division.id for division in adapter.collect_divisions()}
    assert len(adapter.adapters) == 12


def test_primary_tab_adapter_collects_only_primary_faculty_cards() -> None:
    manifest = load_directory_config()
    division = next(item for item in manifest["divisions"] if item["id"] == "epidemiology")
    client = FakeClient({division["faculty_url"]: PRIMARY_TAB_PAGE})
    adapter = build_directory_adapter(manifest, client)

    faculty = adapter.collect_faculty(next(item for item in adapter.collect_divisions() if item.id == "epidemiology"))

    assert [item.id for item in faculty] == ["u0012345"]
    assert faculty[0].full_name == "Primary Faculty, MD"
    assert faculty[0].title == "Professor"
    assert faculty[0].profile_url == "https://medicine.utah.edu/faculty/mddetail/u0012345"
    assert client.seen == [division["faculty_url"]]


def test_dedicated_primary_adapter_supports_the_infectious_diseases_layout() -> None:
    manifest = load_directory_config()
    division = next(item for item in manifest["divisions"] if item["id"] == "infectious-diseases")
    adapter = build_directory_adapter(manifest, FakeClient({division["faculty_url"]: DEDICATED_PRIMARY_PAGE}))

    faculty = adapter.collect_faculty(
        next(item for item in adapter.collect_divisions() if item.id == "infectious-diseases")
    )

    assert [(item.id, item.title) for item in faculty] == [("u0076543", "Assistant Professor")]


def test_adapter_uses_the_core_directory_protocol_and_merges_division_membership() -> None:
    manifest = load_directory_config()
    pages = {
        division["faculty_url"]: PRIMARY_TAB_PAGE
        if division["id"] != "infectious-diseases"
        else DEDICATED_PRIMARY_PAGE
        for division in manifest["divisions"]
    }

    snapshot = collect_directory(build_directory_adapter(manifest, FakeClient(pages)))

    assert len(snapshot["divisions"]) == 12
    assert {item["id"] for item in snapshot["faculty"]} == {"u0012345", "u0076543"}
    primary = next(item for item in snapshot["faculty"] if item["id"] == "u0012345")
    assert len(primary["division_ids"]) == 11


def test_public_profile_adapter_extracts_text_orcid_and_stable_id() -> None:
    client = FakeClient({"https://medicine.utah.edu/faculty/mddetail/u0012345": PROFILE_PAGE})
    from research_explorer.models import Faculty

    faculty = PublicFacultyProfileAdapter(client).collect_profile(
        Faculty(
            id="u0012345",
            full_name="Primary Faculty, MD",
            profile_url="https://medicine.utah.edu/faculty/mddetail/u0012345",
            division_ids=("epidemiology",),
            title="Professor",
        )
    )

    assert faculty.id == "u0012345"
    assert faculty.bio == "Studies implementation science and health equity."
    assert "Internal Medicine" in faculty.academic_information
    assert faculty.orcid_id == "0000-0002-1825-0097"


def test_profile_collection_records_health_and_generates_pubmed_queries() -> None:
    manifest = load_directory_config()
    pages = {
        division["faculty_url"]: PRIMARY_TAB_PAGE
        if division["id"] != "infectious-diseases"
        else DEDICATED_PRIMARY_PAGE
        for division in manifest["divisions"]
    }
    snapshot = collect_directory_snapshot(manifest, FallbackClient(pages), checked_at="2026-09-10T00:00:00Z")

    assert snapshot["stats"]["faculty"] == 2
    assert len(snapshot["health"]) == 12
    assert {row["status"] for row in snapshot["health"]} == {"ok"}
    assert all(row["checked_at"] == "2026-09-10T00:00:00Z" for row in snapshot["health"])
    assert all(item["pubmed_query"] for item in snapshot["faculty"])
    assert all("Affiliation" in item["pubmed_query"] for item in snapshot["faculty"])


def test_profile_collection_exposes_a_blocked_source_without_discarding_other_sources() -> None:
    manifest = load_directory_config()
    pages = {
        division["faculty_url"]: PRIMARY_TAB_PAGE
        if division["id"] != "infectious-diseases"
        else DEDICATED_PRIMARY_PAGE
        for division in manifest["divisions"]
    }
    blocked_url = next(
        division["faculty_url"]
        for division in manifest["divisions"]
        if division["id"] == "oncology"
    )

    class BlockedClient(FallbackClient):
        def get(self, url: str, *, respect_robots: bool = True) -> FakeResponse:
            if url == blocked_url:
                raise PermissionError("robots.txt denied source")
            return super().get(url, respect_robots=respect_robots)

    snapshot = collect_directory_snapshot(manifest, BlockedClient(pages))

    statuses = {row["division_id"]: row["status"] for row in snapshot["health"]}
    assert statuses["oncology"] == "blocked"
    assert statuses["epidemiology"] == "ok"
    assert snapshot["stats"]["faculty"] == 2


def test_pubmed_queries_are_affiliation_scoped_and_support_exact_overrides() -> None:
    from research_explorer.models import Faculty

    faculty = Faculty(id="u1", full_name="Grace B. Hopper, PhD", profile_url="https://medicine.utah.edu/faculty/mddetail/u1")
    query = build_pubmed_query(faculty, ["University of Utah"])
    assert query == '"Hopper GB"[Author] AND ("University of Utah"[Affiliation])'
    overridden = apply_pubmed_queries(
        [faculty], {"pubmed": {"overrides": {"u1": "custom query"}}}
    )[0]
    assert overridden.pubmed_query == "custom query"


def test_refresh_guard_rejects_total_and_per_division_drops() -> None:
    previous = {
        "stats": {"faculty": 4},
        "divisions": [{"id": "a"}],
        "faculty": [{"id": str(index), "division_ids": ["a"]} for index in range(4)],
    }
    current = {
        "stats": {"faculty": 2},
        "divisions": [{"id": "a"}],
        "faculty": [{"id": "0", "division_ids": ["a"]}, {"id": "1", "division_ids": ["a"]}],
    }
    with pytest.raises(RefreshGuardError, match="dropped"):
        assert_safe_directory_refresh(previous, current)

    with pytest.raises(RefreshGuardError, match="minimum"):
        assert_safe_directory_refresh(None, {"stats": {"faculty": 0}, "faculty": []})


@pytest.mark.parametrize(
    ("profile_url", "expected"),
    [
        ("https://medicine.utah.edu/faculty/mddetail/u0043464", "u0043464"),
        ("https://healthcare.utah.edu/fad/mddetail.php?physicianID=U0385820", "u0385820"),
        ("https://medicine.utah.edu/faculty/someone", ""),
    ],
)
def test_extracts_faculty_profile_identifiers(profile_url: str, expected: str) -> None:
    assert faculty_id_from_profile_url(profile_url) == expected
