"""Fixtures compartilhadas dos testes do relatório de Qualidade de Dados."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from dbt_lab.observability import cli

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def manifest() -> Mapping[str, Any]:
    return load_fixture("manifest.json")


@pytest.fixture(scope="session")
def all_pass_results() -> Mapping[str, Any]:
    return load_fixture("run_results_all_pass.json")


@pytest.fixture(scope="session")
def failures_results() -> Mapping[str, Any]:
    """Execução real de `dbt build -s tag:rh`: 3 testes `warn` com 2/3/2 falhas."""
    return load_fixture("run_results_with_failures.json")


@pytest.fixture(scope="session")
def error_results() -> Mapping[str, Any]:
    return load_fixture("run_results_with_error.json")


@pytest.fixture(scope="session")
def empty_results() -> Mapping[str, Any]:
    return load_fixture("run_results_empty.json")


@pytest.fixture(scope="session")
def models_only_results() -> Mapping[str, Any]:
    return load_fixture("run_results_models_only.json")


@pytest.fixture(scope="session")
def invalid_results() -> Mapping[str, Any]:
    return load_fixture("run_results_invalid.json")


@pytest.fixture
def target_dir(tmp_path: Path, manifest: Mapping[str, Any]) -> Path:
    """Diretório de artefatos com run_results.json + manifest.json."""
    directory = tmp_path / "target"
    directory.mkdir()
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return directory


@pytest.fixture
def write_run_results():
    """Grava um run_results.json sintético no diretório de artefatos."""

    def _write(target_dir: Path, payload: Mapping[str, Any], name: str = "run_results.json") -> Path:
        path = target_dir / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    return _write


@pytest.fixture(autouse=True)
def _ambiente_isolado(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Impede que o `.env` local (ou o shell) vaze configuração para os testes.

    Sem isso, `uv run pytest` passaria a enviar de verdade para o Slack de
    quem estiver desenvolvendo, e falharia em quem não tiver `.env`.
    """
    for variavel in ("SLACK_WEBHOOK_URL", "DQ_CHANNEL_LABEL", "DQ_AUDIENCE", "DQ_SAMPLE_LIMIT"):
        monkeypatch.delenv(variavel, raising=False)
    monkeypatch.setattr(cli, "ENV_FILE", str(tmp_path / "inexistente.env"))
