import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
import os

AWS_SERVICES = [
    "Amazon EC2",
    "Amazon S3",
    "Amazon RDS",
    "AWS Lambda",
    "Amazon CloudFront",
    "Amazon DynamoDB",
    "AWS Data Transfer",
]

BASELINE_COSTS = {
    "Amazon EC2":        18.0,
    "Amazon S3":          3.5,
    "Amazon RDS":        12.0,
    "AWS Lambda":         0.8,
    "Amazon CloudFront":  2.2,
    "Amazon DynamoDB":    1.5,
    "AWS Data Transfer":  4.0,
}


def generate_mock_cost_data(days: int = 90) -> pd.DataFrame:
    """
    Generate 90 days of realistic daily AWS cost data per service

    Returns a DataFrame with columns:
        date       - the calendar date
        service    - AWS service name
        cost_usd   - simulated daily cost
        is_anomaly - whether this row is a planted spike (for testing)
    """
    np.random.seed(42)  # Fixed seed = reproducible data every run

    end_date = datetime.today()
    dates = [end_date - timedelta(days=i) for i in range(days - 1, -1, -1)]

    rows = []

    for service in AWS_SERVICES:
        base = BASELINE_COSTS[service]

        for i, date in enumerate(dates):
            # Add natural day-to-day noise (±8% of baseline).
            # Real AWS costs fluctuate slightly every day due to
            # traffic patterns, data transfer volumes, etc.
            noise = np.random.normal(0, base * 0.08)

            # Add a weekly pattern — costs tend to be slightly
            # higher on weekdays (more compute) vs weekends.
            weekday_factor = 1.0 if date.weekday() < 5 else 0.85

            cost = max(0, (base + noise) * weekday_factor)

            # Plant exactly 3 anomaly spikes in the data.
            # Why? So we can verify our anomaly detector actually
            # catches them. This is how you write testable systems —
            # you know the ground truth and verify the output matches.
            is_anomaly = False
            if service == "Amazon S3" and i == 20:
                cost *= 3.4   # 240% spike — simulates accidental public bucket
                is_anomaly = True
            elif service == "Amazon EC2" and i == 55:
                cost *= 2.1   # 110% spike — simulates runaway auto-scaling
                is_anomaly = True
            elif service == "Amazon RDS" and i == 75:
                cost *= 2.8   # 180% spike — simulates forgotten large snapshot
                is_anomaly = True

            rows.append({
                "date": date.strftime("%Y-%m-%d"),
                "service": service,
                "cost_usd": round(cost, 4),
                "is_anomaly": is_anomaly,
            })

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["date", "service"]).reset_index(drop=True)
    return df


def save_mock_data(output_path: str = "data/raw_costs.json"):
    """
    Save the mock data to a local JSON file.

    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    df = generate_mock_cost_data()

    # Convert to the same structure AWS Cost Explorer API returns
    records = df.to_dict(orient="records")
    for r in records:
        r["date"] = str(r["date"])[:10]  # Keep date as string in JSON

    with open(output_path, "w") as f:
        json.dump(records, f, indent=2)

    print(f"Mock data saved to {output_path}")
    print(f"Total records: {len(records)}")
    print(f"Date range: {df['date'].min().date()} to {df['date'].max().date()}")
    print(f"Services: {df['service'].nunique()}")
    print(f"Planted anomalies: {df['is_anomaly'].sum()}")
    return df


if __name__ == "__main__":
    # Running this file directly generates and saves the mock data.
    df = save_mock_data()
    print("\nSample data (last 5 rows):")
    print(df.tail())