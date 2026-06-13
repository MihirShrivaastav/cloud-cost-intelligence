import sys
import os


import streamlit as st
import plotly.express as px
import pandas as pd

from analysis.analyzer import generate_report
from ingestion.mock_data import save_mock_data


sys.path.append(
    os.path.join(os.path.dirname(__file__), "..")
)
if not os.path.exists("data/raw_costs.json"):
    save_mock_data()

# ── Page config ───────────────────────────────────────────────

st.set_page_config(
    page_title="Cloud Cost Intelligence",
    page_icon="☁️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────

st.markdown("""
<style>
    .main { background-color: #0e1117; }
    .metric-card {
        background: #1a1d27;
        border: 1px solid #2d3748;
        border-radius: 10px;
        padding: 1rem 1.25rem;
        margin-bottom: 0.5rem;
    }
    .metric-value {
        font-size: 2rem;
        font-weight: 600;
        color: #ffffff;
        margin: 0;
    }
    .metric-label {
        font-size: 0.8rem;
        color: #718096;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin: 0;
    }
    .anomaly-p1 {
        background: #2d1515;
        border-left: 3px solid #e53e3e;
        padding: 0.5rem 0.75rem;
        border-radius: 0 6px 6px 0;
        margin-bottom: 0.4rem;
        font-size: 0.85rem;
    }
    .anomaly-p2 {
        background: #2d2415;
        border-left: 3px solid #dd6b20;
        padding: 0.5rem 0.75rem;
        border-radius: 0 6px 6px 0;
        margin-bottom: 0.4rem;
        font-size: 0.85rem;
    }
    .anomaly-p3 {
        background: #1a2d1a;
        border-left: 3px solid #38a169;
        padding: 0.5rem 0.75rem;
        border-radius: 0 6px 6px 0;
        margin-bottom: 0.4rem;
        font-size: 0.85rem;
    }
    .section-header {
        font-size: 1rem;
        font-weight: 600;
        color: #a0aec0;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 0.75rem;
        margin-top: 1.5rem;
    }
    div[data-testid="stMetric"] {
        background: #1a1d27;
        border: 1px solid #2d3748;
        border-radius: 10px;
        padding: 1rem;
    }
</style>
""", unsafe_allow_html=True)


# ── Data loading with caching ─────────────────────────────────

@st.cache_data(ttl=300)
def load_report():
    return generate_report()


@st.cache_data(ttl=300)
def load_weekly_df(report):
    """
    Convert the weekly_data list from the report into a DataFrame.
    Cached separately so chart filters don't re-run the full pipeline.
    """
    df = pd.DataFrame(report["weekly_data"])
    df["week_start"] = pd.to_datetime(df["week_start"])
    df["weekly_cost"] = df["weekly_cost"].astype(float)
    return df


# ── Load data ─────────────────────────────────────────────────
report = load_report()
weekly_df = load_weekly_df(report)
all_services = sorted(weekly_df["service"].unique().tolist())


# ── Sidebar ───────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## ☁️ Cloud Cost Intelligence")
    st.markdown("---")

    st.markdown("### Filters")
    selected_services = st.multiselect(
        "Services",
        options=all_services,
        default=all_services,
        help="Select which AWS services to display"
    )

    st.markdown("---")
    st.markdown("### About")
    st.markdown("""
    **Stack**
    - Python 3.11
    - AWS Cost Explorer API
    - Pandas anomaly detection
    - Plotly + Streamlit

    **Detection methods**
    - Daily z-score (rolling 14d)
    - Weekly WoW % delta

    **Severity levels**
    - 🔴 P1 — Critical spike
    - 🟡 P2 — Elevated spend
    - 🟢 P3 — Minor anomaly
    """)

    st.markdown("---")
    if st.button("🔄 Refresh Data"):
        st.cache_data.clear()
        st.rerun()


# ── Header ────────────────────────────────────────────────────
st.markdown("# ☁️ Cloud Cost Intelligence Dashboard")
st.markdown(
    f"*Last updated: {report['generated_at'][:19]} · "
    f"Covering last 90 days · "
    f"{len(all_services)} AWS services monitored*"
)
st.markdown("---")


# ── KPI metric row ────────────────────────────────────────────

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric(
        label="💰 Total Spend (90d)",
        value=f"${report['total_spend_usd']:,.2f}",
    )
with col2:
    st.metric(
        label="🚨 Daily Spikes Detected",
        value=report["daily_spike_count"],
        delta=f"{report['daily_spike_count']} anomalies",
        delta_color="inverse",
    )
with col3:
    top_service, top_cost = report["top_3_cost_drivers"][0]
    st.metric(
        label="📈 Top Cost Driver",
        value=top_service.replace("Amazon ", "").replace("AWS ", ""),
        delta=f"${top_cost:,.2f}",
        delta_color="off",
    )
with col4:
    avg_daily = report["total_spend_usd"] / 90
    st.metric(
        label="📅 Avg Daily Spend",
        value=f"${avg_daily:,.2f}",
    )

st.markdown("---")


# ── Filter weekly data ────────────────────────────────────────
filtered_df = weekly_df[weekly_df["service"].isin(selected_services)]


# ── Chart 1: Total spend trend over time ─────────────────────

st.markdown('<p class="section-header">📈 Weekly Spend Trend</p>',
            unsafe_allow_html=True)

trend_df = (
    filtered_df.groupby("week_start")["weekly_cost"]
    .sum()
    .reset_index()
    .rename(columns={"weekly_cost": "total_weekly_cost"})
)

fig_trend = px.area(
    trend_df,
    x="week_start",
    y="total_weekly_cost",
    labels={"week_start": "Week", "total_weekly_cost": "Total Cost (USD)"},
    color_discrete_sequence=["#4299e1"],
    template="plotly_dark",
)
fig_trend.update_layout(
    paper_bgcolor="#0e1117",
    plot_bgcolor="#0e1117",
    margin=dict(l=0, r=0, t=10, b=0),
    height=300,
    hovermode="x unified",
    showlegend=False,
)
fig_trend.update_traces(
    fill="tozeroy",
    fillcolor="rgba(66, 153, 225, 0.15)",
    line=dict(width=2),
)
st.plotly_chart(fig_trend, use_container_width=True)


# ── Chart 2: Per-service breakdown ───────────────────────────

st.markdown('<p class="section-header">📊 Spend by Service (Weekly)</p>',
            unsafe_allow_html=True)

fig_bar = px.bar(
    filtered_df,
    x="week_start",
    y="weekly_cost",
    color="service",
    labels={
        "week_start": "Week", "weekly_cost": "Cost (USD)", "service": "Service"
        },
    template="plotly_dark",
    color_discrete_sequence=px.colors.qualitative.Set2,
)
fig_bar.update_layout(
    paper_bgcolor="#0e1117",
    plot_bgcolor="#0e1117",
    margin=dict(l=0, r=0, t=10, b=0),
    height=350,
    hovermode="x unified",
    legend=dict(
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="right",
        x=1,
    ),
)
st.plotly_chart(fig_bar, use_container_width=True)


# ── Two column layout: Anomalies + Service breakdown ─────────
col_left, col_right = st.columns([1.2, 0.8])

with col_left:
    # ── Chart 3: Anomaly timeline ─────────────────────────────

    st.markdown('<p class="section-header">🔍 Anomaly Timeline</p>',
                unsafe_allow_html=True)

    if report["daily_spikes"]:
        spikes_df = pd.DataFrame(report["daily_spikes"])
        spikes_df["date"] = pd.to_datetime(spikes_df["date"])
        spikes_df = spikes_df[spikes_df["service"].isin(selected_services)]

        color_map = {"P1": "#e53e3e", "P2": "#dd6b20", "P3": "#38a169"}

        fig_scatter = px.scatter(
            spikes_df,
            x="date",
            y="service",
            size="cost_usd",
            color="severity",
            hover_data=["cost_usd", "daily_zscore", "summary"],
            color_discrete_map=color_map,
            template="plotly_dark",
            labels={"date": "Date", "service": "Service",
                    "cost_usd": "Cost (USD)"},
        )
        fig_scatter.update_layout(
            paper_bgcolor="#0e1117",
            plot_bgcolor="#0e1117",
            margin=dict(l=0, r=0, t=10, b=0),
            height=300,
            legend=dict(title="Severity"),
        )
        st.plotly_chart(fig_scatter, use_container_width=True)
    else:
        st.success("✅ No anomalies detected in the selected period.")

with col_right:
    # ── Chart 4: Service cost share pie ──────────────────────

    st.markdown('<p class="section-header">🥧 Cost Distribution</p>',
                unsafe_allow_html=True)

    service_costs = {
        k: v for k, v in report["spend_by_service"].items()
        if k in selected_services
    }
    pie_df = pd.DataFrame(
        list(service_costs.items()),
        columns=["service", "cost"]
    )
    pie_df["service_short"] = pie_df["service"].str.replace(
        "Amazon ", "").str.replace("AWS ", "")

    fig_pie = px.pie(
        pie_df,
        values="cost",
        names="service_short",
        template="plotly_dark",
        color_discrete_sequence=px.colors.qualitative.Set2,
        hole=0.4,
    )
    fig_pie.update_layout(
        paper_bgcolor="#0e1117",
        plot_bgcolor="#0e1117",
        margin=dict(l=0, r=0, t=10, b=0),
        height=300,
        showlegend=True,
        legend=dict(font=dict(size=10)),
    )
    fig_pie.update_traces(textposition="inside", textinfo="percent")
    st.plotly_chart(fig_pie, use_container_width=True)


st.markdown("---")


# ── Anomaly detail cards ──────────────────────────────────────

st.markdown('<p class="section-header">🚨 Anomaly Detail</p>',
            unsafe_allow_html=True)

all_anomalies = report["daily_spikes"]
if all_anomalies:
    p1 = [a for a in all_anomalies if a["severity"] == "P1"
          and a["service"] in selected_services]
    p2 = [a for a in all_anomalies if a["severity"] == "P2"
          and a["service"] in selected_services]
    p3 = [a for a in all_anomalies if a["severity"] == "P3"
          and a["service"] in selected_services]
    for anomaly in p1:
        st.markdown(
            f'<div class="anomaly-p1">🔴 <strong>P1</strong> — '
            f'{anomaly["summary"]}</div>',
            unsafe_allow_html=True,
        )
    for anomaly in p2:
        st.markdown(
            f'<div class="anomaly-p2">🟡 <strong>P2</strong> — {
                anomaly["summary"]}</div>',
            unsafe_allow_html=True,
        )
    for anomaly in p3:
        st.markdown(
            f'<div class="anomaly-p3">🟢 <strong>P3</strong> — {
                anomaly["summary"]}</div>',
            unsafe_allow_html=True,
        )
