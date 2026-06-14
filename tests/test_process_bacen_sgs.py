from __future__ import annotations

import os
from pathlib import Path

from src.config.series_config import BacenSeriesConfig
from src.processing import process_bacen_sgs


def test_get_latest_raw_parquet_should_return_most_recent_file(tmp_path, monkeypatch) -> None:
    series_config = BacenSeriesConfig(
        code=11,
        name="selic_diaria",
        description="Taxa Selic diaria",
        start_date="01/01/2023",
        end_date="31/12/2024",
        frequency="daily",
    )

    older_file = tmp_path / "bacen_sgs_11_selic_diaria_20240101_120000.parquet"
    newer_file = tmp_path / "bacen_sgs_11_selic_diaria_20240102_120000.parquet"

    older_file.write_text("fake parquet content")
    newer_file.write_text("fake parquet content")

    os.utime(older_file, (1000, 1000))
    os.utime(newer_file, (2000, 2000))

    monkeypatch.setattr(process_bacen_sgs, "RAW_DATA_DIR", Path(tmp_path))

    latest_file = process_bacen_sgs.get_latest_raw_parquet(series_config)

    assert latest_file == newer_file


def test_get_latest_raw_parquet_should_raise_error_when_file_does_not_exist(
    tmp_path,
    monkeypatch,
) -> None:
    series_config = BacenSeriesConfig(
        code=999,
        name="serie_inexistente",
        description="Serie inexistente para teste",
        start_date="01/01/2023",
        end_date="31/12/2024",
        frequency="monthly",
    )

    monkeypatch.setattr(process_bacen_sgs, "RAW_DATA_DIR", Path(tmp_path))

    try:
        process_bacen_sgs.get_latest_raw_parquet(series_config)
    except FileNotFoundError as error:
        assert "No raw Parquet files found" in str(error)
    else:
        raise AssertionError("Expected FileNotFoundError was not raised.")
