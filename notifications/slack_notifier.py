import os
import json
import requests
# from datetime import datetime
from dotenv import load_dotenv

load_dotenv()


def format_slack_message(report: dict) -> dict:

    total = report["total_spend_usd"]
    spike_count = report["daily_spike_count"]
    generated = report["generated_at"][:10]

    # ── Header block ──────────────────────────────────────────
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "☁️ Weekly Cloud Cost Intelligence Report",
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Generated on *{generated}* | "
                            f"Covering last 90 days",
                }
            ],
        },
        {"type": "divider"},
    ]

    # ── Summary section ───────────────────────────────────────
    blocks.append({
        "type": "section",
        "fields": [
            {
                "type": "mrkdwn",
                "text": f"*💰 Total Spend (90 days)*\n${total:,.2f}",
            },
            {
                "type": "mrkdwn",
                "text": f"*🚨 Anomalies Detected*\n"
                        f"{spike_count} spike(s) flagged",
            },
        ],
    })

    # ── Top 3 cost drivers ────────────────────────────────────

    top3_lines = "\n".join(
        [f"• *{svc}*: ${cost:,.2f}" for svc, cost in report[
            "top_3_cost_drivers"]]
    )
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*📊 Top 3 Cost Drivers*\n{top3_lines}",
        },
    })

    blocks.append({"type": "divider"})

    # ── Anomaly alerts ────────────────────────────────────────
    if report["daily_spikes"]:
        # Separate by severity so P1s are always shown first
        p1 = [a for a in report["daily_spikes"] if a["severity"] == "P1"]
        p2 = [a for a in report["daily_spikes"] if a["severity"] == "P2"]
        p3 = [a for a in report["daily_spikes"] if a["severity"] == "P3"]

        severity_emoji = {"P1": "🔴", "P2": "🟡", "P3": "🟢"}
        alert_lines = []

        for anomaly in p1 + p2 + p3:
            emoji = severity_emoji[anomaly["severity"]]
            alert_lines.append(f"{emoji} {anomaly['summary']}")

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*🔍 Cost Anomalies*\n" + "\n".join(alert_lines),
            },
        })
    else:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*✅ No anomalies detected this week*",
            },
        })

    blocks.append({"type": "divider"})

    # ── Savings recommendations ───────────────────────────────

    recommendations = _generate_recommendations(report["top_3_cost_drivers"])
    rec_lines = "\n".join([f"💡 {r}" for r in recommendations])

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*🛠 Savings Recommendations*\n{rec_lines}",
        },
    })

    # ── Footer ────────────────────────────────────────────────
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": "🤖 Cloud Cost Intelligence Dashboard | "
                        "Built with Python + AWS + Terraform",
            }
        ],
    })

    return {"blocks": blocks}


def _generate_recommendations(top3: list) -> list:

    recommendations = []
    service_tips = {
        "Amazon EC2": (
            "Review EC2 instance sizes — consider Reserved "
            "Instances for steady workloads (up to 72% savings)."
        ),
        "Amazon RDS": (
            "Check RDS instance class and consider Aurora "
            "Serverless for variable workloads."
        ),
        "Amazon S3": (
            "Enable S3 Intelligent-Tiering for infrequently "
            "accessed data (up to 40% storage savings)."
        ),
        "AWS Data Transfer": (
            "Review cross-region data transfer — use VPC "
            "endpoints to reduce egress costs."
        ),
        "Amazon CloudFront": (
            "Audit CloudFront distributions — remove unused "
            "distributions and optimize cache TTLs."
        ),
        "Amazon DynamoDB": (
            "Switch to DynamoDB on-demand pricing if traffic "
            "is unpredictable."
        ),
        "AWS Lambda": (
            "Review Lambda memory allocation — right-sizing "
            "memory often reduces both cost and duration."
        ),
    }

    for svc, _ in top3:
        tip = service_tips.get(svc)
        if tip:
            recommendations.append(tip)

    if not recommendations:
        recommendations.append(
            "Review your top services for Reserved Instance opportunities."
        )

    return recommendations


def send_slack_notification(report: dict) -> bool:

    webhook_url = os.getenv("SLACK_WEBHOOK_URL")

    if not webhook_url:
        print("ERROR: SLACK_WEBHOOK_URL not set in .env")
        return False

    message = format_slack_message(report)

    try:
        response = requests.post(
            webhook_url,
            data=json.dumps(message),
            headers={"Content-Type": "application/json"},
            timeout=10,
        )

        if response.status_code == 200:
            print("✅ Slack notification sent successfully")
            return True
        else:
            print(f"❌ Slack returned status {
                response.status_code}: {response.text}")
            return False

    except requests.exceptions.RequestException as e:
        print(f"❌ Request failed: {e}")
        return False


if __name__ == "__main__":
    # Import here to avoid circular imports when Lambda loads this module
    import sys
    sys.path.append(".")
    from analysis.analyzer import generate_report

    print("Generating report...")
    report = generate_report()

    print("Sending to Slack...")
    success = send_slack_notification(report)

    if success:
        print("Check your Slack workspace!")
    else:
        print("Failed — check your SLACK_WEBHOOK_URL in .env")
