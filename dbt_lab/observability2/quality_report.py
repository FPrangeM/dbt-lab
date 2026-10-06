"""
Relatório de Qualidade de Dados: dbt -> Slack.

Lê target/run_results.json (o dbt já rodou), julga cada teste, escreve a
mensagem e envia ao Slack. Não roda o dbt: quem roda é o pipeline.

    uv run python dbt_lab/observability2/quality_report.py --dry-run
    uv run python dbt_lab/observability2/quality_report.py

Configuração (variável de ambiente ou .env na raiz do projeto):
    SLACK_WEBHOOK_URL  obrigatório para enviar
    DQ_TARGET_DIR      padrão dbt_lab/target
    DQ_DB_PATH         padrão db/my-duckdb.duckdb
    DQ_CHANNEL_LABEL   padrão "Base RH"
    DQ_TIMEZONE        padrão America/Sao_Paulo
    DQ_SAMPLE_LIMIT    padrão 3 (registros por problema)

O texto que o RH lê vem do `meta` de cada teste dbt (title, business_rule,
impact, action). Sem `meta`, o alerta mostra o identificador do teste e avisa
que a regra não tem descrição.

Para depurar: --dry-run imprime a mensagem em JSON sem enviar nada.
"""

import argparse
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import requests

AQUI = Path(__file__).resolve().parent
DBT = AQUI.parent
RAIZ = AQUI.parent.parent
log = logging.getLogger("quality_report")

# Status que o dbt grava -> categoria de negócio.
# 'warn' conta como FALHA de propósito: os testes deste projeto usam
# severity='warn', então um teste que encontrou dado inválido aparece como
# 'warn'. Se fosse lido como sucesso, o relatório sairia verde com registros
# reprovados. Status desconhecido vira 'erro' em vez de ser chamado de aprovado.
CATEGORIA = {
    "pass": "aprovado", "success": "aprovado", "no-op": "aprovado",
    "warn": "falha", "fail": "falha",
    "error": "erro", "runtime error": "erro", "partial success": "erro",
    "skipped": "ignorado",
}

# Título, frase e fecho de cada desfecho possível.
TEXTO = {
    "sucesso": (
        "🟢 Qualidade dos Dados | {base}",
        "✨ **Base validada com sucesso**",
        "> Todas as regras de qualidade foram atendidas. Os dados estão prontos para consumo.",
    ),
    "problemas": (
        "🟠 Qualidade dos Dados | {base}",
        "🔎 **Encontramos pontos que precisam de atenção**",
        "> A atualização foi processada, mas alguns registros não atenderam às regras de qualidade.",
    ),
    "erro_execucao": (
        "🔴 Qualidade dos Dados | {base}",
        "🚨 **A validação não pôde ser concluída**",
        "> Houve uma falha durante a execução dos controles. A base não deve ser considerada validada até o reprocessamento.",
    ),
    "sem_testes": (
        "⚪ Qualidade dos Dados | {base}",
        "❔ **A qualidade da base não foi validada**",
        "> Nenhum controle foi executado nesta atualização. É necessário verificar o pipeline antes de considerar os dados confiáveis.",
    ),
}

AVISO_ERRO = (
    "Os testes abaixo **não puderam ser executados**. Isso é uma falha técnica do pipeline "
    "e *não* um problema de qualidade dos dados: a regra em si não chegou a ser avaliada."
)

# Limites da API de blocos. Exceder qualquer um faz o webhook responder 400 e
# a mensagem ser descartada inteira.
MAX_HEADER, MAX_SECTION, MAX_CONTEXT, MAX_BLOCOS = 150, 3000, 2000, 50
MAX_CELULA, MAX_COLUNAS, MAX_DETALHE = 26, 6, 10
# Lista fechada de tipos aceitos pelo Slack hoje: um tipo fora daqui (como o
# antigo "quote", que não existe mais) derruba a mensagem inteira.
# https://docs.slack.dev/reference/block-kit/blocks
TIPOS_ACEITOS = {"actions", "context", "divider", "header", "image", "rich_text", "section", "table"}


def mascarar(valor, coluna):
    """CPF é dado pessoal: o alerta leva só um marcador, nunca o número.

    Nome e unidade já identificam o registro para a operação, e a lista completa
    fica com a Engenharia de Dados.
    """
    if "cpf" in coluna.lower():
        digitos = "".join(c for c in str(valor) if c.isdigit())
        return f"***.***.{digitos[6:9]}-**" if len(digitos) == 11 else "***.***.***-**"
    if valor is None or not str(valor).strip():
        return "—"
    limpo = " ".join(str(valor).split())
    return limpo[: MAX_CELULA - 1] + "…" if len(limpo) > MAX_CELULA else limpo


