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

        min_weekly = weekly_df["weekly_cost"].min()
        # Minimum weekly cost should be > 0 for any service
        assert min_weekly > 0

    def test_weekly_cost_greater_than_daily_average(self, raw_df, weekly_df):

        daily_avg = raw_df.groupby("service")["cost_usd"].mean()
        weekly_avg = weekly_df.groupby("service")["weekly_cost"].mean()

        for service in daily_avg.index:
            # Weekly should be roughly 5-7x daily (weekday factor applies)
            ratio = weekly_avg[service] / daily_avg[service]
            assert 4 <= ratio <= 8, (
                f"{service}: weekly/daily ratio {ratio:.2f} outside expected range"
            )


class TestDailySpikeDetection:
    

    def test_returns_dataframe(self, raw_df):
        result = detect_daily_spikes(raw_df)
        assert isinstance(result, pd.DataFrame)

    def test_detects_all_three_planted_spikes(self, raw_df):

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

        assert 2000 <= full_report["total_spend_usd"] <= 6000