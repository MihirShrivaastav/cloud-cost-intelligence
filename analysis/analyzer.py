import pandas as pd
import numpy as np
import json
from datetime import datetime

# ── Thresholds ──────────────────────────────────────────────
# Weekly WoW: flag only if delta is >= 35% (not 15% — too noisy)
# Daily z-score: flag only if 2.5+ std deviations above rolling mean
WOW_THRESHOLD = 0.35
ZSCORE_THRESHOLD = 2.5

SEVERITY_RULES = {
    "P1": {"wow": 0.60, "zscore": 3.5},
    "P2": {"wow": 0.35, "zscore": 2.5},
    "P3": {"wow": 0.20, "zscore": 2.0},
}


# ── Data loading ─────────────────────────────────────────────
def load_cost_data(filepath: str = "data/raw_costs.json") -> pd.DataFrame:
    """
    Load cost JSON into DataFrame.
    Mirrors how the real Lambda would read from S3 — same structure,
    so swapping mock → real is a one-line change later.
    """
    with open(filepath, "r") as f:
        records = json.load(f)
    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df["cost_usd"] = df["cost_usd"].astype(float)
    return df


# ── Weekly aggregation ───────────────────────────────────────
def compute_weekly_totals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate daily → weekly per service.
    Drops the current incomplete week to avoid false "cost crash" alerts
    (an incomplete week always looks like a massive drop).
    """
    df = df.copy()
    df["week"] = df["date"].dt.to_period("W")

    weekly = (
        df.groupby(["week", "service"])["cost_usd"]
        .sum()
        .reset_index()
        .rename(columns={"cost_usd": "weekly_cost"})
    )
    weekly["week_start"] = weekly["week"].apply(lambda w: w.start_time)

    # Drop incomplete current week
    latest_week = weekly["week"].max()
    weekly = weekly[weekly["week"] != latest_week]

    return weekly.sort_values(["service", "week_start"]).reset_index(drop=True)


# ── Weekly anomaly detection ─────────────────────────────────
def detect_weekly_anomalies(weekly: pd.DataFrame) -> pd.DataFrame:
    """
    Detect week-over-week cost trend anomalies.

    Uses WoW % delta only (dropped z-score at weekly level — it was
    generating too many false positives on normal seasonal variation).
    Also drops the FIRST week per service (NaN WoW — no prior week).
    """
    result_parts = []

    for service_name in weekly["service"].unique():
        svc = weekly[weekly["service"] == service_name].copy()
        svc = svc.sort_values("week_start").reset_index(drop=True)

        # Compute WoW delta
        svc["prev_cost"] = svc["weekly_cost"].shift(1)
        svc["wow_delta_pct"] = (
            (svc["weekly_cost"] - svc["prev_cost"]) / svc["prev_cost"]
        ).round(4)

        # Drop first row — no previous week, WoW is NaN
        svc = svc.dropna(subset=["wow_delta_pct"])

        result_parts.append(svc)

    weekly = pd.concat(result_parts, ignore_index=True)

    # Flag only genuine spikes (positive WoW above threshold)
    anomalies = weekly[weekly["wow_delta_pct"] >= WOW_THRESHOLD].copy()

    if anomalies.empty:
        return anomalies

    # Assign severity
    severities = []
    for _, row in anomalies.iterrows():
        wow = row["wow_delta_pct"]
        if wow >= SEVERITY_RULES["P1"]["wow"]:
            severities.append("P1")
        elif wow >= SEVERITY_RULES["P2"]["wow"]:
            severities.append("P2")
        else:
            severities.append("P3")
    anomalies["severity"] = severities

    # Build summary strings
    summaries = []
    for _, row in anomalies.iterrows():
        summaries.append(
            f"{row['service']}: ${row['weekly_cost']:.2f} week of "
            f"{str(row['week_start'])[:10]} "
            f"(+{row['wow_delta_pct']*100:.1f}% WoW) "
            f"[{row['severity']}]"
        )
    anomalies["summary"] = summaries

    return anomalies.reset_index(drop=True)


# ── Daily spike detection ────────────────────────────────────
def detect_daily_spikes(df: pd.DataFrame) -> pd.DataFrame:
    """
    Detect single-day cost explosions using a rolling z-score.

    Why daily in addition to weekly?
    A 3x spike on one day gets diluted in weekly aggregation to ~40%
    increase — easy to miss. Daily detection catches the exact day,
    which is what an engineer needs to investigate root cause.

    Uses a 14-day rolling window (shift(1) so today doesn't influence
    its own baseline). min_periods=5 means we need at least 5 days
    of history before flagging anything.
    """
    df = df.copy().sort_values(["service", "date"]).reset_index(drop=True)

    result_parts = []

    for service_name in df["service"].unique():
        svc = df[df["service"] == service_name].copy()
        svc = svc.sort_values("date").reset_index(drop=True)

        svc["rolling_mean"] = (
            svc["cost_usd"].shift(1).rolling(14, min_periods=5).mean()
        )
        svc["rolling_std"] = (
            svc["cost_usd"].shift(1).rolling(14, min_periods=5).std()
        )
        svc["daily_zscore"] = np.where(
            svc["rolling_std"] > 0,
            (svc["cost_usd"] - svc["rolling_mean"]) / svc["rolling_std"],
            0.0,
        ).round(4)

        result_parts.append(svc)

    df = pd.concat(result_parts, ignore_index=True)

    # Only flag positive spikes above threshold
    spikes = df[df["daily_zscore"] >= ZSCORE_THRESHOLD].copy()
    spikes = spikes.reset_index(drop=True)

    if spikes.empty:
        return spikes

    # Severity
    severities = []
    for _, row in spikes.iterrows():
        z = row["daily_zscore"]
        if z >= SEVERITY_RULES["P1"]["zscore"]:
            severities.append("P1")
        elif z >= SEVERITY_RULES["P2"]["zscore"]:
            severities.append("P2")
        else:
            severities.append("P3")
    spikes["severity"] = severities

    # Summary strings
    summaries = []
    for _, row in spikes.iterrows():
        summaries.append(
            f"{row['service']}: ${row['cost_usd']:.2f} on "
            f"{str(row['date'])[:10]} "
            f"(daily z={row['daily_zscore']:.2f}) "
            f"[{row['severity']}]"
        )
    spikes["summary"] = summaries

    return spikes[
        ["date", "service", "cost_usd", "daily_zscore",
         "severity", "summary", "is_anomaly"]
    ].reset_index(drop=True)


# ── Master report ────────────────────────────────────────────
def generate_report(filepath: str = "data/raw_costs.json") -> dict:
    """
    Runs the full pipeline and returns a structured dict.
    This is the single function Lambda calls.
    Dashboard and Slack notifier both consume this dict.
    """
    df = load_cost_data(filepath)
    weekly = compute_weekly_totals(df)
    weekly_anomalies = detect_weekly_anomalies(weekly)
    daily_spikes = detect_daily_spikes(df)

    total_spend = df["cost_usd"].sum()
    spend_by_service = (
        df.groupby("service")["cost_usd"]
        .sum()
        .sort_values(ascending=False)
        .round(2)
        .to_dict()
    )

    return {
        "generated_at": datetime.now().isoformat(),
        "total_spend_usd": round(total_spend, 2),
        "spend_by_service": spend_by_service,
        "top_3_cost_drivers": list(spend_by_service.items())[:3],
        "weekly_anomaly_count": len(weekly_anomalies),
        "daily_spike_count": len(daily_spikes),
        "weekly_anomalies": weekly_anomalies.to_dict(orient="records")
            if not weekly_anomalies.empty else [],
        "daily_spikes": daily_spikes.to_dict(orient="records")
            if not daily_spikes.empty else [],
        "weekly_data": weekly.to_dict(orient="records"),
    }


# ── CLI output ───────────────────────────────────────────────
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

    print(f"Daily spikes detected  : {report['daily_spike_count']}")
    print(f"Weekly trend anomalies : {report['weekly_anomaly_count']}")
    print()

    if report["daily_spikes"]:
        print("── Daily spikes (should catch all 3 planted) ──")
        for a in report["daily_spikes"]:
            planted = "  ← PLANTED ✓" if a.get("is_anomaly") else ""
            print(f"  {a['summary']}{planted}")
    else:
        print("── No daily spikes detected ──")
    print()

    if report["weekly_anomalies"]:
        print("── Weekly trend anomalies ──")
        for a in report["weekly_anomalies"]:
            print(f"  {a['summary']}")