"""Release checks for the published DOIM documents and public endpoints.

The regular unit tests validate individual components. This module connects their release
boundaries: source health, document contracts, publication relations, the committed retrieval
index, the deployed Pages documents, and Cloud Run's public readiness/CORS responses.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

from research_explorer import rag

from doim_explorer.contracts import (
    DIRECTORY_DOCUMENT_TYPE,
    PUBLICATIONS_DOCUMENT_TYPE,
    validate_directory_document,
    validate_publication_documents,
)

DEFAULT_SITE_URL = "https://uofuepibio.github.io/doim-explorer/"
DEFAULT_ASK_URL = "https://doim-ask-d4mznpfqta-uc.a.run.app"
PUBLICATION_DETAILS_NAME = "publication-details.json"
PUBLICATIONS_NAME = "publications.json"
DIRECTORY_NAME = "directory.json"


class ReleaseCheckError(ValueError):
    """A release artifact or public endpoint is not safe to accept."""


@dataclass(frozen=True)
class ReleaseSummary:
    """Counts and provenance proven by a successful release check."""

    divisions: int
    faculty: int
    publications: int
    sources: int
    chunks: int = 0
    index_generated_at: str = ""


Documents = tuple[dict[str, Any], dict[str, Any], dict[str, Any]]
JsonLoader = Callable[[str], dict[str, Any]]
CorsChecker = Callable[[str, str], None]


def _require_mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReleaseCheckError(f"{name} must be a JSON object")
    return value


def _load_json_file(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseCheckError(f"could not read {path}: {exc}") from exc
    return dict(_require_mapping(value, str(path)))


def _load_documents(directory: Path) -> Documents:
    return (
        _load_json_file(directory / DIRECTORY_NAME),
        _load_json_file(directory / PUBLICATIONS_NAME),
        _load_json_file(directory / PUBLICATION_DETAILS_NAME),
    )


def validate_release_documents(documents: Documents) -> ReleaseSummary:
    """Validate source health, document schemas, and publication attribution."""

    directory, publications, details = documents
    validate_directory_document(directory)
    validate_publication_documents(publications, details)

    divisions = directory["divisions"]
    faculty = directory["faculty"]
    if directory.get("stats") != {"divisions": len(divisions), "faculty": len(faculty)}:
        raise ReleaseCheckError("directory stats do not match the published divisions and faculty")

    division_ids = {str(row["id"]) for row in divisions}
    health = directory.get("health")
    if not isinstance(health, list):
        raise ReleaseCheckError("directory health must be a list")
    health_by_division: dict[str, Mapping[str, Any]] = {}
    for row in health:
        item = _require_mapping(row, "directory health entry")
        division_id = item.get("division_id")
        if not isinstance(division_id, str) or not division_id:
            raise ReleaseCheckError("directory health entry has no division_id")
        if division_id in health_by_division:
            raise ReleaseCheckError(f"directory health repeats division {division_id}")
        health_by_division[division_id] = item
    if set(health_by_division) != division_ids:
        raise ReleaseCheckError("directory health does not cover exactly the published divisions")
    attention = sorted(
        division_id
        for division_id, row in health_by_division.items()
        if row.get("status") != "ok"
    )
    if attention:
        raise ReleaseCheckError(f"directory sources need attention: {', '.join(attention)}")

    faculty_ids = {str(row["id"]) for row in faculty}
    works = publications["works"]
    work_ids = [str(row["id"]) for row in works]
    if len(work_ids) != len(set(work_ids)):
        raise ReleaseCheckError("publication ids must be unique")
    for work in works:
        work_id = str(work["id"])
        work_faculty = set(work["faculty_ids"])
        work_divisions = set(work["division_ids"])
        if not work_faculty:
            raise ReleaseCheckError(f"publication {work_id} has no faculty identity")
        unknown_faculty = work_faculty - faculty_ids
        if unknown_faculty:
            raise ReleaseCheckError(
                f"publication {work_id} references unknown faculty {sorted(unknown_faculty)}"
            )
        if not work_divisions:
            raise ReleaseCheckError(f"publication {work_id} has no division identity")
        unknown_divisions = work_divisions - division_ids
        if unknown_divisions:
            raise ReleaseCheckError(
                f"publication {work_id} references unknown divisions {sorted(unknown_divisions)}"
            )
        attributed_divisions = {
            division_id
            for person in faculty
            if person["id"] in work_faculty
            for division_id in person["division_ids"]
        }
        if not work_divisions <= attributed_divisions:
            raise ReleaseCheckError(
                f"publication {work_id} divisions are not attributable to its faculty"
            )
    stats = publications.get("stats")
    if not isinstance(stats, Mapping) or stats.get("works") != len(works):
        raise ReleaseCheckError("publication stats do not match the published works")

    return ReleaseSummary(
        divisions=len(divisions),
        faculty=len(faculty),
        publications=len(works),
        sources=len(health),
    )


def validate_static_documents(canonical: Documents, static: Documents) -> ReleaseSummary:
    """Ensure Pages consumes exact copies of the validated generated artifacts."""

    summary = validate_release_documents(canonical)
    validate_release_documents(static)
    if static != canonical:
        raise ReleaseCheckError("static-site documents differ from the canonical generated artifacts")
    return summary


def validate_rag_index(index_dir: Path, documents: Documents, summary: ReleaseSummary) -> ReleaseSummary:
    """Load the committed index and bind its provenance to the validated documents."""

    try:
        index = rag.Index.load(index_dir)
    except (OSError, ValueError) as exc:
        raise ReleaseCheckError(f"could not load retrieval index at {index_dir}: {exc}") from exc
    manifest = _require_mapping(index.manifest, "retrieval manifest")
    sources = _require_mapping(manifest.get("sources"), "retrieval manifest sources")
    directory, publications, _details = documents
    expected_sources = {
        "application": "doim-explorer",
        "directory_document_type": DIRECTORY_DOCUMENT_TYPE,
        "directory_generated_at": directory["generated_at"],
        "publications_document_type": PUBLICATIONS_DOCUMENT_TYPE,
        "publications_generated_at": publications["generated_at"],
    }
    if dict(sources) != expected_sources:
        raise ReleaseCheckError("retrieval index provenance does not match the DOIM documents")
    chunks = manifest.get("chunks")
    vectors = manifest.get("vectors")
    if not isinstance(chunks, int) or chunks <= 0 or chunks != len(index.chunks):
        raise ReleaseCheckError("retrieval manifest chunk count does not match its loaded index")
    if vectors != chunks or len(index.vectors) != chunks:
        raise ReleaseCheckError("retrieval index does not have one vector for every chunk")
    generated_at = manifest.get("generated_at")
    if not isinstance(generated_at, str) or not generated_at:
        raise ReleaseCheckError("retrieval manifest has no generation timestamp")
    return replace(summary, chunks=chunks, index_generated_at=generated_at)


def validate_local_release(root: Path = Path(".")) -> tuple[Documents, ReleaseSummary]:
    """Validate the committed artifacts that will be published and baked into Cloud Run."""

    canonical = _load_documents(root / "data")
    static = _load_documents(root / "site" / "data")
    summary = validate_static_documents(canonical, static)
    return canonical, validate_rag_index(root / "data" / "rag", canonical, summary)


def _url(value: str, name: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ReleaseCheckError(f"{name} must be an absolute http(s) URL")
    return value.rstrip("/") + "/"


def load_public_json(url: str, *, timeout: int = 30) -> dict[str, Any]:
    """Load one public JSON document with a small, diagnostic-only request."""

    request = Request(url, headers={"User-Agent": "doim-explorer-release-check"})
    try:
        with urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise ReleaseCheckError(f"{url} returned HTTP {response.status}")
            payload = response.read().decode("utf-8")
    except (HTTPError, URLError, OSError) as exc:
        raise ReleaseCheckError(f"could not fetch {url}: {exc}") from exc
    try:
        return dict(_require_mapping(json.loads(payload), url))
    except json.JSONDecodeError as exc:
        raise ReleaseCheckError(f"{url} did not return JSON: {exc}") from exc


def check_public_cors(ask_url: str, origin: str, *, timeout: int = 30) -> None:
    """Prove that browsers served by Pages may send a POST without invoking a model."""

    request = Request(
        urljoin(_url(ask_url, "ask URL"), "ask"),
        method="OPTIONS",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "User-Agent": "doim-explorer-release-check",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            allowed_origin = response.headers.get("Access-Control-Allow-Origin")
            if response.status != 200 or allowed_origin != origin:
                raise ReleaseCheckError(
                    f"Cloud Run CORS preflight did not allow {origin} (got {allowed_origin!r})"
                )
    except (HTTPError, URLError, OSError) as exc:
        raise ReleaseCheckError(f"could not preflight {ask_url}: {exc}") from exc


def validate_public_release(
    canonical: Documents,
    expected: ReleaseSummary,
    *,
    site_url: str,
    ask_url: str,
    load_json: JsonLoader = load_public_json,
    check_cors: CorsChecker = check_public_cors,
) -> ReleaseSummary:
    """Verify that public Pages and Cloud Run serve this exact accepted release."""

    site_url = _url(site_url, "site URL")
    ask_url = _url(ask_url, "ask URL")
    public_documents = tuple(
        load_json(urljoin(site_url, f"data/{name}"))
        for name in (DIRECTORY_NAME, PUBLICATIONS_NAME, PUBLICATION_DETAILS_NAME)
    )
    public = validate_release_documents(public_documents)  # type: ignore[arg-type]
    if public_documents != canonical:
        raise ReleaseCheckError("public Pages documents are not the accepted generated artifacts")
    if public != replace(expected, chunks=0, index_generated_at=""):
        raise ReleaseCheckError("public Pages document counts do not match the accepted release")

    origin = f"{urlsplit(site_url).scheme}://{urlsplit(site_url).netloc}"
    check_cors(ask_url, origin)
    readiness = load_json(urljoin(ask_url, "readyz"))
    if (
        readiness.get("ready") is not True
        or readiness.get("chunks") != expected.chunks
        or readiness.get("indexGeneratedAt") != expected.index_generated_at
    ):
        raise ReleaseCheckError("Cloud Run readiness does not match the accepted retrieval index")
    return expected


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify the public DOIM release")
    parser.add_argument("--root", type=Path, default=Path("."), help="Repository root")
    parser.add_argument(
        "--site-url",
        default=os.getenv("DOIM_SITE_URL", DEFAULT_SITE_URL),
        help="Published GitHub Pages root (or DOIM_SITE_URL)",
    )
    parser.add_argument(
        "--ask-url",
        default=os.getenv("DOIM_ASK_URL", DEFAULT_ASK_URL),
        help="Public Cloud Run root (or DOIM_ASK_URL)",
    )
    parser.add_argument("--local-only", action="store_true", help="Skip public endpoint checks")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run local release validation and, unless disabled, public smoke checks."""

    args = parse_args(argv)
    try:
        documents, summary = validate_local_release(args.root)
        print(
            "Validated local release: "
            f"{summary.divisions} divisions, {summary.faculty} faculty, "
            f"{summary.publications} publications, {summary.chunks} retrieval chunks"
        )
        if not args.local_only:
            validate_public_release(
                documents, summary, site_url=args.site_url, ask_url=args.ask_url
            )
            print(f"Validated public Pages and Cloud Run: {args.site_url} and {args.ask_url}")
    except ReleaseCheckError as exc:
        print(f"Release verification failed: {exc}")
        return 1
    return 0
