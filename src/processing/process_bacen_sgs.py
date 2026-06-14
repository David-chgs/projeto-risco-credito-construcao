from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from src.config.series_config import BACEN_SERIES_CONFIGS, BacenSeriesConfig


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DATA_DIR = PROJECT_ROOT / "data" / "processed"
WAREHOUSE_DIR = PROJECT_ROOT / "data" / "warehouse"
LOG_DIR = PROJECT_ROOT / "logs"

DUCKDB_PATH = WAREHOUSE_DIR / "credit_risk.duckdb"


def setup_logging() -> None:
    """
    Configure application logging for console and file outputs.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    log_file = LOG_DIR / "processing.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def get_latest_raw_parquet(series_config: BacenSeriesConfig) -> Path:
    """
    Get the most recent raw Parquet file for a BACEN SGS series.

    Args:
        series_config: BACEN SGS series configuration.

    Returns:
        Path to the latest raw Parquet file.
    """
    pattern = f"bacen_sgs_{series_config.code}_{series_config.name}_*.parquet"
    files = list(RAW_DATA_DIR.glob(pattern))

    if not files:
        raise FileNotFoundError(
            f"No raw Parquet files found in {RAW_DATA_DIR} using pattern {pattern}."
        )

    return max(files, key=lambda file_path: file_path.stat().st_mtime)


def build_raw_files_query() -> str:
    """
    Build SQL UNION query to read the latest Parquet file for each configured series.

    Returns:
        SQL query that unions all latest raw Parquet files.
    """
    select_statements: list[str] = []

    for series_config in BACEN_SERIES_CONFIGS:
        raw_file_path = get_latest_raw_parquet(series_config=series_config)
        safe_path = str(raw_file_path).replace("\\", "/").replace("'", "''")

        select_statements.append(
            f"""
            SELECT
                data,
                valor,
                series_code,
                series_name,
                source,
                '{series_config.frequency}' AS frequency
            FROM read_parquet('{safe_path}')
            """
        )

    return "\nUNION ALL\n".join(select_statements)


def process_bacen_series() -> Path:
    """
    Process all configured BACEN SGS series and save a standardized table.

    Returns:
        Path to processed Parquet file.
    """
    logger = logging.getLogger(__name__)

    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    WAREHOUSE_DIR.mkdir(parents=True, exist_ok=True)

    output_path = PROCESSED_DATA_DIR / "bacen_series.parquet"
    safe_output_path = str(output_path).replace("\\", "/").replace("'", "''")

    logger.info("Starting BACEN SGS processing for configured series.")

    raw_files_query = build_raw_files_query()

    with duckdb.connect(str(DUCKDB_PATH)) as connection:
        connection.execute(
            f"""
            CREATE OR REPLACE TABLE raw_bacen_series AS
            {raw_files_query}
            """
        )

        connection.execute(
            """
            CREATE OR REPLACE TABLE processed_bacen_series AS
            SELECT
                CAST(strptime(data, '%d/%m/%Y') AS DATE) AS reference_date,
                CAST(series_code AS INTEGER) AS series_code,
                CAST(series_name AS VARCHAR) AS series_name,
                CAST(replace(valor, ',', '.') AS DOUBLE) AS value,
                CAST(source AS VARCHAR) AS source,
                CAST(frequency AS VARCHAR) AS frequency
            FROM raw_bacen_series
            ORDER BY series_code, reference_date
            """
        )

        row_count = connection.execute(
            """
            SELECT COUNT(*) FROM processed_bacen_series
            """
        ).fetchone()[0]

        if row_count == 0:
            raise ValueError("Processed BACEN series table is empty.")

        connection.execute(
            f"""
            COPY processed_bacen_series
            TO '{safe_output_path}'
            (FORMAT PARQUET)
            """
        )

    logger.info("Processed BACEN rows: %s", row_count)
    logger.info("Processed Parquet saved to %s", output_path)
    logger.info("DuckDB warehouse saved to %s", DUCKDB_PATH)

    return output_path


def main() -> None:
    """
    Run BACEN SGS processing pipeline.
    """
    setup_logging()

    output_path = process_bacen_series()

    print(f"Arquivo processado salvo com sucesso em: {output_path}")
    print(f"Banco DuckDB criado/atualizado em: {DUCKDB_PATH}")


if __name__ == "__main__":
    main()