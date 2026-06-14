from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import duckdb

from src.config.series_config import BACEN_SERIES_CONFIGS


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WAREHOUSE_DIR = PROJECT_ROOT / "data" / "warehouse"
LOG_DIR = PROJECT_ROOT / "logs"

DUCKDB_PATH = WAREHOUSE_DIR / "credit_risk.duckdb"


@dataclass(frozen=True)
class DataQualityCheck:
    """
    Definition of a data quality check.

    The query must return one numeric value representing the number of violations.
    """

    name: str
    query: str


@dataclass(frozen=True)
class DataQualityResult:
    """
    Result of a data quality check.
    """

    name: str
    violation_count: int
    status: str


def setup_logging() -> None:
    """
    Configure application logging for console and file outputs.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    log_file = LOG_DIR / "data_quality.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def build_expected_series_values_sql() -> str:
    """
    Build a SQL VALUES clause with configured BACEN series and expected periods.

    Returns:
        SQL VALUES clause.
    """
    values = []

    for series in BACEN_SERIES_CONFIGS:
        values.append(
            f"({series.code}, '{series.start_date}', '{series.end_date}')"
        )

    return ", ".join(values)


def build_quality_checks() -> list[DataQualityCheck]:
    """
    Build data quality checks for processed and analytics tables.

    Returns:
        List of data quality checks.
    """
    expected_series_values = build_expected_series_values_sql()

    return [
        DataQualityCheck(
            name="processed_bacen_series_has_rows",
            query="""
                SELECT
                    CASE WHEN COUNT(*) = 0 THEN 1 ELSE 0 END AS violations
                FROM processed_bacen_series
            """,
        ),
        DataQualityCheck(
            name="processed_bacen_series_has_no_nulls",
            query="""
                SELECT COUNT(*) AS violations
                FROM processed_bacen_series
                WHERE
                    reference_date IS NULL
                    OR series_code IS NULL
                    OR series_name IS NULL
                    OR value IS NULL
                    OR source IS NULL
                    OR frequency IS NULL
            """,
        ),
        DataQualityCheck(
            name="processed_bacen_series_has_no_duplicates",
            query="""
                SELECT COUNT(*) AS violations
                FROM (
                    SELECT
                        reference_date,
                        series_code,
                        COUNT(*) AS total_rows
                    FROM processed_bacen_series
                    GROUP BY
                        reference_date,
                        series_code
                    HAVING COUNT(*) > 1
                )
            """,
        ),
        DataQualityCheck(
            name="processed_bacen_series_has_all_configured_series",
            query=f"""
                WITH expected_series(series_code, start_date, end_date) AS (
                    VALUES {expected_series_values}
                ),

                available_series AS (
                    SELECT DISTINCT series_code
                    FROM processed_bacen_series
                )

                SELECT COUNT(*) AS violations
                FROM expected_series AS expected
                LEFT JOIN available_series AS available
                    ON expected.series_code = available.series_code
                WHERE available.series_code IS NULL
            """,
        ),
        DataQualityCheck(
            name="processed_bacen_series_dates_within_expected_range",
            query=f"""
                WITH expected_series_raw(series_code, start_date_text, end_date_text) AS (
                    VALUES {expected_series_values}
                ),

                expected_series AS (
                    SELECT
                        series_code,
                        CAST(strptime(start_date_text, '%d/%m/%Y') AS DATE) AS start_date,
                        CAST(strptime(end_date_text, '%d/%m/%Y') AS DATE) AS end_date
                    FROM expected_series_raw
                )

                SELECT COUNT(*) AS violations
                FROM processed_bacen_series AS processed
                INNER JOIN expected_series AS expected
                    ON processed.series_code = expected.series_code
                WHERE
                    processed.reference_date < expected.start_date
                    OR processed.reference_date > expected.end_date
            """,
        ),
        DataQualityCheck(
            name="analytics_macro_indicators_has_rows",
            query="""
                SELECT
                    CASE WHEN COUNT(*) = 0 THEN 1 ELSE 0 END AS violations
                FROM analytics_macro_indicators
            """,
        ),
        DataQualityCheck(
            name="analytics_macro_indicators_has_no_nulls",
            query="""
                SELECT COUNT(*) AS violations
                FROM analytics_macro_indicators
                WHERE
                    reference_month IS NULL
                    OR selic_monthly_accumulated_percent IS NULL
                    OR ipca_monthly_percent IS NULL
                    OR real_interest_proxy_percent IS NULL
            """,
        ),
        DataQualityCheck(
            name="analytics_macro_indicators_has_no_duplicate_months",
            query="""
                SELECT COUNT(*) AS violations
                FROM (
                    SELECT
                        reference_month,
                        COUNT(*) AS total_rows
                    FROM analytics_macro_indicators
                    GROUP BY
                        reference_month
                    HAVING COUNT(*) > 1
                )
            """,
        ),
    ]


def table_exists(connection: duckdb.DuckDBPyConnection, table_name: str) -> bool:
    """
    Check whether a table exists in the DuckDB warehouse.

    Args:
        connection: DuckDB connection.
        table_name: Table name.

    Returns:
        True when table exists, otherwise False.
    """
    result = connection.execute(
        """
        SELECT COUNT(*) AS table_count
        FROM information_schema.tables
        WHERE table_name = ?
        """,
        [table_name],
    ).fetchone()[0]

    return result > 0


def evaluate_status(violation_count: int) -> str:
    """
    Evaluate the status of a data quality check.

    Args:
        violation_count: Number of violations.

    Returns:
        PASS when there are no violations, otherwise FAIL.
    """
    if violation_count == 0:
        return "PASS"

    return "FAIL"


def run_quality_checks() -> list[DataQualityResult]:
    """
    Run all data quality checks against the DuckDB warehouse.

    Returns:
        List of data quality results.
    """
    logger = logging.getLogger(__name__)

    if not DUCKDB_PATH.exists():
        raise FileNotFoundError(
            f"DuckDB warehouse not found at {DUCKDB_PATH}. "
            "Run processing and analytics pipelines before quality checks."
        )

    required_tables = [
        "processed_bacen_series",
        "analytics_macro_indicators",
    ]

    results: list[DataQualityResult] = []

    with duckdb.connect(str(DUCKDB_PATH)) as connection:
        for table_name in required_tables:
            if not table_exists(connection=connection, table_name=table_name):
                raise ValueError(f"Required table not found: {table_name}")

        for check in build_quality_checks():
            violation_count = connection.execute(check.query).fetchone()[0]
            status = evaluate_status(violation_count=int(violation_count))

            result = DataQualityResult(
                name=check.name,
                violation_count=int(violation_count),
                status=status,
            )

            logger.info(
                "Data quality check %s finished with status %s and %s violations.",
                result.name,
                result.status,
                result.violation_count,
            )

            results.append(result)

    failed_checks = [result for result in results if result.status == "FAIL"]

    if failed_checks:
        failed_check_names = ", ".join(result.name for result in failed_checks)
        raise ValueError(f"Data quality checks failed: {failed_check_names}")

    return results


def main() -> None:
    """
    Run data quality validation pipeline.
    """
    setup_logging()

    results = run_quality_checks()

    print("Data quality checks completed successfully.")
    print("")
    print("Check results:")

    for result in results:
        print(f"- {result.status}: {result.name} ({result.violation_count} violations)")


if __name__ == "__main__":
    main()
