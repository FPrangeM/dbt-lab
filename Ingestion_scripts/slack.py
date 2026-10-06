import requests
import json
import os
import sys
from pathlib import Path

WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
if not WEBHOOK_URL:
    arquivo_env = Path(__file__).resolve().parent.parent / ".env"
    if arquivo_env.exists():
        try:
            from dotenv import load_dotenv

            load_dotenv(arquivo_env, override=False)  # o shell tem prioridade
        except ImportError:
            pass
    WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

if not WEBHOOK_URL:
    sys.exit(
        "Defina SLACK_WEBHOOK_URL no ambiente ou em "
        f"{arquivo_env} (copie o .env.example)."
    )

blocks = [
    # Título (equivalente a H1/H2)
    {
        "type": "header",
        "text": {"type": "plain_text", "text": "📊 Report Diário"}
    },
    # Subtítulo / contexto
    {
        "type": "context",
        "elements": [
            {"type": "mrkdwn", "text": "_Gerado em 23/09/2026 às 10:00_"}
        ]
    },
    {"type": "divider"},

    # Seção com "tabela" simulada
    {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": (
                "*Métrica*          *Valor*      *Status*\n"
                "Vendas              R$ 15.000    ✅\n"
                "Erros               3            ⚠️\n"
                "Usuários ativos     1.240        ✅"
            )
        }
    },

    {"type": "divider"},

    # Bloco de código
    {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": "*Log de erro:*\n```ERROR: timeout ao conectar\n  at db.connect (line 42)\n  at main (line 10)```"
        }
    },

    # Citação
    {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": "> Nenhuma ação necessária no momento."
        }
    }
]

requests.post(
    WEBHOOK_URL,
    data=json.dumps({"blocks": blocks}),
    headers={"Content-Type": "application/json"}
)