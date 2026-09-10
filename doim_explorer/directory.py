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
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import parse_qs, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag
from requests import RequestException
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
DEFAULT_PUBMED_AFFILIATIONS = (
    "University of Utah",
    "University of Utah Health",
    "University of Utah School of Medicine",
)
_PAGE_IDENTIFIER = re.compile(r"\[(u\d+)\]", re.IGNORECASE)
_ORCID = re.compile(r"(?:https?://orcid\.org/)?(\d{4}-\d{4}-\d{4}-\d{3}[\dX])", re.IGNORECASE)
_COLLECTION_ERRORS = (RequestException, ValueError, OSError, RuntimeError, AttributeError, KeyError)


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


def build_pubmed_query(
    faculty: Faculty, affiliations: Sequence[str] = DEFAULT_PUBMED_AFFILIATIONS
) -> str:
    """Build a conservative PubMed author query scoped to University of Utah."""

    name = faculty.full_name.split(",", 1)[0].strip()
    words = [word for word in re.findall(r"[\w'-]+", name) if word]
    if not words:
        return ""
    surname = words[-1]
    initials = "".join(word[0] for word in words[:-1]).upper()
    author = f"{surname} {initials}".strip()
    affiliation_terms = [
        f'"{term.strip()}"[Affiliation]' for term in affiliations if term.strip()
    ]
    if not affiliation_terms:
        return f'"{author}"[Author]'
    return f'"{author}"[Author] AND ({" OR ".join(affiliation_terms)})'


def apply_pubmed_queries(
    faculty: Sequence[Faculty], manifest: Mapping[str, object]
) -> list[Faculty]:
    """Apply exact configured overrides, generating affiliation queries otherwise."""

    config = manifest.get("pubmed", {})
    config = config if isinstance(config, Mapping) else {}
    affiliations = config.get("affiliations", DEFAULT_PUBMED_AFFILIATIONS)
    if not isinstance(affiliations, list) or not affiliations:
        affiliations = DEFAULT_PUBMED_AFFILIATIONS
    overrides = config.get("overrides", {})
    overrides = overrides if isinstance(overrides, Mapping) else {}
    result: list[Faculty] = []
    for member in faculty:
        override = (
            member.pubmed_query
            or str(overrides.get(member.id, "")).strip()
            or str(overrides.get(member.profile_url, "")).strip()
            or str(overrides.get(member.full_name, "")).strip()
        )
        query = override or build_pubmed_query(member, affiliations)
        result.append(member if query == member.pubmed_query else Faculty(**{**member.__dict__, "pubmed_query": query}))
    return result


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


def _profile_identifier(soup: BeautifulSoup, fallback: str) -> str:
    for script in soup.find_all("script"):
        match = _PAGE_IDENTIFIER.search(script.get_text(" ", strip=True))
        if match:
            return match.group(1).lower()
    return fallback


def _heading_section_text(soup: BeautifulSoup, phrase: str, limit: int = 2200) -> str:
    heading = next(
        (
            item
            for item in soup.find_all(["h2", "h3"])
            if phrase in clean_text(item.get_text(" ", strip=True)).casefold()
        ),
        None,
    )
    if heading is None:
        return ""
    container = heading.find_parent("section") or heading.parent
    if container is None:
        return ""
    text = clean_text(container.get_text(" ", strip=True), limit)
    return clean_text(text.replace(clean_text(heading.get_text(" ", strip=True)), "", 1), limit)


def _profile_bio(soup: BeautifulSoup) -> str:
    bio = _heading_section_text(soup, "biograph")
    if bio:
        return bio
    education_heading = next(
        (
            item
            for item in soup.find_all(["h2", "h3"])
            if "education history" in clean_text(item.get_text(" ", strip=True)).casefold()
        ),
        None,
    )
    if education_heading is not None:
        education_section = education_heading.find_parent("section")
        for previous_section in education_section.find_all_previous("section") if education_section else ():
            candidate = previous_section.select_one(".gls-width-expand")
            text = clean_text(candidate.get_text(" ", strip=True) if candidate else "", 3000)
            if text:
                return text
    main = soup.find("main") or soup
    candidate = main.select_one(".gls-width-expand")
    return clean_text(candidate.get_text(" ", strip=True) if candidate else "", 3000)


