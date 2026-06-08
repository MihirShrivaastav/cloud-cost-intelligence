import pandas as pd
import numpy as np
import json
from datetime import datetime


# Thresholds that define what counts as an anomaly.
# Why these numbers?
# - 20% WoW change: below this is normal business fluctuation.
#   Above it, something likely changed (new resource, runaway job).
# - Z-score > 2: means the value is outside 95% of normal range
#   for that service. Industry standard for anomaly detection.
WOW_THRESHOLD = 0.20       # 20% week-over-week change
ZSCORE_THRESHOLD = 2.0     # 2 standard deviations from mean

# Severity levels mirror how real on-call teams triage alerts.
# P1 = wake someone up. P2 = fix today. P3 = review this week.
SEVERITY_RULES = {
    "P1": {"wow": 0.50, "zscore": 3.5},   # >50% spike or extreme outlier
    "P2": {"wow": 0.30, "zscore": 2.5},   # >30% spike or strong outlier
    "P3": {"wow": 0.20, "zscore": 2.0},   # >20% spike or mild outlier
}


def load_cost_data(filepath: str = "data/raw_costs.json") -> pd.DataFrame:
    """
    Load cost data from JSON file into a DataFrame.

    Why read from JSON and not regenerate?
    In production the Lambda ingestor writes to S3, and the
    analysis Lambda reads from S3. This local file mirrors
    that exact pattern — decoupled read/write.
    """
    with open(filepath, "r") as f:
        records = json.load(f)

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df["cost_usd"] = df["cost_usd"].astype(float)
    return df

