"""Carga das tabelas do schema hackathon para DataFrames."""
import os
import pandas as pd
import psycopg

DSN = os.environ.get("FORTUNA_DSN", "host=localhost port=5432 dbname=fortuna user=postgres")
TABELAS = ["clientes", "pedidos", "movimentacao_mensal", "bureau", "parcelas"]


def carregar(dsn: str = DSN) -> dict[str, pd.DataFrame]:
    with psycopg.connect(dsn) as con:
        out = {}
        for t in TABELAS:
            with con.cursor() as cur:
                cur.execute(f"SELECT * FROM hackathon.{t}")
                cols = [d.name for d in cur.description]
                out[t] = pd.DataFrame(cur.fetchall(), columns=cols)
    for df in out.values():
        for c in df.columns:
            if df[c].dtype == object and len(df) and type(df[c].dropna().iloc[0]).__name__ == "Decimal":
                df[c] = df[c].astype(float)
            if df[c].dtype == object and len(df) and type(df[c].dropna().iloc[0]).__name__ == "date":
                df[c] = pd.to_datetime(df[c])
    return out