else:
    st.success("✅ No anomalies detected.")


st.markdown("---")


# ── Savings recommendations ───────────────────────────────────
st.markdown('<p class="section-header">💡 Savings Recommendations</p>',
            unsafe_allow_html=True)

service_tips = {
    "Amazon EC2":
        ("Review EC2 instance sizes — Reserved Instances for steady "
         "workloads save up to 72%.", "$200–400/mo potential saving"),
    "Amazon RDS":
        ("Consider Aurora Serverless for variable workloads or "
         "right-size your RDS instance class.",
         "$100–250/mo potential saving"),
    "Amazon S3":
        ("Enable S3 Intelligent-Tiering for infrequently accessed "
         "data.", "$20–80/mo potential saving"),
    "AWS Data Transfer":
        ("Use VPC endpoints to reduce cross-region egress costs.",
         "$30–100/mo potential saving"),
    "Amazon CloudFront":
        ("Audit unused distributions and optimize cache TTLs.",
         "$10–50/mo potential saving"),
    "Amazon DynamoDB":
        ("Switch to on-demand pricing if traffic is unpredictable.",
         "$15–60/mo potential saving"),
    "AWS Lambda":
        ("Right-size Lambda memory allocation — less memory often "
         "means lower cost and similar duration.",
         "$5–30/mo potential saving"),
}

rec_cols = st.columns(3)
top_services = [s for s, _ in report["top_3_cost_drivers"]
                if s in selected_services]

for i, svc in enumerate(top_services[:3]):
    tip, saving = service_tips.get(svc, ("Review usage patterns.", "Variable"))
    short = svc.replace("Amazon ", "").replace("AWS ", "")
    with rec_cols[i]:
        st.markdown(f"""
<div class="metric-card">
  <p class="metric-label">{short}</p>
  <p style="font-size:0.85rem;color:#cbd5e0;margin:0.5rem 0">{tip}</p>
  <p style="font-size:0.8rem;color:#48bb78;margin:0">💚 {saving}</p>
</div>
""", unsafe_allow_html=True)


# ── Footer ────────────────────────────────────────────────────
st.markdown("---")
st.markdown(
    "<p style='text-align:center;color:#4a5568;font-size:0.8rem'>"
    "☁️ Cloud Cost Intelligence Dashboard · "
    "Built with Python, AWS, Pandas, Plotly & Streamlit · "
    "Mihir Srivastava</p>",
    unsafe_allow_html=True,
)
