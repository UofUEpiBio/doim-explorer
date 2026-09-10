from pathlib import Path


def test_weekly_doim_refresh_opens_a_guarded_pull_request() -> None:
    workflow = Path(".github/workflows/refresh-doim-directory.yml").read_text(encoding="utf-8")

    assert 'cron: "37 7 * * 1"' in workflow
    assert "doim-directory --collect --strict" in workflow
    assert "--max-drop-ratio 0.25" in workflow
    assert "peter-evans/create-pull-request@v7" in workflow
    assert "automation/doim-directory-refresh" in workflow
    assert "contents: write" in workflow
    assert "pull-requests: write" in workflow
