"""Testes do leitor de artefatos do dbt: classificação e agregação dos resultados."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from dbt_lab.observability.artifacts import (
    ArtifactError,
    build_report,
    build_report_from_artifacts,
    classify_status,
    to_timezone,
)
from dbt_lab.observability.models import RunStatus, TestCategory


class TestClassifyStatus:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            ("pass", TestCategory.PASSED),
            ("success", TestCategory.PASSED),
            ("no-op", TestCategory.PASSED),
            # `warn` é o caso crítico: com severity='warn' o dbt marca como warn
            # um teste que ENCONTROU dado inválido. Tratar como sucesso esconderia
            # o problema do relatório.
            ("warn", TestCategory.FAILED),
            ("fail", TestCategory.FAILED),
            ("error", TestCategory.ERRORED),
            ("runtime error", TestCategory.ERRORED),
            ("skipped", TestCategory.SKIPPED),
            ("WARN", TestCategory.FAILED),
            ("  pass  ", TestCategory.PASSED),
        ],
    )
    def test_mapeia_status_do_dbt(self, status: str, expected: TestCategory) -> None:
        assert classify_status(status) is expected

    @pytest.mark.parametrize("status", [None, "", "status-inexistente"])
    def test_status_desconhecido_nao_e_aprovado(self, status: str | None) -> None:
        assert classify_status(status) is TestCategory.ERRORED


class TestBuildReport:
    def _report(
        self,
        run_results: Mapping[str, Any],
        manifest: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        options: dict[str, Any] = {
            "run_results": run_results,
            "manifest": manifest,
            "run_results_path": "target/run_results.json",
            "channel_label": "Base RH",
            "include_samples": False,
        }
        options.update(kwargs)
        return build_report(**options)

    def test_todos_aprovados(self, all_pass_results: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
        report = self._report(all_pass_results, manifest)

        assert report.status is RunStatus.SUCCESS
        assert (report.total, report.passed, report.failed, report.errored) == (3, 3, 0, 0)
        assert report.executed == 3
        assert report.pass_rate == 100.0

    def test_falhas_reais_do_projeto(
        self, failures_results: Mapping[str, Any], manifest: Mapping[str, Any]
    ) -> None:
        report = self._report(failures_results, manifest)

        assert report.status is RunStatus.QUALITY_ISSUES
        # 3 testes `warn` (severidade warn) com 2, 3 e 2 reprovações.
        assert (report.total, report.passed, report.failed, report.errored) == (3, 0, 3, 0)
        assert report.pass_rate == 0.0
        assert {outcome.test_name: outcome.failures for outcome in report.problems} == {
            "rh_desligados": 2,
            "rh_intervalo_status": 3,
            "rh_sem_registro": 2,
        }
        assert all(outcome.dbt_status == "warn" for outcome in report.problems)

    def test_modelos_do_build_nao_sao_contados_como_testes(
        self, failures_results: Mapping[str, Any], manifest: Mapping[str, Any]
    ) -> None:
        report = self._report(failures_results, manifest)

        assert {outcome.unique_id for outcome in report.outcomes} == {
            "test.dbt_lab.rh_desligados",
            "test.dbt_lab.rh_intervalo_status",
            "test.dbt_lab.rh_sem_registro",
        }

    def test_erro_de_execucao_e_separado_de_falha_de_qualidade(
        self, error_results: Mapping[str, Any], manifest: Mapping[str, Any]
    ) -> None:
        report = self._report(error_results, manifest)

        assert report.status is RunStatus.EXECUTION_ERROR
        assert (report.passed, report.failed, report.errored, report.skipped) == (1, 1, 1, 1)
        assert [outcome.test_name for outcome in report.errors] == ["rh_intervalo_status"]
        assert [outcome.test_name for outcome in report.problems] == ["rh_sem_registro"]
        assert report.errors[0].failures is None
        assert "invalid input syntax" in (report.errors[0].message or "")
        # 4 testes, mas apenas 3 foram tentados: o ignorado fica fora da taxa.
        assert report.executed == 3
        assert report.pass_rate == pytest.approx(33.3)

    def test_somente_erro_de_execucao(self, error_results: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
        results = {**error_results, "results": [r for r in error_results["results"] if r["status"] == "error"]}
        report = self._report(results, manifest)

        assert report.status is RunStatus.EXECUTION_ERROR
        assert (report.failed, report.errored) == (0, 1)

    def test_execucao_vazia_nao_valida_qualidade(
        self, empty_results: Mapping[str, Any], manifest: Mapping[str, Any]
    ) -> None:
        report = self._report(empty_results, manifest)

        assert report.status is RunStatus.NO_TESTS
        assert report.executed == 0
        assert report.pass_rate is None

    def test_run_sem_testes_apos_filtro_de_selecao(
        self, models_only_results: Mapping[str, Any], manifest: Mapping[str, Any]
    ) -> None:
        report = self._report(models_only_results, manifest)

        assert report.status is RunStatus.NO_TESTS
        assert report.total == 0

    def test_todos_ignorados_tambem_e_ausencia_de_validacao(
        self, error_results: Mapping[str, Any], manifest: Mapping[str, Any]
    ) -> None:
        results = {**error_results, "results": [r for r in error_results["results"] if r["status"] == "skipped"]}
        report = self._report(results, manifest)

        assert report.status is RunStatus.NO_TESTS
        assert report.skipped == 1

    def test_metadados_de_negocio_vem_do_manifest(
        self, failures_results: Mapping[str, Any], manifest: Mapping[str, Any]
    ) -> None:
        report = self._report(failures_results, manifest)
        contexto = {o.test_name: o.context for o in report.problems}["rh_desligados"]

        assert contexto.title == "Colaboradores desligados sem data de desligamento"
        assert contexto.audience == "RH"
        assert contexto.described is True
        assert contexto.business_rule.startswith("Todo colaborador com status DESLIGADO")
        assert contexto.sample_columns == ("Nome", "CPF", "Status", "Data_Desligamento")

    def test_teste_sem_meta_cai_no_generico(
        self, error_results: Mapping[str, Any], manifest: Mapping[str, Any]
    ) -> None:
        results = {**error_results, "results": [r for r in error_results["results"] if "cpf_duplicado" in r["unique_id"]]}
        report = self._report(results, manifest)
        contexto = report.outcomes[0].context

        assert contexto.described is False
        assert contexto.title == "Rh cpf duplicado"
        assert contexto.business_rule == ""

    def test_modelo_e_severidade_vem_do_manifest(
        self, failures_results: Mapping[str, Any], manifest: Mapping[str, Any]
    ) -> None:
        report = self._report(failures_results, manifest)

        assert all(o.model_name == "rh_trusted" for o in report.outcomes)
        assert all(o.severity == "warn" for o in report.outcomes)
        assert all(o.audit_relation for o in report.problems)

    def test_sem_store_failures_nao_ha_relacao_de_amostras(
        self, error_results: Mapping[str, Any], manifest: Mapping[str, Any]
    ) -> None:
        results = {**error_results, "results": [r for r in error_results["results"] if "cpf_duplicado" in r["unique_id"]]}
        report = self._report(results, manifest)

        assert report.outcomes[0].audit_relation is None

    def test_manifest_ausente_geram_aviso_sem_quebrar(
        self, failures_results: Mapping[str, Any]
    ) -> None:
        report = self._report(failures_results, None)

        assert report.status is RunStatus.QUALITY_ISSUES
        assert any("manifest.json ausente" in warning for warning in report.warnings)
        assert all(o.model_name is None for o in report.outcomes)

    def test_resultado_malformado_e_ignorado(self, all_pass_results: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
        results = {**all_pass_results, "results": ["lixo", *all_pass_results["results"]]}
        report = self._report(results, manifest)

        assert report.total == 3

    def test_results_ausente_e_erro_explicito(self) -> None:
        with pytest.raises(ArtifactError, match="results"):
            build_report(
                run_results={"metadata": {}},
                manifest=None,
                run_results_path="target/run_results.json",
                channel_label="Base RH",
            )

    def test_timestamp_ausente_usa_agora_e_avisa(self, all_pass_results: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
        results = {**all_pass_results, "metadata": {"dbt_version": "1.11.14"}}
        report = self._report(results, manifest)

        assert any("timestamp" in warning for warning in report.warnings)
        assert report.dbt_version == "1.11.14"

    def test_comando_e_versao_vem_dos_artefatos(
        self, all_pass_results: Mapping[str, Any], manifest: Mapping[str, Any]
    ) -> None:
        report = self._report(all_pass_results, manifest)

        assert report.invocation_command == "dbt test -s tag:rh"
        assert report.dbt_version == "1.11.14"
        assert report.run_results_path == "target/run_results.json"

    def test_horario_convertido_para_o_fuso_do_relatorio(
        self, all_pass_results: Mapping[str, Any], manifest: Mapping[str, Any]
    ) -> None:
        report = self._report(all_pass_results, manifest, timezone_name="America/Sao_Paulo")

        assert report.generated_at.strftime("%d/%m/%Y %H:%M") == "21/09/2026 09:00"

    def test_fuso_invalido_cai_para_utc(self, all_pass_results: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
        report = self._report(all_pass_results, manifest, timezone_name="Marte/Base")

        assert report.generated_at.utcoffset() is not None

    def test_to_timezone_preserva_o_momento(self) -> None:
        from datetime import datetime, timezone

        momento = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)

        assert to_timezone(momento, "America/Sao_Paulo").hour == 9
        assert to_timezone(momento, "Marte/Base") == momento


class TestBuildReportFromArtifacts:
    def test_lê_run_results_e_manifest_do_diretorio(
        self,
        target_dir: Path,
        failures_results: Mapping[str, Any],
        manifest: Mapping[str, Any],
        write_run_results: Callable[[Path, Mapping[str, Any]], Path],
    ) -> None:
        write_run_results(target_dir, failures_results)

        report = build_report_from_artifacts(target_dir, include_samples=False)

        assert report.status is RunStatus.QUALITY_ISSUES
        assert report.problems[0].context.described is True

    def test_artefato_ausente_explica_como_gerar(
        self, target_dir: Path, write_run_results: Callable[[Path, Mapping[str, Any]], Path]
    ) -> None:
        with pytest.raises(ArtifactError, match="dbt build"):
            build_report_from_artifacts(target_dir)

    def test_json_invalido(self, target_dir: Path, write_run_results: Callable[[Path, Mapping[str, Any]], Path]) -> None:
        (target_dir / "run_results.json").write_text("{ nao é json", encoding="utf-8")

        with pytest.raises(ArtifactError, match="Não foi possível ler"):
            build_report_from_artifacts(target_dir)

    def test_results_com_formato_inesperado(
        self,
        target_dir: Path,
        invalid_results: Mapping[str, Any],
        write_run_results: Callable[[Path, Mapping[str, Any]], Path],
    ) -> None:
        write_run_results(target_dir, invalid_results)

        with pytest.raises(ArtifactError, match="results"):
            build_report_from_artifacts(target_dir)

    def test_run_results_de_nome_diferente(
        self,
        target_dir: Path,
        all_pass_results: Mapping[str, Any],
        write_run_results: Callable[[Path, Mapping[str, Any]], Path],
    ) -> None:
        caminho = write_run_results(target_dir, all_pass_results, name="run_results_anterior.json")

        report = build_report_from_artifacts(target_dir, run_results_path=caminho, include_samples=False)

        assert report.status is RunStatus.SUCCESS
        assert report.run_results_path == str(caminho)
