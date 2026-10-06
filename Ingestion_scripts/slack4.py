from slackify_markdown import slackify_markdown
import requests, json
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

with open("report.md", "r", encoding="utf-8") as f:
    md = f.read()

texto_slack = slackify_markdown(md)

requests.post(
    WEBHOOK_URL,
    data=json.dumps({"text": texto_slack}),
    headers={"Content-Type": "application/json"}
)