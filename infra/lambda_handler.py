import os
import sys
import json

# Add parent directory so our modules are importable
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def handler(event, context):
    
    print(f"Lambda invoked | Request ID: {context.aws_request_id}")

    use_mock = os.getenv("USE_MOCK_DATA", "false").lower() == "true"

    if use_mock:
        # Local testing mode — use mock data, no AWS API calls
        print("Using mock data (USE_MOCK_DATA=true)")
        from ingestion.mock_data import save_mock_data
        save_mock_data("/tmp/raw_costs.json")
        from analysis.analyzer import generate_report
        report = generate_report("/tmp/raw_costs.json")
    else:
        # Production mode — call real AWS Cost Explorer API
        print("Fetching real AWS cost data...")
        from ingestion.aws_fetcher import fetch_and_save
        fetch_and_save(
            output_path=f"s3://{os.getenv('S3_BUCKET')}/raw/costs.json"
        )
        from analysis.analyzer import generate_report
        report = generate_report(
            f"s3://{os.getenv('S3_BUCKET')}/raw/costs.json"
        )

    # Send Slack notification
    from notifications.slack_notifier import send_slack_notification
    success = send_slack_notification(report)

    return {
        "statusCode": 200 if success else 500,
        "body": json.dumps({
            "message": "Cost analysis complete",
            "total_spend": report["total_spend_usd"],
            "anomalies_found": report["daily_spike_count"],
            "slack_sent": success,
        })
    }