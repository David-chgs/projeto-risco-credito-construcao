from __future__ import annotations

import logging
from pathlib import Path

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"
WAREHOUSE_DIR = PROJECT_ROOT / "data" / "warehouse"
LOG_DIR = PROJECT_ROOT / "logs"

DUCKDB_PATH = WAREHOUSE_DIR / "credit_risk.duckdb"
OUTPUT_PATH = PROCESSED_DATA_DIR / "analytics_macro_indicators.parquet"


def setup_logging() -> None:
    """
    Configure application logging for console and file outputs.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    log_file = LOG_DIR / "analytics.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def build_macro_indicators() -> Path:
    """
    Build monthly macroeconomic indicators from processed BACEN series.

    Returns:
        Path to the analytics Parquet file.
    """
    logger = logging.getLogger(__name__)

    if not DUCKDB_PATH.exists():
        raise FileNotFoundError(
            f"DuckDB warehouse not found at {DUCKDB_PATH}. "
            "Run the processing pipeline before analytics."
        )

    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)

    safe_output_path = str(OUTPUT_PATH).replace("\\", "/").replace("'", "''")

    logger.info("Starting macro indicators build.")

    with duckdb.connect(str(DUCKDB_PATH)) as connection:
        connection.execute(
            """
            CREATE OR REPLACE TABLE analytics_macro_indicators AS
            WITH selic_monthly AS (
                SELECT
                    CAST(date_trunc('month', reference_date) AS DATE) AS reference_month,
                    (
                        EXP(SUM(LN(1 + value / 100))) - 1
                    ) * 100 AS selic_monthly_accumulated_percent
                FROM processed_bacen_series
                WHERE series_code = 11
                GROUP BY
                    reference_month
            ),

            ipca_monthly AS (
                SELECT
                    CAST(date_trunc('month', reference_date) AS DATE) AS reference_month,
                    value AS ipca_monthly_percent
                FROM processed_bacen_series
                WHERE series_code = 433
            )

            SELECT
                s.reference_month,
                ROUND(s.selic_monthly_accumulated_percent, 6) AS selic_monthly_accumulated_percent,
                ROUND(i.ipca_monthly_percent, 6) AS ipca_monthly_percent,
                ROUND(
                    (
                        (
                            (1 + s.selic_monthly_accumulated_percent / 100)
                            / (1 + i.ipca_monthly_percent / 100)
                        ) - 1
                    ) * 100,
                    6
                ) AS real_interest_proxy_percent,
                CURRENT_TIMESTAMP AS created_at
            FROM selic_monthly AS s
            INNER JOIN ipca_monthly AS i
                ON s.reference_month = i.reference_month
            ORDER BY
                s.reference_month
            """
        )

        row_count = connection.execute(
            """
            SELECT COUNT(*) FROM analytics_macro_indicators
            """
        ).fetchone()[0]

        if row_count == 0:
            raise ValueError("Analytics macro indicators table is empty.")

        connection.execute(
            f"""
            COPY analytics_macro_indicators
            TO '{safe_output_path}'
            (FORMAT PARQUET)
            """
        )

    logger.info("Analytics macro indicator rows: %s", row_count)
    logger.info("Analytics Parquet saved to %s", OUTPUT_PATH)

    return OUTPUT_PATH


def main() -> None:
    """
    Run macroeconomic analytics pipeline.
    """
    setup_logging()

    output_path = build_macro_indicators()

    print(f"Indicadores macroeconomicos salvos com sucesso em: {output_path}")
    print(f"Tabela DuckDB criada/atualizada: analytics_macro_indicators")


if __name__ == "__main__":
    main()