def compute_weekly_totals(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["week"] = df["date"].dt.to_period("W")

    weekly = (
        df.groupby(["week", "service"])["cost_usd"]
        .sum()
        .reset_index()
        .rename(columns={"cost_usd": "weekly_cost"})
    )
    weekly["week_start"] = weekly["week"].apply(lambda w: w.start_time)

    # Drop the most recent (current) week — it's incomplete.
    # An incomplete week always looks like a cost crash because
    # we only have 1-2 days of data instead of 7. This would
    # trigger false P1 alerts every single run. In production
    # the Lambda only runs on full completed weeks (Sunday night).
    latest_week = weekly["week"].max()
    weekly = weekly[weekly["week"] != latest_week]

    return weekly.sort_values(["service", "week_start"]).reset_index(drop=True)

def compute_wow_delta(weekly: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate week-over-week percentage change per service.

    Why per-service and not total?
    A 20% total increase could mean EC2 spiked 80% but S3 dropped.
    Aggregating hides the signal. Per-service deltas pinpoint
    exactly which resource is responsible — which is what an
    engineer actually needs to investigate.
    """
    weekly = weekly.copy()
    weekly["prev_week_cost"] = weekly.groupby("service")["weekly_cost"].shift(1)
    weekly["wow_delta_pct"] = (
        (weekly["weekly_cost"] - weekly["prev_week_cost"])
        / weekly["prev_week_cost"]
    ).round(4)
    return weekly

def compute_zscore(weekly: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate z-score for each week's cost relative to that
    service's historical mean and standard deviation.

    Why z-score on top of WoW delta?
    WoW delta misses gradual cost creep — if costs rise 15%
    every week for 6 weeks, no single week triggers the 20%
    threshold. Z-score catches this because the recent weeks
    will be far from the overall mean. Two methods = fewer
    missed anomalies (false negatives) and fewer false alarms.
    """
    # Compute mean and std per service, then merge back.
    # This approach avoids the groupby/apply column-drop bug
    # in Pandas 2.x where the groupby key gets lost after apply.
    stats = (
        weekly.groupby("service")["weekly_cost"]
        .agg(mean="mean", std="std")
        .reset_index()
    )
    weekly = weekly.merge(stats, on="service", how="left")
    weekly["std"] = weekly["std"].fillna(0)
    weekly["zscore"] = weekly.apply(
        lambda r: 0.0 if r["std"] == 0
        else round((r["weekly_cost"] - r["mean"]) / r["std"], 4),
        axis=1,
    )
    weekly = weekly.drop(columns=["mean", "std"])
    return weekly

def detect_daily_spikes(df: pd.DataFrame) -> pd.DataFrame:
    """
    Detect anomalies at the daily level before weekly aggregation
    smooths them out.

    Why daily AND weekly?
    Weekly totals are great for trend analysis but terrible at
    catching single-day explosions. A 3x spike on one day gets
    averaged into a week and looks like a 40% increase — easy
    to miss. Daily detection catches the exact day it happened,
    which is what an engineer needs to investigate the root cause.
    """
    df = df.copy().sort_values(["service", "date"]).reset_index(drop=True)

    # Compute rolling stats per service WITHOUT groupby+apply.
    # We iterate per service and concat — avoids the Pandas 2.x
    # bug where groupby key column disappears after apply().
    result_parts = []

    for service_name in df["service"].unique():
        svc_df = df[df["service"] == service_name].copy()
        svc_df = svc_df.sort_values("date").reset_index(drop=True)

        # Rolling 14-day mean/std using the PREVIOUS days only (shift(1))
        # so today's value doesn't influence its own baseline.
        svc_df["rolling_mean"] = (
            svc_df["cost_usd"]
            .shift(1)
            .rolling(14, min_periods=5)
            .mean()
        )
        svc_df["rolling_std"] = (
            svc_df["cost_usd"]
            .shift(1)
            .rolling(14, min_periods=5)
            .std()
        )
        svc_df["daily_zscore"] = (
            (svc_df["cost_usd"] - svc_df["rolling_mean"])
            / svc_df["rolling_std"].replace(0, float("nan"))
        ).round(4)

        result_parts.append(svc_df)

    df = pd.concat(result_parts, ignore_index=True)

    # Flag days where cost is more than 2.5 std deviations above normal
    spikes = df[df["daily_zscore"] > 2.5].copy().reset_index(drop=True)

    if spikes.empty:
        return spikes

    spikes["severity"] = spikes["daily_zscore"].apply(
        lambda z: "P1" if z > 3.5 else "P2" if z > 2.8 else "P3"
    )

    # Build summary strings using iterrows() — safe in all Pandas versions
    summaries = []
    for _, row in spikes.iterrows():
        summaries.append(
            f"{row['service']}: ${row['cost_usd']:.2f} on "
            f"{str(row['date'])[:10]} "
            f"(daily z={row['daily_zscore']:.2f}) [{row['severity']}]"
        )
    spikes["summary"] = summaries

    return spikes[
        ["date", "service", "cost_usd", "daily_zscore",
         "severity", "summary", "is_anomaly"]
    ].reset_index(drop=True)

def assign_severity(row) -> str:
    """
    Assign P1/P2/P3 severity based on how extreme the anomaly is.

    Why a severity system?
    Not all anomalies are equal. A 200% EC2 spike (P1) needs
    immediate action — it could mean a runaway instance burning
    money by the hour. A 22% S3 increase (P3) can wait for the
    weekly review. Severity lets the system prioritize correctly,
    exactly like a real alerting system (PagerDuty, OpsGenie).
    """
    wow = abs(row.get("wow_delta_pct", 0) or 0)
    z = abs(row.get("zscore", 0) or 0)

    if wow >= SEVERITY_RULES["P1"]["wow"] or z >= SEVERITY_RULES["P1"]["zscore"]:
        return "P1"
    elif wow >= SEVERITY_RULES["P2"]["wow"] or z >= SEVERITY_RULES["P2"]["zscore"]:
        return "P2"
    elif wow >= SEVERITY_RULES["P3"]["wow"] or z >= SEVERITY_RULES["P3"]["zscore"]:
        return "P3"
    return "normal"


def detect_anomalies(weekly: pd.DataFrame) -> pd.DataFrame:
    """
    Run the full anomaly detection pipeline and return
    only the flagged rows with severity assigned.

    This is the single function the Lambda will call.
    Everything else feeds into this.
    """
    weekly = compute_wow_delta(weekly)
    weekly = compute_zscore(weekly)

    weekly["severity"] = weekly.apply(assign_severity, axis=1)
    anomalies = weekly[weekly["severity"] != "normal"].copy()

    # Add a human-readable summary for each anomaly.
    # Why? The Slack notifier just reads this string directly —
    # no formatting logic needed in the notifications module.
    anomalies["summary"] = anomalies.apply(
        lambda r: (
            f"{r['service']}: ${r['weekly_cost']:.2f} this week "
            f"({'+' if r['wow_delta_pct'] >= 0 else ''}"
            f"{r['wow_delta_pct']*100:.1f}% WoW, "
            f"z={r['zscore']:.2f}) [{r['severity']}]"
        ),
        axis=1,
    )
    return anomalies.reset_index(drop=True)


def generate_report(filepath: str = "data/raw_costs.json") -> dict:
    """
    Master function — runs both weekly trend analysis and
    daily spike detection, merges results into one report.
    """
    df = load_cost_data(filepath)
    weekly = compute_weekly_totals(df)
    weekly_anomalies = detect_anomalies(weekly)
    daily_spikes = detect_daily_spikes(df)

    total_spend = df["cost_usd"].sum()
    spend_by_service = (
        df.groupby("service")["cost_usd"]
        .sum()
        .sort_values(ascending=False)
        .round(2)
        .to_dict()
    )
    top_3 = list(spend_by_service.items())[:3]

    report = {
        "generated_at": datetime.now().isoformat(),
        "total_spend_usd": round(total_spend, 2),
        "spend_by_service": spend_by_service,
        "top_3_cost_drivers": top_3,
        "weekly_anomaly_count": len(weekly_anomalies),
        "daily_spike_count": len(daily_spikes),
        "weekly_anomalies": weekly_anomalies[
            ["service", "week_start", "weekly_cost",
             "wow_delta_pct", "zscore", "severity", "summary"]
        ].to_dict(orient="records"),
        "daily_spikes": daily_spikes.to_dict(orient="records"),
        "weekly_data": weekly.to_dict(orient="records"),
    }
    return report

if __name__ == "__main__":
    report = generate_report()

    print("=" * 55)
    print("CLOUD COST INTELLIGENCE REPORT")
    print("=" * 55)
    print(f"Generated : {report['generated_at'][:19]}")
    print(f"Total spend (90 days): ${report['total_spend_usd']:,.2f}")
    print()
    print("Spend by service:")
    for svc, cost in report["spend_by_service"].items():
        bar = "█" * int(cost / 50)
        print(f"  {svc:<25} ${cost:>8.2f}  {bar}")
    print()
    print(f"Weekly trend anomalies : {report['weekly_anomaly_count']}")
    print(f"Daily spike anomalies  : {report['daily_spike_count']}")
    print()
    if report["daily_spikes"]:
        print("Daily spikes detected:")
        for a in report["daily_spikes"]:
            planted = " ← PLANTED SPIKE ✓" if a.get("is_anomaly") else ""
            print(f"  {a['summary']}{planted}")
    print()
    if report["weekly_anomalies"]:
        print("Weekly trend anomalies:")
        for a in report["weekly_anomalies"]:
            print(f"  {a['summary']}")