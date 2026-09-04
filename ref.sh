
# Setup and inicialization of a local clickhouse instance
mkdir -p "$PWD/db/ch_data"
mkdir -p "$PWD/db/ch_logs"

podman run -d \
    --name my-clickhouse-server \
    -p 8123:8123 \
    -p 9000:9000 \
    -e CLICKHOUSE_PASSWORD=123 \
    --ulimit nofile=262144:262144 \
    -v "$PWD/db/ch_data:/var/lib/clickhouse/" \
    -v "$PWD/db/ch_logs:/var/log/clickhouse-server/" \
    clickhouse/clickhouse-server:head 


# Install dbt
uv init --bare

# Adicionar dependencias
uv add dbt
uv add dbt-clickhouse

# Iniciar dbt
uv run dbt init
