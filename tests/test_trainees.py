from __future__ import annotations

import json

import pytest

openpyxl = pytest.importorskip("openpyxl")

from research_explorer.works import WorksResult

from doim_explorer.trainees import build_trainee_pubmed_query, trainee_id
from doim_explorer.update import trainee_publications_main


def _roster(path) -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Last Name", "First Name", "Degree", "Program", "E-Mail Address"])
    sheet.append(["Doe", "Jane Ann", "MD", "Internal Medicine", "Jane.Doe@example.org"])
    sheet.append(["Van Hook", "Reed", "MD", "Cardiovascular Disease", "Sam.Van.Hook@example.org"])
    sheet.append(["Roe", "Rex", "DO", "Internal Medicine", "Rex.Roe@example.org"])
    workbook.save(path)


def _directory(path) -> None:
    path.write_text(
        json.dumps(
            {
                "settings": {"max_publications_per_faculty": 100, "abstract_max_chars": 1500},
                "divisions": [],
                "faculty": [{"id": "u1", "full_name": "Rex T. Roe, MD"}],
            }
        )
    )


def test_trainee_queries_search_the_full_first_name_with_any_middle_name() -> None:
    query = build_trainee_pubmed_query("Van Hook", "Reed", "Sam.Van.Hook@x.org", ["Utah"])
    assert query == (
        '("Van Hook, Reed"[Full Author Name] OR "Van Hook, Reed *"[Full Author Name] OR '
        '"Van Hook, Sam"[Full Author Name] OR "Van Hook, Sam *"[Full Author Name]) '
        'AND ("Utah"[Affiliation])'
    )
    assert build_trainee_pubmed_query("Doé", "Jane Ann", "Jane.Doe@x.org", ["Utah"]) == (
        '("Doe, Jane"[Full Author Name] OR "Doe, Jane *"[Full Author Name]) '
        'AND ("Utah"[Affiliation])'
    )


def test_trainee_publications_are_collected_and_tagged_end_to_end(tmp_path, monkeypatch) -> None:
    queries = []

    def fake_pubmed(_client, researcher, _limits):
        queries.append(researcher["pubmed_query"])
        if "Doe" in researcher["pubmed_query"]:
            return WorksResult(
                works=[
                    {"title": "Shared paper", "pmid": "1", "url": "https://x/1", "year": 2025},
                    {"title": "Solo paper", "pmid": "2", "url": "https://x/2", "year": 2024},
                ]
            )
        if "Roe" in researcher["pubmed_query"]:
            return WorksResult(
                works=[{"title": "Shared paper", "pmid": "1", "url": "https://x/1", "year": 2025}]
            )
        return WorksResult(message="PubMed returned no records for this query")

    monkeypatch.setattr("research_explorer.works.collect_pubmed", fake_pubmed)
    monkeypatch.setattr(
        "research_explorer.works.WORK_COLLECTORS", (("pubmed", "PubMed", fake_pubmed),)
    )
    monkeypatch.setattr("research_explorer.works.enrich_works", lambda *_args: {})

    roster, directory = tmp_path / "roster.xlsx", tmp_path / "directory.json"
    _roster(roster)
    _directory(directory)
    output = tmp_path / "trainee-publications.json"
    status = trainee_publications_main(
        [str(roster), "--directory", str(directory), "--output", str(output), "--strict"]
    )

    assert status == 0
    assert len(queries) == 3
    assert all('"University of Utah"[Affiliation]' in query for query in queries)
    index = json.loads(output.read_text())
    details = json.loads((tmp_path / "trainee-publication-details.json").read_text())
    assert index["document_type"] == "doim-trainee-publications"
    assert details["document_type"] == "doim-trainee-publication-details"
    by_title = {work["title"]: work for work in index["works"]}
    doe, roe = trainee_id("Doe", "Jane Ann"), trainee_id("Roe", "Rex")
    assert doe == "t-doe-jane-ann"
    assert sorted(by_title["Shared paper"]["trainee_ids"]) == [doe, roe]
    assert by_title["Shared paper"]["program_ids"] == ["internal-medicine"]
    assert by_title["Solo paper"]["trainee_ids"] == [doe]
    assert index["stats"]["trainees_with_publications"] == 2
    # Only trainees with publications are named; the rest are counted per program.
    trainees = {item["id"]: item for item in index["trainees"]}
    assert set(trainees) == {doe, roe}
    assert trainees[doe]["works"] == 2 and trainees[doe]["faculty_id"] is None
    assert trainees[roe]["faculty_id"] == "u1"  # also listed as faculty: the same person
    assert {row["faculty_id"] for row in index["health"]} == {doe, roe}
    assert index["summary"]["by_program"] == [
        {"program": "Internal Medicine", "roster": 2, "with_publications": 2},
        {"program": "Cardiovascular Disease", "roster": 1, "with_publications": 0},
    ]
