"""Static, credential-free coverage for the DOIM gcloud bootstrap contract."""

import subprocess
from pathlib import Path

SCRIPT = Path("infra/gcloud/bootstrap-doim.sh")


def test_bootstrap_script_is_valid_bash_and_dry_run_is_side_effect_free() -> None:
    syntax = subprocess.run(
        ["bash", "-n", str(SCRIPT)], capture_output=True, text=True, check=False
    )
    assert syntax.returncode == 0, syntax.stderr

    preview = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--project",
            "doim-explorer-test",
            "--github-owner",
            "UofUEpiBio",
            "--github-repo",
            "doim-explorer",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert preview.returncode == 0, preview.stderr
    assert "dry run: no gcloud calls will be made" in preview.stderr
    assert "gcloud services enable" in preview.stdout
    assert "gcloud run deploy doim-ask" in preview.stdout
    assert "gcloud artifacts repositories create doim" in preview.stdout
    assert "workload-identity-pool=doim-github" in preview.stdout


def test_bootstrap_keeps_the_placeholder_private_and_wif_repository_scoped() -> None:
    script = SCRIPT.read_text(encoding="utf-8")

    assert "--no-allow-unauthenticated" in script
    assert "--allow-unauthenticated" not in script.replace("--no-allow-unauthenticated", "")
    assert "assertion.repository == '${github_owner}/${github_repo}'" in script
    assert "attribute.repository/${github_owner}/${github_repo}" in script
