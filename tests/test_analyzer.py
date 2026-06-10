import pytest
import pandas as pd
import numpy as np
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from ingestion.mock_data import generate_mock_cost_data
from analysis.analyzer import (
    load_cost_data,
    compute_weekly_totals,
    detect_weekly_anomalies,
    detect_daily_spikes,
    generate_report,
)


# ── Fixtures ──────────────────────────────────────────────────
# Why fixtures?
# Fixtures are reusable test data setup. Instead of regenerating
# the DataFrame in every test, pytest runs the fixture once and
# passes it in. This keeps tests fast and DRY (Don't Repeat Yourself).
# This is standard practice in production Python test suites.

@pytest.fixture
def raw_df():
    """90 days of mock cost data with 3 planted anomaly spikes."""
    return generate_mock_cost_data(days=90)


@pytest.fixture
def weekly_df(raw_df):
    """Weekly aggregated version of the raw data."""
    return compute_weekly_totals(raw_df)


@pytest.fixture
def full_report():
    """Full report dict from generate_report()."""
    return generate_report()


# ── Ingestion tests ───────────────────────────────────────────

class TestMockDataGeneration:
    """
    Tests for ingestion/mock_data.py

    Why test mock data?
    Every downstream module depends on this data having the right
    shape and values. If this breaks silently, every other module
    produces wrong results with no obvious error. These tests act
    as a contract — "this is the shape the rest of the system expects."
    """

    def test_returns_dataframe(self, raw_df):
        assert isinstance(raw_df, pd.DataFrame)

    def test_correct_row_count(self, raw_df):
        # 90 days × 7 services = 630 rows exactly
        assert len(raw_df) == 630

    def test_required_columns_present(self, raw_df):
        required = {"date", "service", "cost_usd", "is_anomaly"}
        assert required.issubset(set(raw_df.columns))

    def test_no_negative_costs(self, raw_df):
        # Cost can never be negative — a negative bill doesn't exist.
        # This would silently corrupt downstream averages if it happened.
        assert (raw_df["cost_usd"] >= 0).all()

    def test_correct_service_count(self, raw_df):
        assert raw_df["service"].nunique() == 7

    def test_exactly_three_planted_anomalies(self, raw_df):
        # We planted exactly 3 known spikes to verify detection.
        # If this count changes, the detector tests become invalid.
        assert raw_df["is_anomaly"].sum() == 3

    def test_planted_anomalies_are_on_correct_services(self, raw_df):
        # Verify spikes are on the right services and days
        anomalies = raw_df[raw_df["is_anomaly"] == True]
        spiked_services = set(anomalies["service"].tolist())
        assert "Amazon S3" in spiked_services
        assert "Amazon EC2" in spiked_services
        assert "Amazon RDS" in spiked_services

    def test_date_column_is_datetime(self, raw_df):
        assert pd.api.types.is_datetime64_any_dtype(raw_df["date"])

    def test_cost_column_is_numeric(self, raw_df):
        assert pd.api.types.is_numeric_dtype(raw_df["cost_usd"])

    def test_date_range_is_90_days(self, raw_df):
        delta = (raw_df["date"].max() - raw_df["date"].min()).days
        assert delta == 89  # 90 days = 89 day delta


# ── Analysis tests ────────────────────────────────────────────

class TestWeeklyAggregation:
    """
    Tests for compute_weekly_totals()

    Why test aggregation separately?
    If weekly totals are wrong, every downstream analysis is wrong.
    Isolating this test means when something breaks we know exactly
    which layer failed — a core principle of unit testing.
    """

    def test_returns_dataframe(self, weekly_df):
        assert isinstance(weekly_df, pd.DataFrame)

    def test_required_columns_present(self, weekly_df):
        required = {"week", "service", "weekly_cost", "week_start"}
        assert required.issubset(set(weekly_df.columns))

    def test_no_negative_weekly_costs(self, weekly_df):
        assert (weekly_df["weekly_cost"] >= 0).all()

    def test_correct_service_count_preserved(self, weekly_df):
        assert weekly_df["service"].nunique() == 7

    def test_incomplete_week_is_dropped(self, weekly_df):
        """
        The current (incomplete) week must be excluded.
        We verify by checking that all weeks have reasonable cost
        totals — an incomplete week would show unusually low cost.
        """
        min_weekly = weekly_df["weekly_cost"].min()
        # Minimum weekly cost should be > 0 for any service
        assert min_weekly > 0

    def test_weekly_cost_greater_than_daily_average(self, raw_df, weekly_df):
        """
        Weekly total per service should be roughly 7x daily average.
        This catches off-by-one errors in the aggregation window.
        """
        daily_avg = raw_df.groupby("service")["cost_usd"].mean()
        weekly_avg = weekly_df.groupby("service")["weekly_cost"].mean()

        for service in daily_avg.index:
            # Weekly should be roughly 5-7x daily (weekday factor applies)
            ratio = weekly_avg[service] / daily_avg[service]
            assert 4 <= ratio <= 8, (
                f"{service}: weekly/daily ratio {ratio:.2f} outside expected range"
            )


