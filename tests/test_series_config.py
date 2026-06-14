from __future__ import annotations

from datetime import datetime

from src.config.series_config import BACEN_SERIES_CONFIGS


def test_bacen_series_configs_should_not_be_empty() -> None:
    assert len(BACEN_SERIES_CONFIGS) > 0


def test_bacen_series_codes_should_be_unique() -> None:
    codes = [series.code for series in BACEN_SERIES_CONFIGS]

    assert len(codes) == len(set(codes))


def test_bacen_series_names_should_use_snake_case() -> None:
    for series in BACEN_SERIES_CONFIGS:
        assert series.name == series.name.lower()
        assert " " not in series.name
        assert "-" not in series.name


def test_bacen_series_dates_should_use_brazilian_format() -> None:
    for series in BACEN_SERIES_CONFIGS:
        datetime.strptime(series.start_date, "%d/%m/%Y")
        datetime.strptime(series.end_date, "%d/%m/%Y")


def test_bacen_series_frequency_should_be_supported() -> None:
    supported_frequencies = {"daily", "monthly"}

    for series in BACEN_SERIES_CONFIGS:
        assert series.frequency in supported_frequencies
