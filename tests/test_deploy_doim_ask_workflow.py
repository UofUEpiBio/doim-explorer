"""Static coverage for the credential-free DOIM Ask deployment workflow."""

from pathlib import Path

WORKFLOW = Path(".github/workflows/deploy-doim-ask.yml")


def test_deployment_uses_wif_variables_and_only_the_salt_secret() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "id-token: write" in workflow
    assert "google-github-actions/auth@v3" in workflow
    assert "workload_identity_provider: ${{ vars.WIF_PROVIDER }}" in workflow
    assert "service_account: ${{ vars.WIF_SERVICE_ACCOUNT }}" in workflow
    assert "secrets.WIF_" not in workflow
    assert "IP_SALT=${{ secrets.IP_SALT }}" in workflow
    assert "gha-creds-*.json" in Path(".dockerignore").read_text(encoding="utf-8")


def test_deployment_is_doim_named_and_rejects_unsafe_index_inputs() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "doim-ask-deploy" in workflow
    assert "doim/doim-ask:${{ github.sha }}" in workflow
    assert "gcloud run deploy doim-ask" in workflow
    assert "--allow-unauthenticated" in workflow
    assert "not built from DOIM contracts" in workflow
    assert "without --no-embed" in workflow
    assert "apt-get install --yes --no-install-recommends ca-certificates git" in dockerfile