def tabela_amostras(amostras, colunas):
    """Registros apontados, alinhados à mão dentro de um bloco de código.

    Fora do bloco de código o mrkdwn usa fonte proporcional e as colunas
    desalinham, então o alinhamento é calculado a partir do maior valor.
    """
    celulas = [[mascarar(linha.get(c), c) for c in colunas] for linha in amostras]
    larguras = [max([len(c)] + [len(l[i]) for l in celulas]) for i, c in enumerate(colunas)]

    def formatar(linha):
        return "  ".join(v.ljust(w) for v, w in zip(linha, larguras)).rstrip()

    linhas = [formatar([c[:MAX_CELULA] for c in colunas]), "  ".join("-" * w for w in larguras)]
    return "\n".join(linhas + [formatar(linha) for linha in celulas])


def buscar_amostras(db_path, teste, limite):
    """Lê algumas linhas reprovadas do teste da tabela que o dbt criou.

    Devolve (linhas, motivo_da_falha). Nunca levanta exceção: se o banco ou a
    tabela não existirem, o relatório segue sem as amostras e registra o motivo.
    """
    relacao = teste["tabela_de_falhas"]
    if not db_path.exists():
        return [], f"banco não encontrado: {db_path}"
    # A relação vem como "banco"."schema"."tabela"; o primeiro pedaço é o
    # próprio banco, então só schema e tabela interessam.
    partes = [p.strip('"`') for p in relacao.split(".")]
    if len(partes) < 2:
        return [], f"relação inválida: {relacao}"
    try:
        banco = duckdb.connect(str(db_path), read_only=True)
        try:
            consulta = banco.execute(f'SELECT * FROM "{partes[-2]}"."{partes[-1]}" LIMIT {max(1, limite)}')
            colunas = [c[0] for c in consulta.description or []]
            linhas = consulta.fetchall()
        finally:
            banco.close()
    except Exception as erro:  # noqa: BLE001 - falha do banco vira aviso, não crash
        return [], f"{type(erro).__name__}: {erro}"
    return [{c: "" if v is None else str(v) for c, v in zip(colunas, linha)} for linha in linhas], None


