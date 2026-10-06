"""Testes da mensagem do Slack: conteúdo, formatação e limites da API."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import replace
from typing import Any

import pytest

from dbt_lab.observability.artifacts import build_report
from dbt_lab.observability.blocks import (
    ALLOWED_BLOCK_TYPES,
    HEADER_MAX_CHARS,
    MAX_SAMPLE_COLUMNS,
    SECTION_MAX_CHARS,
    build_blocks,
    build_fallback_text,
    build_payload,
    mask_cpf,
    truncate,
)
from dbt_lab.observability.models import RunStatus


def build(
    run_results: Mapping[str, Any],
    manifest: Mapping[str, Any] | None,
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


def texts(blocks: Iterable[Mapping[str, Any]]) -> str:
    """Todo o texto visível da mensagem, em ordem."""
    collected: list[str] = []
    for block in blocks:
        if "text" in block:
            collected.append(block["text"].get("text", ""))
        for element in block.get("elements", []):
            collected.append(element.get("text", ""))
    return "\n".join(collected)


# Amostras sintéticas com o mesmo formato das tabelas dbt_test__audit, para que a
# renderização seja testada sem depender do banco local.
SAMPLES = {
    "rh_desligados": (
        {"Nome": "Camila Mendes", "CPF": "852.963.741-11", "Status": "DESLIGADO", "Data_Desligamento": None},
        {"Nome": "Vanessa Pereira", "CPF": "654.321.987-19", "Status": "DESLIGADO", "Data_Desligamento": None},
    ),
    "rh_intervalo_status": (
        {
            "Nome": "Thiago Nunes",
            "CPF": "963.741.852-12",
            "Data_Inicio_Afastamento": "2026-03-05",
            "Data_Fim_Afastamento": "2026-02-05",
        },
    ),
    "rh_sem_registro": (
        {"Nome": "Carlos Eduardo Silva", "CPF": "987.654.321-02", "Unidade": "Loja Manaus Atacarejo"},
    ),
}


def com_amostras(report: Any) -> Any:
    """Injeta amostras determinísticas nos problemas do relatório."""
    return replace(
        report,
        outcomes=tuple(
            replace(outcome, samples=SAMPLES.get(outcome.test_name, ()))
            if outcome.is_quality_problem
            else outcome
            for outcome in report.outcomes
        ),
    )


class TestTodosAprovados:
    @pytest.fixture
    def report(self, all_pass_results: Mapping[str, Any], manifest: Mapping[str, Any]) -> Any:
        return build(all_pass_results, manifest)

    def test_mensagem_curta_de_sucesso(self, report: Any) -> None:
        blocks = build_blocks(report)
        conteudo = texts(blocks)

        assert blocks[0]["text"]["text"].startswith("🟢 Data Quality — Base RH")
        assert "Todos os testes de qualidade foram aprovados." in conteudo
        assert "Execução concluída com sucesso" in conteudo

    def test_resumo_com_taxa_de_sucesso(self, report: Any) -> None:
        conteudo = texts(build_blocks(report))

        assert "Testes executados    3" in conteudo
        assert "Aprovados            3" in conteudo
        assert "Falhas               0" in conteudo
        assert "Taxa de sucesso    100%" in conteudo

    def test_nao_lista_problemas(self, report: Any) -> None:
        assert "🔴" not in texts(build_blocks(report))
        assert len(build_blocks(report)) <= 7

    def test_texto_de_fallback(self, report: Any) -> None:
        fallback = build_fallback_text(report)

        assert fallback.startswith("🟢 Data Quality — Base RH")
        assert "3 testes executados, 3 aprovados, 0 falhas" in fallback
        assert "21/09/2026 09:00" in fallback


class TestProblemasDeQualidade:
    @pytest.fixture
    def report(self, failures_results: Mapping[str, Any], manifest: Mapping[str, Any]) -> Any:
        return build(failures_results, manifest)

    def test_titulo_e_rodape_de_alerta(self, report: Any) -> None:
        conteudo = texts(build_blocks(report))

        assert "🔎 Relatório de Qualidade de Dados — Base RH" in conteudo
        assert "Problemas encontrados nos dados" in conteudo
        assert "recomenda verificar os registros apontados" in conteudo

    def test_contexto_com_comando_do_dbt(self, report: Any) -> None:
        conteudo = texts(build_blocks(report))

        assert "dbt 1.11.14" in conteudo
        assert "dbt build -s tag:rh" in conteudo
        assert "(America/Sao_Paulo)" in conteudo

    def test_cada_problema_tem_regra_impacto_e_acao(self, report: Any) -> None:
        conteudo = texts(build_blocks(report))

        for titulo in (
            "Colaboradores desligados sem data de desligamento",
            "Intervalo de afastamento inválido",
            "Colaboradores que sumiram do extrato semanal",
        ):
            assert titulo in conteudo
        assert conteudo.count("*Problema:*") == 3
        assert conteudo.count("*Impacto:*") == 3
        assert conteudo.count("*Ação recomendada:*") == 3
        assert conteudo.count("*Registros afetados:*") == 3

    def test_tabela_e_modelo_de_cada_problema(self, report: Any) -> None:
        conteudo = texts(build_blocks(com_amostras(report)))

        assert conteudo.count("`rh_trusted` · teste `rh_") == 3
        assert "severidade `warn`" in conteudo
        assert conteudo.count("*Registros apontados*") == 3
        assert "Nome" in conteudo and "Unidade" in conteudo

    def test_colunas_seguem_o_meta_do_teste(self, report: Any) -> None:
        conteudo = texts(build_blocks(com_amostras(report)))

        assert "Data_Inicio_Afastamento" in conteudo
        assert "Data_Desligamento" in conteudo

    def test_taxa_de_sucesso_zero(self, report: Any) -> None:
        assert re.search(r"Taxa de sucesso\s+0%", texts(build_blocks(report)))

    def test_texto_de_fallback_lista_os_problemas(self, report: Any) -> None:
        fallback = build_fallback_text(report)

        assert "Colaboradores desligados sem data de desligamento (2 registro(s))" in fallback
        assert "3 falhas" in fallback

    def test_erros_de_execucao_aparecem_quebrado(self, report: Any) -> None:
        conteudo = texts(build_blocks(com_amostras(report)))

        assert "Thiago Nunes" in conteudo


class TestErroDeExecucao:
    @pytest.fixture
    def report(self, error_results: Mapping[str, Any], manifest: Mapping[str, Any]) -> Any:
        return build(error_results, manifest)

    def test_diferenciado_de_falha_de_dados(self, report: Any) -> None:
        conteudo = texts(build_blocks(report))

        assert "🛑" in conteudo
        assert "não puderam ser executados" in conteudo
        assert "não* um problema de qualidade dos dados" in conteudo
        assert "Falha técnica na execução" in conteudo

    def test_mensagem_do_dbt_incluida(self, report: Any) -> None:
        conteudo = texts(build_blocks(report))

        assert "invalid input syntax for type date" in conteudo

    def test_resumo_mostra_erros_e_nao_sucesso(self, report: Any) -> None:
        conteudo = texts(build_blocks(report))

        assert re.search(r"Erros de execução\s+1", conteudo)
        assert re.search(r"Ignorados\s+1", conteudo)
        assert re.search(r"Taxa de sucesso\s+33,3%", conteudo) or re.search(
            r"Taxa de sucesso\s+33.3%", conteudo
        )

    def test_falha_e_erro_aparecem_em_secoes_distintas(self, report: Any) -> None:
        conteudo = texts(build_blocks(report))

        assert "🔴 *Colaboradores que sumiram do extrato semanal*" in conteudo
        assert "⚠️ *Intervalo de afastamento inválido*" in conteudo
        assert "Registros afetados:* 1" in conteudo


class TestSemTestesExecutados:
    def test_avisa_que_nao_validou(self, empty_results: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
        report = build(empty_results, manifest)
        conteudo = texts(build_blocks(report))

        assert report.status is RunStatus.NO_TESTS
        assert "❔ Data Quality — Base RH" in conteudo
        assert "Nenhum teste de qualidade foi executado" in conteudo
        assert "não foi validada" in conteudo
        assert "Sem testes executados não há garantia de qualidade" in conteudo

    def test_nao_mostra_resumo_de_execucao(self, empty_results: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
        conteudo = texts(build_blocks(build(empty_results, manifest)))

        assert "Resumo da execução" not in conteudo
        assert "Taxa de sucesso" not in conteudo

    def test_run_so_com_modelos(self, models_only_results: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
        assert build(models_only_results, manifest).status is RunStatus.NO_TESTS


class TestFormatacao:
    def test_cpfnunca_aparece_em_claro(self, failures_results: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
        report = build(failures_results, manifest)
        assert all(not outcome.samples for outcome in report.problems)

        conteudo = texts(build_blocks(com_amostras(report)))

        assert "852.963.741-11" not in conteudo
        assert "654.321.987-19" not in conteudo
        assert "Camila Mendes" in conteudo
        assert mask_cpf("852.963.741-11") in conteudo

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("852.963.741-11", "***.***.741-**"),
            ("85296374111", "***.***.741-**"),
            ("852.963.741", "***.***.***-**"),
            ("", "***.***.***-**"),
        ],
    )
    def test_mascara_de_cpf(self, value: str, expected: str) -> None:
        assert mask_cpf(value) == expected

    def test_texto_do_dbt_e_escapado(self, failures_results: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
        report = build(failures_results, manifest)
        com_metacaracteres = replace(
            report,
            outcomes=tuple(
                replace(
                    o,
                    context=replace(
                        o.context,
                        business_rule="Se a <tabela> & o <nome> forem <inconsistentes>...",
                    ),
                )
                if o.test_name == "rh_desligados"
                else o
                for o in report.outcomes
            ),
        )
        conteudo = texts(build_blocks(com_metacaracteres))

        assert "&lt;tabela&gt; &amp;" in conteudo
        assert "<tabela>" not in conteudo

    def test_respeita_limites_do_slack(self, failures_results: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
        report = build(failures_results, manifest)
        blocos = build_blocks(report)

        assert len(blocos) <= 50
        for bloco in blocos:
            if bloco["type"] == "header":
                assert len(bloco["text"]["text"]) <= HEADER_MAX_CHARS
            if bloco["type"] == "section":
                assert len(bloco["text"]["text"]) <= SECTION_MAX_CHARS

    @pytest.mark.parametrize(
        "run_results",
        ["all_pass_results", "failures_results", "error_results", "empty_results"],
    )
    def test_todo_tipo_de_bloco_e_aceito_pelo_slack(
        self, request: pytest.FixtureRequest, run_results: str, manifest: Mapping[str, Any]
    ) -> None:
        """Um tipo fora da lista faz o webhook responder 400 e nada ser entregue."""
        blocos = build_blocks(build(request.getfixturevalue(run_results), manifest))

        assert {bloco["type"] for bloco in blocos} <= ALLOWED_BLOCK_TYPES

    def test_todo_texto_de_bloco_e_uma_string_nao_vazia(
        self, failures_results: Mapping[str, Any], manifest: Mapping[str, Any]
    ) -> None:
        for bloco in build_blocks(com_amostras(build(failures_results, manifest))):
            if "text" in bloco:
                assert bloco["text"]["type"] in {"mrkdwn", "plain_text"}
                assert isinstance(bloco["text"]["text"], str) and bloco["text"]["text"].strip()
            for elemento in bloco.get("elements", []):
                assert isinstance(elemento.get("text"), str) and elemento["text"].strip()

    def test_header_longo_e_truncado(self, all_pass_results: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
        report = build(all_pass_results, manifest, channel_label="Base " + "RH " * 100)
        cabecalho = build_blocks(report)[0]

        assert len(cabecalho["text"]["text"]) == HEADER_MAX_CHARS

    def test_mensagem_de_erro_gigante_e_truncada(self, error_results: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
        gigante = {**error_results, "results": [r for r in error_results["results"] if r["status"] == "error"]}
        report = build({**gigante, "results": [dict(r, message="erro " * 5000) for r in gigante["results"]]}, manifest)
        bloco = next(b for b in build_blocks(report) if "Mensagem do dbt" in b.get("text", {}).get("text", ""))

        assert len(bloco["text"]["text"]) <= SECTION_MAX_CHARS

    def test_payload_tem_text_e_blocks(self, failures_results: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
        payload = build_payload(build(failures_results, manifest))

        assert set(payload) == {"text", "blocks"}
        assert isinstance(payload["blocks"], list) and payload["blocks"]
        assert payload["text"]
        # serializável, como exige requests.post(data=json.dumps(...))
        assert json.loads(json.dumps(payload, ensure_ascii=False)) == payload

    def test_muitos_problemas_sao_resumidos(self, failures_results: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
        base = next(r for r in failures_results["results"] if r["status"] == "warn")
        muitos = [dict(base, unique_id=f"test.dbt_lab.teste_{i}") for i in range(15)]
        report = build({**failures_results, "results": muitos}, manifest)
        conteudo = texts(build_blocks(report))

        assert report.status is RunStatus.QUALITY_ISSUES
        assert conteudo.count("🔴 *") == 10
        assert "e mais 5 problema(s) de qualidade" in conteudo

    def test_colunas_de_amostra_sao_limitadas(self, failures_results: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
        outcome = next(
            o for o in build(failures_results, manifest).problems if o.test_name == "rh_intervalo_status"
        )
        muitas_colunas = {f"Coluna_{indice}": "x" for indice in range(12)}
        conteudo = texts(build_blocks(replace(build(failures_results, manifest), outcomes=(replace(outcome, samples=(muitas_colunas,)),))))

        assert conteudo.count("Coluna_") <= MAX_SAMPLE_COLUMNS + 1  # +1 do cabeçalho


class TestAvisos:
    def test_aviso_aparece_sem_vazar_detalhe_interno(
        self, failures_results: Mapping[str, Any], manifest: Mapping[str, Any]
    ) -> None:
        report = build(failures_results, manifest, include_samples=True, db_path=None)
        conteudo = texts(build_blocks(report))

        assert any("Amostras indisponíveis" in warning for warning in report.warnings)
        assert "avisos técnicos na coleta" in conteudo
        assert "run_results.json" not in conteudo
        assert "duckdb" not in conteudo
        assert "None" not in conteudo

    def test_sem_amostras_por_falha_de_banco(self, failures_results: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
        report = build(failures_results, manifest, include_samples=True, db_path=None)
        conteudo = texts(build_blocks(report))

        assert "Não foi possível listar os registros afetados" in conteudo
        assert "Thiago Nunes" not in conteudo

    def test_teste_sem_meta_avisa_na_mensagem(self, error_results: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
        results = {**error_results, "results": [dict(r, status="fail", failures=4) for r in error_results["results"] if "cpf_duplicado" in r["unique_id"]]}
        conteudo = texts(build_blocks(build(results, manifest)))

        assert "não declara uma descrição de negócio" in conteudo
        assert "*Problema:*" not in conteudo


class TestTruncate:
    @pytest.mark.parametrize(
        ("text", "limit", "expected"),
        [
            ("abc", 10, "abc"),
            ("abcdef", 6, "abcdef"),
            ("abcdef", 5, "abcd…"),
        ],
    )
    def test_truncamento(self, text: str, limit: int, expected: str) -> None:
        assert truncate(text, limit) == expected