@dataclass
class PublicFacultyProfileAdapter:
    """Enrich directory cards from the linked public University profile page."""

    client: _DirectoryClient

    def __post_init__(self) -> None:
        self._cache: dict[str, Faculty] = {}

    def collect_profile(self, faculty: Faculty) -> Faculty:
        cached = self._cache.get(faculty.id)
        if cached is not None:
            return Faculty(**{**cached.__dict__, "division_ids": faculty.division_ids})
        response = self.client.get(faculty.profile_url)
        soup = BeautifulSoup(response.text, "html.parser")
        stable_id = _profile_identifier(soup, faculty.id)
        for element in soup(["script", "style", "noscript", "svg"]):
            element.decompose()
        if stable_id != faculty.id:
            stable_id = faculty.id
        name_heading = soup.select_one("main h1") or soup.find("h1")
        full_name = clean_text(name_heading.get_text(" ", strip=True)) if name_heading else faculty.full_name
        if not full_name:
            full_name = faculty.full_name
        orcid_id = ""
        for anchor in soup.select("a[href*='orcid.org']"):
            match = _ORCID.search(str(anchor.get("href", "")))
            if match:
                orcid_id = match.group(1).upper()
                break
        enriched = Faculty(
            **{
                **faculty.__dict__,
                "id": stable_id,
                "full_name": full_name,
                "bio": _profile_bio(soup),
                "academic_information": _heading_section_text(soup, "academic information"),
                "orcid_id": orcid_id,
            }
        )
        self._cache[faculty.id] = enriched
        return enriched


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def collect_directory_snapshot(
    manifest: Mapping[str, object],
    client: _DirectoryClient | None = None,
    *,
    checked_at: str | None = None,
) -> dict[str, object]:
    """Collect cards and public profiles, retaining a health row per division."""

    from doim_explorer.contracts import build_directory_document

    adapter = build_directory_adapter(manifest, client)
    profile_adapter = PublicFacultyProfileAdapter(adapter.adapters[next(iter(adapter.adapters))].client)
    members: dict[str, Faculty] = {}
    health: list[dict[str, object]] = []
    timestamp = checked_at or _now()
    for division in adapter.collect_divisions():
        try:
            cards = list(adapter.collect_faculty(division))
            errors: list[str] = []
            for card in cards:
                try:
                    enriched = apply_pubmed_queries(
                        [profile_adapter.collect_profile(card)], manifest
                    )[0]
                except PermissionError as exc:
                    errors.append(f"{card.id}: blocked ({exc})")
                    enriched = apply_pubmed_queries([card], manifest)[0]
                except _COLLECTION_ERRORS as exc:  # A single profile must not hide its division.
                    errors.append(f"{card.id}: {exc}")
                    enriched = apply_pubmed_queries([card], manifest)[0]
                existing = members.get(enriched.id)
                divisions = tuple(
                    dict.fromkeys((*(existing.division_ids if existing else ()), *enriched.division_ids))
                )
                members[enriched.id] = Faculty(**{**enriched.__dict__, "division_ids": divisions})
            status = "partial" if errors else "ok"
            message = "; ".join(errors) if errors else f"Collected {len(cards)} primary profiles"
            health.append(
                {
                    "division_id": division.id,
                    "source": division.faculty_url,
                    "source_label": f"{division.name} primary faculty",
                    "status": status,
                    "message": message,
                    "faculty_count": len(cards),
                    "checked_at": timestamp,
                }
            )
        except PermissionError as exc:
            health.append(
                {
                    "division_id": division.id,
                    "source": division.faculty_url,
                    "source_label": f"{division.name} primary faculty",
                    "status": "blocked",
                    "message": str(exc),
                    "faculty_count": 0,
                    "checked_at": timestamp,
                }
            )
        except _COLLECTION_ERRORS as exc:
            health.append(
                {
                    "division_id": division.id,
                    "source": division.faculty_url,
                    "source_label": f"{division.name} primary faculty",
                    "status": "error",
                    "message": str(exc),
                    "faculty_count": 0,
                    "checked_at": timestamp,
                }
            )
    return build_directory_document(manifest, [item.__dict__ for item in members.values()], health, generated_at=timestamp)


class RefreshGuardError(ValueError):
    """Raised when a refresh would publish a suspiciously incomplete directory."""


def assert_safe_directory_refresh(
    previous: Mapping[str, object] | None,
    current: Mapping[str, object],
    *,
    max_drop_ratio: float = 0.25,
    min_faculty: int = 1,
) -> None:
    """Reject empty/abruptly smaller refreshes before a pull request is opened."""

    if not 0 <= max_drop_ratio <= 1:
        raise ValueError("max_drop_ratio must be between 0 and 1")
    current_stats = current.get("stats", {})
    current_count = int(current_stats.get("faculty", len(current.get("faculty", [])))) if isinstance(current_stats, Mapping) else 0
    if current_count < min_faculty:
        raise RefreshGuardError(f"faculty count {current_count} is below minimum {min_faculty}")
    if not previous:
        return
    previous_stats = previous.get("stats", {})
    previous_count = int(previous_stats.get("faculty", len(previous.get("faculty", [])))) if isinstance(previous_stats, Mapping) else 0
    if previous_count and current_count < previous_count * (1 - max_drop_ratio):
        raise RefreshGuardError(
            f"faculty count dropped from {previous_count} to {current_count}, exceeding {max_drop_ratio:.0%} guard"
        )
    previous_divisions = {
        str(item.get("id")): 0
        for item in previous.get("divisions", [])
        if isinstance(item, Mapping)
    }
    current_divisions = dict(previous_divisions)
    for item in current.get("divisions", []):
        if isinstance(item, Mapping):
            current_divisions[str(item.get("id"))] = 0
    for member in previous.get("faculty", []):
        if isinstance(member, Mapping):
            for division_id in member.get("division_ids", []):
                if division_id in previous_divisions:
                    previous_divisions[division_id] += 1
    for member in current.get("faculty", []):
        if isinstance(member, Mapping):
            for division_id in member.get("division_ids", []):
                if division_id in current_divisions:
                    current_divisions[division_id] += 1
    for division_id, old_count in previous_divisions.items():
        new_count = current_divisions.get(division_id, 0)
        if old_count and new_count < old_count * (1 - max_drop_ratio):
            raise RefreshGuardError(
                f"{division_id} faculty count dropped from {old_count} to {new_count}, "
                f"exceeding {max_drop_ratio:.0%} guard"
            )


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
