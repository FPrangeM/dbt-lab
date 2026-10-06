"""Testes do envio ao Slack e do CLI.

Nenhum teste aqui faz requisição de rede: a sessão HTTP é substituída por um
dublê, e o `SLACK_WEBHOOK_URL` nunca é usado contra o Slack real.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
import requests

from dbt_lab.observability import cli
from dbt_lab.observability.slack import SlackDeliveryError, SlackNotifier, redact_url

FAKE_WEBHOOK = "https://hooks.slack.com/services/T000/B000/segredo"


class FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "ok") -> None:
        self.status_code = status_code
        self.text = text

    @property
    def ok(self) -> bool:
        return self.status_code < 400


class FakeSession:
    """Dublê de requests.Session: registra a chamada, não acessa a rede."""

    def __init__(self, response: FakeResponse | None = None, error: Exception | None = None) -> None:
        self.response = response or FakeResponse()
        self.error = error
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        if self.error is not None:
            raise self.error
        return self.response

    def close(self) -> None:
        self.closed = True


class TestRedactUrl:
    def test_esconde_o_caminho_do_webhook(self) -> None:
        redigido = redact_url(FAKE_WEBHOOK)

        assert redigido == "https://hooks.slack.com/***"
        assert "segredo" not in redigido

    def test_url_invalida(self) -> None:
        assert redact_url("não é url") == "***"


class TestSlackNotifier:
    def test_envia_blocks_e_text_como_json(self) -> None:
        session = FakeSession()
        blocks: list[dict[str, Any]] = [{"type": "section", "text": {"type": "mrkdwn", "text": "olá"}}]

        SlackNotifier(FAKE_WEBHOOK, session=session).send(blocks, text="resumo")

        call = session.calls[0]
        assert call["url"] == FAKE_WEBHOOK
        assert call["headers"] == {"Content-Type": "application/json"}
        assert call["timeout"] == 10.0
        payload = json.loads(call["data"])
        assert payload == {"text": "resumo", "blocks": blocks}

    def test_preserva_acentos(self) -> None:
        session = FakeSession()

        SlackNotifier(FAKE_WEBHOOK, session=session).send([], text="Qualidade de Dados — 3 falhas")

        assert "Qualidade de Dados — 3 falhas" in session.calls[0]["data"]

    def test_timeout_configuravel(self) -> None:
        session = FakeSession()

        SlackNotifier(FAKE_WEBHOOK, timeout=2.5, session=session).send([], text="x")

        assert session.calls[0]["timeout"] == 2.5

    def test_recusa_do_slack_vira_erro_sem_vazar_o_webhook(self) -> None:
        session = FakeSession(FakeResponse(400, "invalid_payload"))
        notifier = SlackNotifier(FAKE_WEBHOOK, session=session)

        with pytest.raises(SlackDeliveryError) as erro:
            notifier.send([], text="x")

        assert "HTTP 400" in str(erro.value)
        assert "invalid_payload" in str(erro.value)
        assert "segredo" not in str(erro.value)

    def test_falha_de_rede_vira_erro_tratado(self) -> None:
        session = FakeSession(error=requests.ConnectionError("dns"))

        with pytest.raises(SlackDeliveryError, match="Falha de rede"):
            SlackNotifier(FAKE_WEBHOOK, session=session).send([], text="x")

    def test_webhook_vazio_e_rejeitado(self) -> None:
        with pytest.raises(ValueError, match="obrigatório"):
            SlackNotifier("")

    def test_log_nao_contem_o_webhook(self, caplog: pytest.LogCaptureFixture) -> None:
        session = FakeSession()
        with caplog.at_level(logging.INFO, logger="dbt_lab.observability.slack"):
            SlackNotifier(FAKE_WEBHOOK, session=session).send([], text="x")

        assert "segredo" not in caplog.text
        assert "hooks.slack.com" in caplog.text

    def test_context_manager_fecha_a_sessao(self) -> None:
        session = FakeSession()

        with SlackNotifier(FAKE_WEBHOOK, session=session) as notifier:
            notifier.send([], text="x")

        assert session.closed is True


class TestCliDryRun:
    def test_gera_payload_sem_enviar(
        self, target_dir: Path, failures_results: Mapping[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (target_dir / "run_results.json").write_text(json.dumps(failures_results), encoding="utf-8")
        enviados: list[object] = []
        monkeypatch.setattr(cli.SlackNotifier, "send", lambda self, *a, **k: enviados.append(a))

        codigo = cli.main(["--target-dir", str(target_dir), "--dry-run", "--no-samples"])

        payload = json.loads(capsys.readouterr().out)
        assert codigo == 0
        assert enviados == []
        assert payload["blocks"][0]["type"] == "header"
        assert "🔎" in payload["text"]

    def test_dry_run_nao_exige_webhook(self, target_dir: Path, all_pass_results: Mapping[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
        (target_dir / "run_results.json").write_text(json.dumps(all_pass_results), encoding="utf-8")
        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)

        assert cli.main(["--target-dir", str(target_dir), "--dry-run", "--no-samples"]) == 0

    def test_grava_payload_em_arquivo(
        self, target_dir: Path, all_pass_results: Mapping[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (target_dir / "run_results.json").write_text(json.dumps(all_pass_results), encoding="utf-8")
        destino = tmp_path / "saida" / "payload.json"

        cli.main(["--target-dir", str(target_dir), "--dry-run", "--no-samples", "--out", str(destino)])

        assert json.loads(destino.read_text(encoding="utf-8"))["text"].startswith("🟢")
        assert capsys.readouterr().out  # também imprime no stdout

    def test_artefato_ausente_sai_com_erro(
        self, target_dir: Path, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with caplog.at_level(logging.ERROR, logger="dbt_lab.observability"):
            codigo = cli.main(["--target-dir", str(target_dir), "--dry-run"])

        assert codigo == 1
        assert "run_results.json não encontrado" in caplog.text
        assert capsys.readouterr().out == ""


class TestCliEntrega:
    def test_envia_quando_o_webhook_existe(
        self, target_dir: Path, all_pass_results: Mapping[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (target_dir / "run_results.json").write_text(json.dumps(all_pass_results), encoding="utf-8")
        chamadas: list[tuple[Any, ...]] = []
        monkeypatch.setenv("SLACK_WEBHOOK_URL", FAKE_WEBHOOK)
        monkeypatch.setattr(cli.SlackNotifier, "send", lambda self, blocks, text: chamadas.append((blocks, text)))

        codigo = cli.main(["--target-dir", str(target_dir), "--no-samples"])

        assert codigo == 0
        assert chamadas and chamadas[0][0][0]["type"] == "header"

    def test_sem_webhook_sai_com_erro_e_nao_chama_a_rede(
        self, target_dir: Path, all_pass_results: Mapping[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (target_dir / "run_results.json").write_text(json.dumps(all_pass_results), encoding="utf-8")
        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
        monkeypatch.setenv("DQ_TARGET_DIR", str(target_dir))

        codigo = cli.main(["--no-samples"])

        assert codigo == 1

    def test_falha_de_entrega_sai_com_erro(
        self, target_dir: Path, all_pass_results: Mapping[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (target_dir / "run_results.json").write_text(json.dumps(all_pass_results), encoding="utf-8")
        monkeypatch.setenv("SLACK_WEBHOOK_URL", FAKE_WEBHOOK)

        def falha(self: Any, blocks: Sequence[Mapping[str, Any]], text: str) -> None:
            raise SlackDeliveryError("Slack recusou")

        monkeypatch.setattr(cli.SlackNotifier, "send", falha)

        assert cli.main(["--target-dir", str(target_dir), "--no-samples"]) == 1


class TestSettings:
    def test_padroes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for variavel in (
            "SLACK_WEBHOOK_URL",
            "DQ_TARGET_DIR",
            "DQ_DB_PATH",
            "DQ_CHANNEL_LABEL",
            "DQ_AUDIENCE",
            "DQ_TIMEZONE",
            "DQ_SAMPLE_LIMIT",
            "DQ_HTTP_TIMEOUT",
            "DQ_LOG_LEVEL",
        ):
            monkeypatch.delenv(variavel, raising=False)

        settings = cli.Settings.from_env()

        assert settings.webhook_url is None
        assert settings.channel_label == "Base RH"
        assert settings.audience == "RH"
        assert settings.timezone_name == "America/Sao_Paulo"
        assert settings.sample_limit == 3
        assert settings.http_timeout == 10.0
        assert settings.target_dir.name == "target"
        assert settings.db_path.suffix == ".duckdb"

    def test_lê_do_ambiente(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SLACK_WEBHOOK_URL", FAKE_WEBHOOK)
        monkeypatch.setenv("DQ_CHANNEL_LABEL", "Base Financeira")
        monkeypatch.setenv("DQ_SAMPLE_LIMIT", "5")
        monkeypatch.setenv("DQ_HTTP_TIMEOUT", "3.5")

        settings = cli.Settings.from_env()

        assert settings.webhook_url == FAKE_WEBHOOK
        assert settings.channel_label == "Base Financeira"
        assert settings.sample_limit == 5
        assert settings.http_timeout == 3.5

    @pytest.mark.parametrize(("raw", "esperado"), [("abc", 3), ("0", 3), ("-1", 3), ("7", 7)])
    def test_sample_limit_invalido_cai_para_o_padrao(self, monkeypatch: pytest.MonkeyPatch, raw: str, esperado: int) -> None:
        monkeypatch.setenv("DQ_SAMPLE_LIMIT", raw)

        assert cli.Settings.from_env().sample_limit == esperado

    def test_timeout_invalido_cai_para_o_padrao(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DQ_HTTP_TIMEOUT", "muito")

        assert cli.Settings.from_env().http_timeout == 10.0

    def test_dotenv_nao_sobrescreve_o_ambiente(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("DQ_CHANNEL_LABEL=Vinda do arquivo\nDQ_AUDIENCE=Vinda do arquivo\n", encoding="utf-8")
        monkeypatch.setenv("DQ_CHANNEL_LABEL", "Vinda do shell")

        settings = cli.Settings.from_env(env_file=env_file)

        assert settings.channel_label == "Vinda do shell"
        assert settings.audience == "Vinda do arquivo"
