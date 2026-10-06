uv python install 3.12

# Install dbt
uv init --bare

# Adicionar dependencias
uv add dbt
uv add dbt-clickhouse

# Iniciar dbt
uv run dbt init --profiles-dir .

# Criar link simbólico entre o profile local e o diretorio de referencia
ln ./Refs/profiles.yml ~/.dbt/profiles.yml # Adicionar a flag -f se o arquivo destino ja existir



# slack webhook
# Nao comitar a URL. Cadastre-a em .env (veja .env.example) ou exporte no shell:
# export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/T.../B.../..."