class TestDailySpikeDetection:
    """
    Tests for detect_daily_spikes()

    The most important tests in the suite — they verify the core
    value proposition of the entire project. If anomaly detection
    doesn't catch real spikes, the project has no business value.
    """

    def test_returns_dataframe(self, raw_df):
        result = detect_daily_spikes(raw_df)
        assert isinstance(result, pd.DataFrame)

    def test_detects_all_three_planted_spikes(self, raw_df):
        """
        This is the ground truth test — we KNOW there are 3 planted
        spikes, so the detector must find all 3. If this fails,
        the detection algorithm has a bug.
        """
        spikes = detect_daily_spikes(raw_df)
        # Check that all 3 planted anomaly rows were caught
        caught_planted = spikes[spikes["is_anomaly"] == True]
        assert len(caught_planted) == 3, (
            f"Expected 3 planted spikes caught, got {len(caught_planted)}"
        )

    def test_planted_spikes_are_p1_severity(self, raw_df):
        """
        The planted spikes are 2-3x normal cost, so z-scores will be
        very high (10+). They must be classified as P1.
        """
        spikes = detect_daily_spikes(raw_df)
        planted = spikes[spikes["is_anomaly"] == True]
        assert (planted["severity"] == "P1").all(), (
            "All planted spikes should be P1 — they are extreme outliers"
        )

    def test_severity_column_valid_values(self, raw_df):
        spikes = detect_daily_spikes(raw_df)
        if not spikes.empty:
            valid = {"P1", "P2", "P3"}
            assert set(spikes["severity"].unique()).issubset(valid)

    def test_required_columns_in_output(self, raw_df):
        spikes = detect_daily_spikes(raw_df)
        required = {"date", "service", "cost_usd", "daily_zscore",
                    "severity", "summary", "is_anomaly"}
        assert required.issubset(set(spikes.columns))

    def test_zscore_above_threshold(self, raw_df):
        """All returned spikes must have z-score >= 2.5 (our threshold)."""
        spikes = detect_daily_spikes(raw_df)
        if not spikes.empty:
            assert (spikes["daily_zscore"] >= 2.5).all()

    def test_no_false_negatives_on_planted_services(self, raw_df):
        """S3, EC2, RDS must all appear in detected spikes."""
        spikes = detect_daily_spikes(raw_df)
        planted_services = {"Amazon S3", "Amazon EC2", "Amazon RDS"}
        detected_services = set(spikes[spikes["is_anomaly"] == True]["service"])
        assert planted_services == detected_services


class TestWeeklyAnomalyDetection:
    """Tests for detect_weekly_anomalies()"""

    def test_returns_dataframe(self, weekly_df):
        result = detect_weekly_anomalies(weekly_df)
        assert isinstance(result, pd.DataFrame)

    def test_no_nan_in_wow_delta(self, weekly_df):
        """
        NaN WoW values caused false P1 alerts in early versions.
        This test ensures that bug never comes back.
        """
        result = detect_weekly_anomalies(weekly_df)
        if not result.empty:
            assert result["wow_delta_pct"].isna().sum() == 0

    def test_only_positive_wow_flagged(self, weekly_df):
        """
        Cost drops should not trigger alerts — we only care about
        unexpected increases. Negative WoW should never appear.
        """
        result = detect_weekly_anomalies(weekly_df)
        if not result.empty:
            assert (result["wow_delta_pct"] >= 0).all()

    def test_severity_valid_values(self, weekly_df):
        result = detect_weekly_anomalies(weekly_df)
        if not result.empty:
            valid = {"P1", "P2", "P3"}
            assert set(result["severity"].unique()).issubset(valid)


# ── Report generation tests ───────────────────────────────────

class TestGenerateReport:
    """
    Integration tests for generate_report()

    Why integration tests on top of unit tests?
    Unit tests verify each function in isolation. Integration tests
    verify the full pipeline works end-to-end — that all modules
    connect correctly and the output contract is correct.
    The Slack notifier and dashboard both depend on this contract.
    """

    def test_returns_dict(self, full_report):
        assert isinstance(full_report, dict)

    def test_required_keys_present(self, full_report):
        required = {
            "generated_at", "total_spend_usd", "spend_by_service",
            "top_3_cost_drivers", "weekly_anomaly_count",
            "daily_spike_count", "weekly_anomalies",
            "daily_spikes", "weekly_data",
        }
        assert required.issubset(set(full_report.keys()))

    def test_total_spend_is_positive(self, full_report):
        assert full_report["total_spend_usd"] > 0

    def test_top_3_has_exactly_3_entries(self, full_report):
        assert len(full_report["top_3_cost_drivers"]) == 3

    def test_daily_spikes_is_list(self, full_report):
        assert isinstance(full_report["daily_spikes"], list)

    def test_all_three_planted_spikes_in_report(self, full_report):
        """End-to-end: full pipeline must catch all 3 planted spikes."""
        planted = [s for s in full_report["daily_spikes"]
                   if s.get("is_anomaly")]
        assert len(planted) == 3, (
            f"Full pipeline should catch 3 planted spikes, got {len(planted)}"
        )

    def test_spend_by_service_has_all_services(self, full_report):
        assert len(full_report["spend_by_service"]) == 7

    def test_generated_at_is_string(self, full_report):
        assert isinstance(full_report["generated_at"], str)

    def test_total_spend_reasonable_range(self, full_report):
        """
        90 days of simulated spend should be between $2,000 and $6,000.
        This catches baseline cost constant changes that would silently
        break the savings recommendation calculations.
        """
        assert 2000 <= full_report["total_spend_usd"] <= 6000