"""Public primary-faculty directory adapters for University of Utah DOIM.

The department's twelve division directories are Drupal pages.  Eleven present a
``#faculty-panel-primary`` tab alongside adjunct and emeritus tabs; Infectious
Diseases is a dedicated primary-faculty page.  Keeping those layouts explicit lets
the collector reject a markup change rather than silently mixing in non-primary
faculty.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import parse_qs, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag
from research_explorer.collectors import SourceClient
from research_explorer.models import DirectoryAdapter, Division, Faculty
from research_explorer.text import clean_text

_PROFILE_IDENTIFIER = re.compile(r"/mddetail/(u\d+)/?$")
_PRIMARY_PANEL_DIVISIONS = frozenset(
    {
        "cardiovascular-medicine",
        "endocrinology",
        "epidemiology",
        "gastroenterology-hepatology-nutrition",
        "general-internal-medicine",
        "geriatrics",
        "hematology-hematologic-malignancies",
        "nephrology-hypertension",
        "oncology",
        "respiratory-critical-care-occupational-pulmonary-medicine",
        "rheumatology",
    }
)
_DEDICATED_PRIMARY_DIVISIONS = frozenset({"infectious-diseases"})
_ADAPTER_DIVISION_IDS = _PRIMARY_PANEL_DIVISIONS | _DEDICATED_PRIMARY_DIVISIONS


class _Response(Protocol):
    url: str
    text: str


class _DirectoryClient(Protocol):
    def get(self, url: str, *, respect_robots: bool = True) -> _Response: ...


def _division_from_record(value: Mapping[str, object]) -> Division:
    return Division(
        id=str(value["id"]),
        name=str(value["name"]),
        source_url=str(value["source_url"]),
        faculty_url=str(value["faculty_url"]),
        summary=str(value.get("summary", "")),
    )


def _profile_url(page_url: str, href: str) -> str:
    """Normalize a public University of Utah profile URL, omitting fragments."""

    parsed = urlparse(urljoin(page_url, href))
    if parsed.scheme != "https" or not parsed.netloc.endswith("utah.edu"):
        return ""
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", parsed.query, ""))


def faculty_id_from_profile_url(profile_url: str) -> str:
    """Return the U of U public profile identifier embedded in a profile link.

    The division cards use either ``/faculty/mddetail/u########`` or the older
    ``fad/mddetail.php?physicianID=u########`` URL.  Both point to the same
    University-maintained faculty identifier, so it is the only key used while
    adapters de-duplicate a faculty member across divisions.
    """

    parsed = urlparse(profile_url)
    path_match = _PROFILE_IDENTIFIER.search(parsed.path)
    if path_match:
        return path_match.group(1).lower()
    query_id = parse_qs(parsed.query).get("physicianID", [""])[0]
    return query_id.lower() if re.fullmatch(r"u\d+", query_id, flags=re.IGNORECASE) else ""


def _card_faculty(card: Tag, page_url: str, division_id: str) -> Faculty | None:
    heading = card.select_one("h3.gls-card-title")
    profile = next(
        (
            anchor
            for anchor in card.select("a[href]")
            if clean_text(anchor.get_text(" ", strip=True)).casefold() == "view full profile"
        ),
        None,
    )
    if heading is None or profile is None:
        return None
    profile_url = _profile_url(page_url, str(profile.get("href", "")))
    faculty_id = faculty_id_from_profile_url(profile_url)
    full_name = clean_text(heading.get_text(" ", strip=True))
    if not full_name or not profile_url or not faculty_id:
        return None
    title = ""
    for paragraph in card.select("p"):
        text = clean_text(paragraph.get_text(" ", strip=True))
        if text and text.casefold() != "view full profile":
            title = text
            break
    return Faculty(
        id=faculty_id,
        full_name=full_name,
        profile_url=profile_url,
        division_ids=(division_id,),
        title=title,
    )


@dataclass(frozen=True)
class PrimaryFacultySourceAdapter:
    """Collect cards from one configured official primary-faculty source."""

    division: Division
    client: _DirectoryClient

    def collect_faculty(self) -> Sequence[Faculty]:
        response = self.client.get(self.division.faculty_url)
        soup = BeautifulSoup(response.text, "html.parser")
        if self.division.id in _PRIMARY_PANEL_DIVISIONS:
            container = soup.select_one("#faculty-panel-primary")
        elif self.division.id in _DEDICATED_PRIMARY_DIVISIONS:
            container = soup.select_one("main") or soup
        else:  # Defensive: every manifest division must name a supported layout.
            raise ValueError(f"No primary-faculty adapter for {self.division.id}")
        if container is None:
            raise ValueError(
                f"{self.division.name} primary-faculty markup was not found at {response.url}"
            )
        faculty = [
            item
            for card in container.select(".gls-card")
            if (item := _card_faculty(card, response.url, self.division.id)) is not None
        ]
        if not faculty:
            raise ValueError(
                f"{self.division.name} primary-faculty source contained no usable profile cards"
            )
        return faculty


class DoimDirectoryAdapter(DirectoryAdapter):
    """Route the core directory protocol through all configured DOIM sources."""

    def __init__(self, manifest: Mapping[str, object], client: _DirectoryClient | None = None) -> None:
        raw_divisions = manifest.get("divisions")
        if not isinstance(raw_divisions, list):
            raise TypeError("Directory manifest must contain a divisions list")
        self._divisions = tuple(
            _division_from_record(item) for item in raw_divisions if isinstance(item, Mapping)
        )
        configured_ids = {division.id for division in self._divisions}
        if configured_ids != _ADAPTER_DIVISION_IDS:
            missing = sorted(configured_ids - _ADAPTER_DIVISION_IDS)
            stale = sorted(_ADAPTER_DIVISION_IDS - configured_ids)
            raise ValueError(
                "Primary-faculty adapter registrations do not match the manifest "
                f"(missing={missing}, stale={stale})"
            )
        source_client = client or SourceClient()
        self.adapters = {
            division.id: PrimaryFacultySourceAdapter(division, source_client)
            for division in self._divisions
        }

    def collect_divisions(self) -> Sequence[Division]:
        return self._divisions

    def collect_faculty(self, division: Division) -> Sequence[Faculty]:
        return self.adapters[division.id].collect_faculty()


def build_directory_adapter(
    manifest: Mapping[str, object], client: _DirectoryClient | None = None
) -> DoimDirectoryAdapter:
    """Build the complete 12-source adapter set from the versioned manifest."""

    return DoimDirectoryAdapter(manifest, client)
