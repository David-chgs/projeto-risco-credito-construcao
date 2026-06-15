"""
export_to_postgres.py

Exports DuckDB analytical tables to PostgreSQL so Metabase can connect
and serve the credit risk dashboard.

Tables exported (schema: public, database: credit_risk)
────────────────────────────────────────────────────────
processed_empreendimentos   — proposal-level detail (drilldowns)
analytics_carteira_cenario  — portfolio health by viability scenario
analytics_carteira_regiao   — regional risk concentration
analytics_carteira_padrao   — padrão × cenário risk matrix
analytics_pipeline_mensal   — monthly origination pipeline

Prerequisites
─────────────
1. Copy .env.docker to .env and fill in your credentials.
2. Start the stack:  docker compose up -d
3. Wait for Postgres to be healthy (~10 s), then run this script.
4. Open Metabase at http://localhost:3000 and add credit_risk as a data source.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import duckdb
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WAREHOUSE_DIR = PROJECT_ROOT / "data" / "warehouse"
LOG_DIR = PROJECT_ROOT / "logs"

DUCKDB_PATH = WAREHOUSE_DIR / "credit_risk.duckdb"

_TABLES_TO_EXPORT: list[str] = [
    "processed_empreendimentos",
    "analytics_carteira_cenario",
    "analytics_carteira_regiao",
    "analytics_carteira_padrao",
    "analytics_pipeline_mensal",
]

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _build_pg_url() -> str:
    load_dotenv()
    try:
        user     = os.environ["POSTGRES_USER"]
        password = os.environ["POSTGRES_PASSWORD"]
        dbname   = os.environ["POSTGRES_DB"]
    except KeyError as exc:
        raise RuntimeError(
            f"Missing required env var: {exc}. "
            "Copy .env.docker to .env and fill in your credentials."
        ) from exc

    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{dbname}"


def _verify_postgres(engine) -> None:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError as exc:
        raise RuntimeError(
            "Cannot connect to PostgreSQL. "
            "Is the Docker stack running?  →  docker compose up -d"
        ) from exc


def _verify_duckdb_tables(conn: duckdb.DuckDBPyConnection) -> None:
    existing = {
        row[0]
        for row in conn.execute(
            "SELECT table_name FROM information_schema.tables"
        ).fetchall()
    }
    missing = [t for t in _TABLES_TO_EXPORT if t not in existing]
    if missing:
        raise ValueError(
            f"Tables missing in DuckDB: {missing}. "
            "Run the full ingestion → processing → analytics pipeline first."
        )


# ──────────────────────────────────────────────────────────────────────────────
# Export
# ──────────────────────────────────────────────────────────────────────────────

def export_to_postgres() -> dict[str, int]:
    """
    Read each analytical table from DuckDB and push it to PostgreSQL.

    Each table is replaced on every run (idempotent re-runs are safe).

    Returns:
        Dict mapping table_name → exported row count.

    Raises:
        FileNotFoundError: DuckDB warehouse not found.
        RuntimeError: PostgreSQL connectivity or write failure.
        ValueError: Required DuckDB tables absent.
    """
    if not DUCKDB_PATH.exists():
        raise FileNotFoundError(
            f"DuckDB warehouse not found: {DUCKDB_PATH}. "
            "Run the pipeline before exporting."
        )

    pg_url = _build_pg_url()
    engine  = create_engine(pg_url, pool_pre_ping=True)

    _verify_postgres(engine)
    logger.info("PostgreSQL connection verified | db=%s", os.getenv("POSTGRES_DB"))

    results: dict[str, int] = {}

    try:
        with duckdb.connect(str(DUCKDB_PATH), read_only=True) as duck_conn:
            _verify_duckdb_tables(duck_conn)
            logger.info("DuckDB tables verified. Starting export.")

            for table_name in _TABLES_TO_EXPORT:
                logger.info("Exporting: %s", table_name)

                try:
                    df: pd.DataFrame = duck_conn.execute(
                        f"SELECT * FROM {table_name}"
                    ).df()
                except duckdb.Error as exc:
                    raise RuntimeError(
                        f"Failed to read {table_name} from DuckDB."
                    ) from exc

                try:
                    df.to_sql(
                        name=table_name,
                        con=engine,
                        schema="public",
                        if_exists="replace",
                        index=False,
                        method="multi",
                        chunksize=500,
                    )
                except SQLAlchemyError as exc:
                    raise RuntimeError(
                        f"Failed to write {table_name} to PostgreSQL."
                    ) from exc

                results[table_name] = len(df)
                logger.info("Exported | table=%s | rows=%d", table_name, len(df))

    finally:
        engine.dispose()

    logger.info("Export complete | tables=%d | total_rows=%d", len(results), sum(results.values()))
    return results


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────

def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[
            logging.FileHandler(LOG_DIR / "export.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def main() -> None:
    setup_logging()
    try:
        results = export_to_postgres()

        print(f"\nExport concluido: {len(results)} tabelas enviadas ao PostgreSQL")
        print(f"\n{'Tabela':<40} {'Linhas':>6}")
        print("-" * 48)
        for table_name, row_count in results.items():
            print(f"{table_name:<40} {row_count:>6}")
        print(f"\nAcesse o Metabase em: http://localhost:3000")
        print("Configure a fonte de dados: Admin -> Databases -> Add -> PostgreSQL")
        print(f"  Host: postgres | Port: 5432 | Database: {os.getenv('POSTGRES_DB', 'credit_risk')}")

    except Exception:
        logger.exception("Fatal error during PostgreSQL export.")
        raise


if __name__ == "__main__":
    main()