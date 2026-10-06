"""Testes do catálogo de regras de negócio (`meta` do teste dbt)."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from dbt_lab.observability.catalog import build_context, humanize


class TestHumanize:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("rh_sem_registro", "Rh sem registro"),
            ("not_null_cpf", "Not null cpf"),
            ("rh", "Rh"),
        ],
    )
    def test_normaliza_o_nome_do_teste(self, name: str, expected: str) -> None:
        assert humanize(name) == expected

    def test_nome_vazio(self) -> None:
        assert humanize("") == ""


class TestBuildContext:
    def test_meta_completo(self) -> None:
        context = build_context(
            {
                "title": "Regra X",
                "audience": "Financeiro",
                "business_rule": "Regra de negócio X.",
                "impact": "Impacto X.",
                "action": "Ação X.",
                "sample_columns": ["Nome", "CPF"],
            },
            test_name="regra_x",
        )

        assert context.title == "Regra X"
        assert context.audience == "Financeiro"
        assert context.business_rule == "Regra de negócio X."
        assert context.impact == "Impacto X."
        assert context.action == "Ação X."
        assert context.sample_columns == ("Nome", "CPF")
        assert context.described is True

    def test_audiente_padrao(self) -> None:
        assert build_context({}, test_name="x", audience="RH").audience == "RH"
        assert build_context({"audience": "Fiscal"}, test_name="x", audience="RH").audience == "Fiscal"

    @pytest.mark.parametrize("meta", [None, {}, "não é mapping", 42])
    def test_meta_ausente_ou_invalido_nao_quebra(self, meta: Any) -> None:
        context = build_context(meta, test_name="rh_desligados")

        assert context.described is False
        assert context.title == "Rh desligados"
        assert context.business_rule == ""
        assert context.sample_columns == ()

    def test_valores_nao_textuais_sao_descartados(self) -> None:
        context = build_context(
            {"title": 42, "business_rule": ["lista"], "impact": "   "},
            test_name="rh_desligados",
        )

        assert context.title == "Rh desligados"
        assert context.business_rule == ""
        assert context.impact == ""
        assert context.described is False

    def test_whitespace_e_normalizado(self) -> None:
        context = build_context({"title": "  Regra\n  com   espaço  "}, test_name="x")

        assert context.title == "Regra com espaço"

    def test_sample_columns_ignora_nao_lista(self) -> None:
        assert build_context({"sample_columns": "Nome"}, test_name="x").sample_columns == ()
        assert build_context({"sample_columns": [1, "Nome", ""]}, test_name="x").sample_columns == ("Nome",)

    def test_chave_desconhecida_gera_aviso(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger="dbt_lab.observability.catalog"):
            build_context({"title": "Regra", "owner": "joao"}, test_name="x")

        assert "owner" in caplog.text
