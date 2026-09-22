from pathlib import Path


def test_scheduled_and_targeted_refreshes_open_reviewable_data_pull_requests() -> None:
    workflow = Path(".github/workflows/refresh-doim-directory.yml").read_text(encoding="utf-8")
    targeted = Path(".github/workflows/refresh-doim-faculty.yml").read_text(encoding="utf-8")

    assert 'cron: "37 7 * * 1"' in workflow
    assert 'cron: "37 7 1 1,3,5,7,9,11 *"' in workflow
    assert "doim-refresh ${{ steps.mode.outputs.args }}" in workflow
    assert "--roster-only" in workflow
    assert "--all-profiles" in workflow
    assert "google-github-actions/auth@v3" in workflow
    assert "RESEARCH_EXPLORER_CONTACT_EMAIL" in workflow
    assert "peter-evans/create-pull-request@v7" in workflow
    assert "automation/doim-directory-refresh" in workflow
    assert "contents: write" in workflow
    assert "pull-requests: write" in workflow
    assert "faculty_ids:" in targeted
    assert 'doim-refresh --faculty-ids "$FACULTY_IDS"' in targeted
    assert "automation/doim-faculty-refresh" in targeted
    assert "data/rag/**" in targeted
