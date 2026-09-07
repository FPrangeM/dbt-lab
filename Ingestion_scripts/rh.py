import duckdb
from sqlalchemy import create_engine,text


df = duckdb.sql("""
select * from read_csv('./data/extract_rh.csv',all_varchar=True)
""").df()


# 2. SQLAlchemy representa o banco destino
engine = create_engine(
    "clickhousedb://default:123@localhost:8123"
)

dataset = 'raw'
table_name='rh'

with engine.connect() as conn:
    # Gera a DDL baseada nas colunas do DataFrame
    columns_schema = ", ".join([f"`{col}` Nullable(String)" for col in df.columns])
    conn.execute(text(f"""
        CREATE OR REPLACE TABLE {dataset}.{table_name} (
            {columns_schema}
        ) 
        ENGINE = MergeTree()
        ORDER BY tuple()
    """
    ))


# 3. Pandas faz a carga
df.to_sql(
    schema=dataset,
    name=table_name,
    con=engine,
    if_exists="append",
    index=False,
)