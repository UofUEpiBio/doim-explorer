"""Static coverage for the active DOIM GitHub Actions workflows."""

from pathlib import Path

WORKFLOWS = Path(".github/workflows")


def _workflow(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def test_ci_uses_a_locked_environment_for_pull_requests_and_main() -> None:
    workflow = _workflow("ci.yml")

    assert "pull_request:" in workflow
    assert "branches: [main]" in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "uv sync --locked --all-extras --dev" in workflow
    assert "uv run --locked ruff check doim_explorer server tests" in workflow
    assert "uv run --locked pytest" in workflow


def test_pages_publishes_only_reviewed_main_content() -> None:
    workflow = _workflow("deploy-pages.yml")

    assert "branches: [main]" in workflow
    assert '      - "site/**"' in workflow
    assert "workflow_run:" not in workflow
    assert "actions/configure-pages@v5" in workflow
    assert "actions/upload-pages-artifact@v4" in workflow
    assert "actions/deploy-pages@v4" in workflow


def test_refresh_is_guarded_and_proposes_a_reviewable_change() -> None:
    workflow = _workflow("refresh-doim-directory.yml")

    assert "cron: \"37 7 * * 1\"" in workflow
    assert "workflow_dispatch:" in workflow
    assert "doim-directory --collect --strict" in workflow
    assert "--max-drop-ratio 0.25 --min-faculty 1" in workflow
    assert "peter-evans/create-pull-request@v7" in workflow
    assert "automation/doim-directory-refresh" in workflow
    assert "pull-requests: write" in workflow


def test_auth_check_uses_wif_variables_and_only_doim_resources() -> None:
    workflow = _workflow("verify-doim-auth.yml")

    assert "workflow_dispatch:" in workflow
    assert "id-token: write" in workflow
    assert "google-github-actions/auth@v3" in workflow
    assert "workload_identity_provider: ${{ vars.WIF_PROVIDER }}" in workflow
    assert "service_account: ${{ vars.WIF_SERVICE_ACCOUNT }}" in workflow
    assert "secrets.WIF_" not in workflow
    assert "artifacts repositories describe doim" in workflow
    assert "run services describe doim-ask" in workflow
    assert "insightnet" not in workflow


def test_public_release_check_uses_no_cloud_credentials_or_secrets() -> None:
    workflow = _workflow("verify-doim-release.yml")

    assert "workflow_dispatch:" in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "id-token: write" not in workflow
    assert "${{ secrets." not in workflow
    assert "uv sync --locked --all-extras --dev" in workflow
    assert "uv run --locked doim-release-check" in workflow
