from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BacenSeriesConfig:
    """
    Configuration for a BACEN SGS time series.
    """

    code: int
    name: str
    description: str
    start_date: str
    end_date: str
    frequency: str


BACEN_SERIES_CONFIGS: tuple[BacenSeriesConfig, ...] = (
    BacenSeriesConfig(
        code=11,
        name="selic_diaria",
        description="Taxa Selic diaria",
        start_date="01/01/2023",
        end_date="31/12/2024",
        frequency="daily",
    ),
    BacenSeriesConfig(
        code=433,
        name="ipca_mensal",
        description="IPCA variacao mensal",
        start_date="01/01/2023",
        end_date="31/12/2024",
        frequency="monthly",
    ),
)