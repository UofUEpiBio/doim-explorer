from dataclasses import dataclass

import pytest
from research_explorer.models import collect_directory

from doim_explorer.config import load_directory_config
from doim_explorer.directory import build_directory_adapter, faculty_id_from_profile_url


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