def main():
    # ---------------------------------------------------------------- config
    arquivo_env = RAIZ / ".env"
    if arquivo_env.exists():
        try:
            from dotenv import load_dotenv

            load_dotenv(arquivo_env, override=False)  # o shell tem prioridade
        except ImportError:
            log.info("python-dotenv ausente; usando só as variáveis do ambiente.")

    zona = os.environ.get("DQ_TIMEZONE", "America/Sao_Paulo")
    base = os.environ.get("DQ_CHANNEL_LABEL", "Base RH")
    webhook = os.environ.get("SLACK_WEBHOOK_URL")
    db_path = Path(os.environ.get("DQ_DB_PATH", RAIZ / "db" / "my-duckdb.duckdb"))

    p = argparse.ArgumentParser(description="Relatório de Qualidade de Dados do dbt para o Slack.")
    p.add_argument("--target-dir", type=Path, default=Path(os.environ.get("DQ_TARGET_DIR", DBT / "target")))
    p.add_argument("--db-path", type=Path, default=db_path)
    p.add_argument("--sample-limit", type=int, default=int(os.environ.get("DQ_SAMPLE_LIMIT", 3)))
    p.add_argument("--no-samples", action="store_true", help="não lista os registros afetados")
    p.add_argument("--dry-run", action="store_true", help="imprime a mensagem e NÃO envia")
    p.add_argument("--out", type=Path, help="grava o payload em um arquivo JSON")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")

    if not args.dry_run and not webhook:
        log.error("Defina SLACK_WEBHOOK_URL no ambiente ou no %s, ou use --dry-run.", arquivo_env)
        return 1

    # ------------------------------------------------- 1. lê o que o dbt gravou
    caminho = args.target_dir / "run_results.json"
    if not caminho.exists():
        log.error(
            "%s não encontrado. Rode o dbt antes: cd dbt_lab && uv run dbt build -s tag:rh --profiles-dir ~/.dbt", caminho
        )
        return 1
    run_results = json.loads(caminho.read_text(encoding="utf-8"))
    manifesto = {}
    if (caminho.parent / "manifest.json").exists():
        manifesto = json.loads((caminho.parent / "manifest.json").read_text(encoding="utf-8"))
    else:
        log.info("manifest.json ausente: as descrições de negócio podem não aparecer.")

    # ------------------------------------------------------- 2. julga cada teste
    def texto(meta, chave):
        valor = meta.get(chave) if isinstance(meta, dict) else None
        return " ".join(valor.split()) if isinstance(valor, str) and valor.strip() else ""

    nos = manifesto.get("nodes", {})
    testes, avisos = [], []
    for resultado in run_results.get("results", []):
        # dbt build grava modelos e testes no mesmo arquivo; só testes interessam.
        if not resultado.get("unique_id", "").startswith("test."):
            continue
        no = nos.get(resultado["unique_id"], {})
        config = no.get("config") or {}
        meta = {**(config.get("meta") or {}), **(no.get("meta") or {})}
        nome = no.get("name") or resultado["unique_id"].rsplit(".", 1)[-1]
        # O modelo vem em attached_node; quando falta, dos depends_on.
        modelo = no.get("attached_node") or next(
            (d for d in (no.get("depends_on") or {}).get("nodes", []) if d.startswith("model.")), ""
        )
        reprovacoes = resultado.get("failures")
        titulo = texto(meta, "title") or nome.replace("_", " ").capitalize()
        testes.append({
            "categoria": CATEGORIA.get(str(resultado.get("status", "")).lower(), "erro"),
            "titulo": titulo,
            "regra": texto(meta, "business_rule"),
            "impacto": texto(meta, "impact"),
            "acao": texto(meta, "action"),
            "tem_descricao": any(texto(meta, k) for k in ("title", "business_rule", "impact", "action")),
            "identificacao": " · ".join(
                parte for parte in [f"`{modelo.rsplit('.', 1)[-1]}`" if modelo else "",
                                    f"teste `{nome}`",
                                    f"severidade `{config['severity']}`" if config.get("severity") else ""] if parte
            ),
            "reprovacoes": reprovacoes if isinstance(reprovacoes, int) else None,
            "mensagem_dbt": resultado.get("message"),
            "colunas": meta.get("sample_columns") if isinstance(meta.get("sample_columns"), list) else [],
            "tabela_de_falhas": no.get("relation_name") if (config.get("store_failures")) else None,
            "amostras": [],
        })

    if not args.no_samples:
        for teste in testes:
            if teste["categoria"] == "falha" and teste["tabela_de_falhas"]:
                teste["amostras"], motivo = buscar_amostras(args.db_path, teste, args.sample_limit)
                if motivo:
                    avisos.append(f"amostras de '{teste['titulo']}': {motivo}")

    contagem = {"aprovado": 0, "falha": 0, "erro": 0, "ignorado": 0}
    for teste in testes:
        contagem[teste["categoria"]] += 1
    executados = contagem["aprovado"] + contagem["falha"] + contagem["erro"]

    # Nada executado não é o mesmo que "tudo certo": sem teste rodando, a
    # qualidade dos dados simplesmente não foi validada.
    if not executados:
        situacao = "sem_testes"
    elif contagem["erro"]:
        situacao = "erro_execucao"
    elif contagem["falha"]:
        situacao = "problemas"
    else:
        situacao = "sucesso"

    # -------------------------------------------------------- 3. escreve a mensagem
    def sec(texto, limite=MAX_SECTION):
        return {"type": "section", "text": {"type": "mrkdwn", "text": texto[: limite - 1].rstrip() + "…" if len(texto) > limite else texto}}

    def div():
        return {"type": "divider"}

    metadados = run_results.get("metadata") or {}
    parametros = run_results.get("args") or {}
    comando = parametros.get("invocation_command") or f"dbt {parametros.get('which', 'test')}"
    try:
        inicio = metadados.get("invocation_started_at") or metadados.get("generated_at")
        horario = datetime.fromisoformat(str(inicio).replace("Z", "+00:00")).astimezone(ZoneInfo(zona)).strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError, ZoneInfo):  # horário é informativo; não derruba o relatório
        horario = datetime.now(timezone.utc).astimezone(ZoneInfo(zona)).strftime("%d/%m/%Y %H:%M")

    titulo, frase, fecho = TEXTO[situacao]

    # -------------------------------------------------------------
    # 3. Apresentação: relatório curto e orientado à ação.
    blocos = [
        {"type": "header", "text": {"type": "plain_text", "text": titulo.format(base=base), "emoji": True}},
        {"type": "context", "elements": [
            {"type": "mrkdwn", "text": f"_Atualização · {horario}_"},
        ]},
        div(),
    ]

    if executados:
        taxa = round(100 * contagem["aprovado"] / executados, 1)

        if contagem["falha"] == 0 and contagem["erro"] == 0:
            resumo = f"🟢 *Tudo certo* · {executados} controles validados · {taxa:g}% aprovados"
        elif contagem["erro"] > 0:
            resumo = (
                f"🔴 *Validação incompleta* · {contagem['falha']} ponto(s) de atenção · "
                f"{contagem['erro']} erro(s) de execução"
            )
        else:
            resumo = (
                f"🟠 *{contagem['falha']} ponto(s) de atenção* · "
                f"{contagem['aprovado']} de {executados} controles aprovados"
            )

        blocos.append(sec(resumo))

    falhas = [t for t in testes if t["categoria"] == "falha"]
    erros = [t for t in testes if t["categoria"] == "erro"]

    def bloco_do_problema(teste):
        detalhe = []

        # if teste["regra"]:
            # detalhe.append(f"*Problema:* {teste['regra']}")
        # if teste["reprovacoes"] is not None:
            # detalhe.append(f"*Registros:* **{teste['reprovacoes']}**")
        # if teste["impacto"]:
        #     detalhe.append(f"*Impacto:* {teste['impacto']}")
        # if teste["acao"]:
            # detalhe.append(f"*Ação:* {teste['acao']}")

        partes = [sec(f"🔴 *{teste['titulo']}*")]
        if detalhe:
            partes.append(sec("\n".join(detalhe)))

        if teste["amostras"]:
            disponiveis = list(teste["amostras"][0])
            colunas = [c for c in teste["colunas"] if c in disponiveis][:MAX_COLUNAS] or disponiveis[:MAX_COLUNAS]
            partes.append(
                sec(
                    "*Exemplos*\n```"
                    + tabela_amostras(teste["amostras"], colunas)
                    + "```"
                )
            )

        return partes

    if falhas:
        blocos += [div(), sec("*📌 O que precisa ser corrigido*")]
        for indice, teste in enumerate(falhas[:MAX_DETALHE]):
            if indice:
                blocos.append(div())
            blocos += bloco_do_problema(teste)

        if len(falhas) > MAX_DETALHE:
            blocos.append(sec(f"_+ {len(falhas) - MAX_DETALHE} problema(s) não exibido(s)_"))

    if erros:
        blocos += [
            div(),
            sec("*🛠️ Problemas na validação*"),
        ]
        for indice, teste in enumerate(erros[:MAX_DETALHE]):
            if indice:
                blocos.append(div())
            blocos.append(sec(f"⚠️ *{teste['titulo']}*"))
            mensagem = " ".join(str(teste["mensagem_dbt"] or "Sem detalhe disponível.").split())[:300]
            blocos.append(sec(f"_{mensagem}_"))

        if len(erros) > MAX_DETALHE:
            blocos.append(sec(f"_+ {len(erros) - MAX_DETALHE} erro(s) não exibido(s)_"))

    if not falhas and not erros:
        blocos += [sec(fecho)]

    if avisos:
        for aviso in avisos:
            log.warning(aviso)

    # Rodapé mínimo: não expõe detalhes técnicos ao time de RH.
    blocos += [
        div(),
        {"type": "context", "elements": [
            {"type": "mrkdwn", "text": "_Relatório automático de qualidade de dados_"}
        ]},
    ]

    invalidos = {b["type"] for b in blocos} - TIPOS_ACEITOS
    if invalidos or len(blocos) > MAX_BLOCOS:
        raise SystemExit(f"Payload inválido: tipos {sorted(invalidos)} / {len(blocos)} blocos")

    icone = {"sucesso": "🟢", "problemas": "🔎", "erro_execucao": "🛑", "sem_testes": "❔"}[situacao]
    resumo = f"{executados} controles executados · {contagem['aprovado']} aprovados · {contagem['falha']} pontos de atenção · {contagem['erro']} erros"
    if situacao == "problemas":
        resumo += " · " + ", ".join(f"{t['titulo']} ({t['reprovacoes']} registro(s))" for t in testes if t["categoria"] == "falha")
    corpo = {"text": f"{icone} Data Quality — {base} · {resumo} · {horario}", "blocks": blocos}
    log.info("%d testes: %d ok, %d falhas, %d erros, %d ignorados -> %s", len(testes), contagem["aprovado"], contagem["falha"], contagem["erro"], contagem["ignorado"], situacao)
    log.info("Resumo: %s", corpo["text"])

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(corpo, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("Payload gravado em %s", args.out)

    # ------------------------------------------------------------- 4. envia
    if args.dry_run:
        print(json.dumps(corpo, ensure_ascii=False, indent=2))
        return 0
    try:
        log.info("Enviando %d blocos para %s/services/***", len(blocos), webhook.split("/services/")[0])
        resposta = requests.post(webhook, data=json.dumps(corpo, ensure_ascii=False),
                                 headers={"Content-Type": "application/json"}, timeout=10)
        if resposta.status_code >= 400:
            raise RuntimeError((resposta.text or "")[:300])
    except Exception as erro:  # noqa: BLE001 - erro de envio não pode virar traceback cru
        log.error("Falha ao enviar: %s", erro)
        return 1
    log.info("Relatório publicado no Slack (HTTP %s).", resposta.status_code)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
