from __future__ import annotations

from src.quality.validate_bacen_series import (
    build_expected_series_values_sql,
    build_quality_checks,
    evaluate_status,
)


def test_evaluate_status_should_return_pass_when_there_are_no_violations() -> None:
    assert evaluate_status(0) == "PASS"


def test_evaluate_status_should_return_fail_when_there_are_violations() -> None:
    assert evaluate_status(1) == "FAIL"


def test_build_expected_series_values_sql_should_include_configured_series() -> None:
    values_sql = build_expected_series_values_sql()

    assert "11" in values_sql
    assert "433" in values_sql


def test_build_quality_checks_should_not_be_empty() -> None:
    checks = build_quality_checks()

    assert len(checks) > 0
