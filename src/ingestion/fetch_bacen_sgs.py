from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from src.config.series_config import BACEN_SERIES_CONFIGS, BacenSeriesConfig


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"
LOG_DIR = PROJECT_ROOT / "logs"

BACEN_SGS_BASE_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{series_code}/dados"


def setup_logging() -> None:
    """
    Configure application logging for console and file outputs.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    log_file = LOG_DIR / "ingestion.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def fetch_bacen_sgs_series(
    series_config: BacenSeriesConfig,
) -> list[dict[str, Any]]:
    """
    Fetch a time series from the Brazilian Central Bank SGS API.

    Args:
        series_config: BACEN SGS series configuration.

    Returns:
        Raw API response as a list of dictionaries.
    """
    logger = logging.getLogger(__name__)

    params = {
        "formato": "json",
        "dataInicial": series_config.start_date,
        "dataFinal": series_config.end_date,
    }

    url = BACEN_SGS_BASE_URL.format(series_code=series_config.code)

    try:
        logger.info(
            "Fetching BACEN SGS series %s - %s from %s to %s",
            series_config.code,
            series_config.name,
            series_config.start_date,
            series_config.end_date,
        )

        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()

        if not data:
            raise ValueError(
                f"No data returned for series {series_config.code} "
                f"between {series_config.start_date} and {series_config.end_date}."
            )

        logger.info(
            "Successfully fetched %s records for %s",
            len(data),
            series_config.name,
        )

        return data

    except requests.exceptions.Timeout as error:
        logger.exception("Request timed out while fetching BACEN SGS data.")
        raise RuntimeError("BACEN SGS request timed out.") from error

    except requests.exceptions.ConnectionError as error:
        logger.exception("Connection error while fetching BACEN SGS data.")
        raise RuntimeError("Could not connect to BACEN SGS API.") from error

    except requests.exceptions.HTTPError as error:
        logger.exception("HTTP error returned by BACEN SGS API.")
        raise RuntimeError("BACEN SGS API returned an HTTP error.") from error

    except requests.exceptions.RequestException as error:
        logger.exception("Unexpected request error while fetching BACEN SGS data.")
        raise RuntimeError("Unexpected error while requesting BACEN SGS API.") from error

    except ValueError:
        logger.exception("Invalid or empty response from BACEN SGS API.")
        raise


def save_raw_data(
    data: list[dict[str, Any]],
    series_config: BacenSeriesConfig,
) -> tuple[Path, Path]:
    """
    Save raw API response as JSON and Parquet files.

    Args:
        data: Raw API response.
        series_config: BACEN SGS series configuration.

    Returns:
        Paths to the saved JSON and Parquet files.
    """
    logger = logging.getLogger(__name__)

    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)

    extraction_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = (
        f"bacen_sgs_{series_config.code}_"
        f"{series_config.name}_{extraction_timestamp}"
    )

    json_path = RAW_DATA_DIR / f"{base_name}.json"
    parquet_path = RAW_DATA_DIR / f"{base_name}.parquet"

    with json_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)

    df = pd.DataFrame(data)
    df["series_code"] = series_config.code
    df["series_name"] = series_config.name
    df["source"] = "BACEN_SGS"
    df["extraction_timestamp"] = extraction_timestamp

    df.to_parquet(parquet_path, index=False)

    logger.info("Raw JSON saved to %s", json_path)
    logger.info("Raw Parquet saved to %s", parquet_path)

    return json_path, parquet_path


def run_ingestion() -> None:
    """
    Run BACEN SGS ingestion for all configured series.
    """
    logger = logging.getLogger(__name__)

    for series_config in BACEN_SERIES_CONFIGS:
        try:
            raw_data = fetch_bacen_sgs_series(series_config=series_config)

            json_path, parquet_path = save_raw_data(
                data=raw_data,
                series_config=series_config,
            )

            print(f"Serie ingerida com sucesso: {series_config.name}")
            print(f"JSON bruto: {json_path}")
            print(f"Parquet bruto: {parquet_path}")

        except Exception:
            logger.exception(
                "Failed to ingest BACEN SGS series %s - %s",
                series_config.code,
                series_config.name,
            )
            raise


def main() -> None:
    """
    Run BACEN SGS ingestion pipeline.
    """
    setup_logging()
    run_ingestion()


if __name__ == "__main__":
    main()