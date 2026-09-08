import duckdb
from sqlalchemy import create_engine,text


df = duckdb.sql("""
select * from read_csv('./data/lojas.csv',all_varchar=True)
""").df()


# 2. SQLAlchemy representa o banco destino
engine = create_engine(
    "duckdb:///db/my-duckdb.duckdb"
)

dataset = 'raw'
table_name='lojas'

with engine.connect() as conn:
    conn.execute(text(f"""
        create schema if not exists {dataset}
    """
    ))

# 3. Pandas faz a carga
df.to_sql(
    schema=dataset,
    name=table_name,
    con=engine,
    if_exists="replace",
    index=False,
)