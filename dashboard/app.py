import sys
import os
sys.path.append(
    os.path.join(os.path.dirname(__file__), "..")
)

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd

from analysis.analyzer import generate_report
from ingestion.mock_data import save_mock_data


if not os.path.exists("data/raw_costs.json"):
    save_mock_data()

# ── Page config ───────────────────────────────────────────────

st.set_page_config(
    page_title="CloudCostBot - Dashboard",
    page_icon="▣",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Design tokens ────────────────────────────────────────────
BG = "#0a0c10"
SURFACE = "#12151c"
LINE = "#1f2430"
TEXT = "#e6e9ef"
MUTED = "#6b7280"
ACCENT = "#f0b429"
CRITICAL = "#e25555"
WARNING = "#e0a23c"
OK = "#3fb68b"
SEV_COLORS = {"P1": CRITICAL, "P2": WARNING, "P3": OK}

# ── Custom CSS ────────────────────────────────────────────────

st.markdown(f"""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&
family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">

<style>
    html, body, [class*="css"] {{
        font-family: 'Inter', sans-serif;
    }}
    .main, .stApp {{ background-color: {BG}; }}

    /* Kill default Streamlit padding bloat */
    .block-container {{ padding-top: 4rem; padding-bottom: 3rem; }}

    /* ── Header ── */
    .lc-title {{
        font-family: 'JetBrains Mono', monospace;
        font-size: 1.6rem;
        font-weight: 700;
        color: {TEXT};
        letter-spacing: -0.02em;
        margin-bottom: 0;
        text-align: center;
    }}
    .lc-subtitle {{
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.78rem;
        color: {MUTED};
        margin-top: 0.25rem;
        letter-spacing: 0.02em;
        text-align: center;
    }}

    /* ── Section labels ── */
    .lc-section {{
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.72rem;
        font-weight: 600;
        color: {MUTED};
        text-transform: uppercase;
        letter-spacing: 0.18em;
        margin: 2.25rem 0 0.9rem 0;
        padding-bottom: 0.5rem;
        border-bottom: 1px solid {LINE};
    }}

    /* ── Ledger row (KPI / recommendations) ── */
    .lc-row {{
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        padding: 0.85rem 0;
        border-bottom: 1px solid {LINE};
    }}
    .lc-row:first-child {{ border-top: 1px solid {LINE}; }}
    .lc-row-label {{
        font-size: 0.85rem;
        color: {MUTED};
        font-weight: 500;
    }}
    .lc-row-value {{
        font-family: 'JetBrains Mono', monospace;
        font-size: 1.05rem;
        font-weight: 600;
        color: {TEXT};
        text-align: right;
    }}
    .lc-row-delta {{
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.78rem;
        color: {MUTED};
        margin-left: 0.6rem;
    }}
    .lc-delta-up {{ color: {CRITICAL}; }}
    .lc-delta-down {{ color: {OK}; }}

    /* ── Anomaly entries ── */
    .lc-anomaly {{
        display: flex;
        gap: 0.75rem;
        padding: 0.6rem 0;
        border-bottom: 1px solid {LINE};
        font-size: 0.85rem;
        align-items: flex-start;
    }}
    .lc-anomaly:first-child {{ border-top: 1px solid {LINE}; }}
    .lc-tag {{
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.68rem;
        font-weight: 700;
        padding: 0.15rem 0.45rem;
        border: 1px solid currentColor;
        border-radius: 2px;
        white-space: nowrap;
        letter-spacing: 0.05em;
        flex-shrink: 0;
        margin-top: 0.05rem;
    }}
    .lc-anomaly-text {{ color: {TEXT}; line-height: 1.5; }}

    /* ── Recommendation rows ── */
    .lc-rec {{
        border: 1px solid {LINE};
        padding: 1rem 1.1rem;
        height: 100%;
    }}
    .lc-rec-service {{
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.72rem;
        font-weight: 600;
        color: {ACCENT};
        text-transform: uppercase;
        letter-spacing: 0.12em;
        margin-bottom: 0.6rem;
    }}
    .lc-rec-tip {{
        font-size: 0.85rem;
        color: {TEXT};
        line-height: 1.55;
        margin-bottom: 0.75rem;
    }}
    .lc-rec-saving {{
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.8rem;
        color: {OK};
        border-top: 1px solid {LINE};
        padding-top: 0.6rem;
    }}

    /* ── Sidebar ── */
    section[data-testid="stSidebar"] {{
        background-color: {SURFACE};
        border-right: 1px solid {LINE};
    }}
    section[data-testid="stSidebar"] * {{ color: {TEXT}; }}
    .lc-sidebar-title {{
        font-family: 'JetBrains Mono', monospace;
        font-weight: 700;
        font-size: 1rem;
        letter-spacing: -0.01em;
    }}
    .lc-sidebar-meta {{
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.7rem;
        color: {MUTED};
        line-height: 1.7;
    }}

    /* ── Footer ── */
    .lc-footer {{
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.7rem;
        color: {MUTED};
        text-align: center;
        letter-spacing: 0.05em;
        padding-top: 1.5rem;
    }}

    hr {{ border-color: {LINE}; }}
</style>
""", unsafe_allow_html=True)


# ── Plotly base template ───────────────────────────────────────
PLOTLY_LAYOUT = dict(
    paper_bgcolor=BG,
    plot_bgcolor=BG,
    font=dict(family="Inter, sans-serif", color=MUTED, size=12),
    margin=dict(l=0, r=0, t=10, b=0),
    xaxis=dict(showgrid=False, linecolor=LINE, tickfont=dict(color=MUTED)),
    yaxis=dict(showgrid=True, gridcolor=LINE, zeroline=False,
               tickfont=dict(color=MUTED)),
)


# ── Data loading with caching ─────────────────────────────────

@st.cache_data(ttl=300)
def load_report():
    return generate_report()


@st.cache_data(ttl=300)
def load_weekly_df(report):
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
    st.markdown(
        '<div class="lc-sidebar-title">CloudCostBot</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="lc-sidebar-meta">v1.0 · AWS Cost Explorer</div>',
        unsafe_allow_html=True,
    )
    st.markdown("---")

    st.markdown(
        '<div class="lc-section" style="margin-top:0">Filters</div>',
        unsafe_allow_html=True,
    )
    selected_services = st.multiselect(
        "Services",
        options=all_services,
        default=all_services,
        label_visibility="collapsed",
    )

    st.markdown(
        '<div class="lc-section">Detection</div>',
        unsafe_allow_html=True,
    )
    st.markdown("""
    <div class="lc-sidebar-meta">
    METHODS<br>
    &nbsp;&nbsp;daily z-score (14d rolling)<br>
    &nbsp;&nbsp;weekly WoW % delta<br><br>
    SEVERITY<br>
    &nbsp;&nbsp;P1 — critical spike<br>
    &nbsp;&nbsp;P2 — elevated spend<br>
    &nbsp;&nbsp;P3 — minor anomaly
    </div>
    """, unsafe_allow_html=True)

    st.markdown(
        '<div class="lc-section">Stack</div>',
        unsafe_allow_html=True,
    )
    st.markdown("""
    <div class="lc-sidebar-meta">
    Python 3.11 · Pandas<br>
    AWS Cost Explorer API<br>
    Plotly · Streamlit
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")
    if st.button("Refresh data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()


# ── Header ────────────────────────────────────────────────────
st.markdown('<div class="lc-title">CloudCostBot - Dashboard</div>',
            unsafe_allow_html=True)
st.markdown(
    f'<div class="lc-subtitle">'
    f'LAST UPDATED {report["generated_at"][:19]}  ·  '
    f'90-DAY WINDOW  ·  '
    f'{len(all_services)} SERVICES MONITORED'
    f'</div>',
    unsafe_allow_html=True,
)


# ── KPI ledger row ────────────────────────────────────────────

top_service, top_cost = report["top_3_cost_drivers"][0]
avg_daily = report["total_spend_usd"] / 90
top_short = top_service.replace("Amazon ", "").replace("AWS ", "")

st.markdown('<div class="lc-section">Overview</div>', unsafe_allow_html=True)

kpi_rows = f"""
<div class="lc-row">
    <span class="lc-row-label">Total spend (90d)</span>
    <span class="lc-row-value">${report['total_spend_usd']:,.2f}</span>
</div>
<div class="lc-row">
    <span class="lc-row-label">Average daily spend</span>
    <span class="lc-row-value">${avg_daily:,.2f}</span>
</div>
<div class="lc-row">
    <span class="lc-row-label">Top cost driver</span>
    <span class="lc-row-value">{top_short}
        <span class="lc-row-delta">${top_cost:,.2f}</span>
    </span>
</div>
<div class="lc-row">
    <span class="lc-row-label">Daily spikes detected</span>
    <span class="lc-row-value">{report['daily_spike_count']}
        <span class="lc-row-delta lc-delta-up">anomalies</span>
    </span>
</div>
"""
st.markdown(kpi_rows, unsafe_allow_html=True)


# ── Filter weekly data ────────────────────────────────────────
filtered_df = weekly_df[weekly_df["service"].isin(selected_services)]


# ── Chart 1: Total spend trend over time ─────────────────────

st.markdown('<div class="lc-section">Weekly Spend Trend</div>',
            unsafe_allow_html=True)

trend_df = (
    filtered_df.groupby("week_start")["weekly_cost"]
    .sum()
    .reset_index()
    .rename(columns={"weekly_cost": "total_weekly_cost"})
)

fig_trend = go.Figure()
fig_trend.add_trace(go.Scatter(
    x=trend_df["week_start"],
    y=trend_df["total_weekly_cost"],
    mode="lines",
    line=dict(width=2, color=ACCENT),
    fill="tozeroy",
    fillcolor="rgba(240, 180, 41, 0.08)",
    hovertemplate="%{x|%b %d}<br>$%{y:,.2f}<extra></extra>",
))
fig_trend.update_layout(
    **PLOTLY_LAYOUT,
    height=280,
    hovermode="x unified",
    showlegend=False,
    yaxis_title=None,
    xaxis_title=None,
)
st.plotly_chart(fig_trend, use_container_width=True)


# ── Chart 2: Per-service breakdown ───────────────────────────

st.markdown('<div class="lc-section">Spend by Service (Weekly)</div>',
            unsafe_allow_html=True)

SERVICE_PALETTE = [
    "#f0b429", "#3fb68b", "#5b8def", "#e25555",
    "#9b7ede", "#4dd0e1", "#e08e3e",
]

fig_bar = px.bar(
    filtered_df,
    x="week_start",
    y="weekly_cost",
    color="service",
    labels={"week_start": "", "weekly_cost": "", "service": "Service"},
    color_discrete_sequence=SERVICE_PALETTE,
)
fig_bar.update_layout(
    **PLOTLY_LAYOUT,
    height=320,
    hovermode="x unified",
    barmode="stack",
    legend=dict(
        orientation="h",
        yanchor="bottom",
        y=1.02,
        xanchor="right",
        x=1,
        font=dict(color=MUTED, size=11),
        title=None,
    ),
)
st.plotly_chart(fig_bar, use_container_width=True)


# ── Two column layout: Anomalies + Cost distribution ─────────
col_left, col_right = st.columns([1.2, 0.8])

with col_left:
    st.markdown('<div class="lc-section">Anomaly Timeline</div>',
                unsafe_allow_html=True)

    if report["daily_spikes"]:
        spikes_df = pd.DataFrame(report["daily_spikes"])
        spikes_df["date"] = pd.to_datetime(spikes_df["date"])
        spikes_df = spikes_df[spikes_df["service"].isin(selected_services)]

        fig_scatter = px.scatter(
            spikes_df,
            x="date",
            y="service",
            size="cost_usd",
            color="severity",
            hover_data=["cost_usd", "daily_zscore", "summary"],
            color_discrete_map=SEV_COLORS,
            labels={"date": "", "service": ""},
        )
        fig_scatter.update_layout(
            **PLOTLY_LAYOUT,
            height=300,
            legend=dict(title=None, font=dict(color=MUTED, size=11)),
        )
        st.plotly_chart(fig_scatter, use_container_width=True)
    else:
        st.markdown(
            f'<div style="color:{OK};font-family:JetBrains Mono,monospace;'
            f'font-size:0.85rem;padding:1rem 0;">'
            f'No anomalies detected in the selected period.</div>',
            unsafe_allow_html=True,
        )

with col_right:
    st.markdown('<div class="lc-section">Cost Distribution</div>',
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
        color_discrete_sequence=SERVICE_PALETTE,
        hole=0.55,
    )
    fig_pie.update_layout(
        **PLOTLY_LAYOUT,
        height=300,
        showlegend=True,
        legend=dict(font=dict(color=MUTED, size=10), title=None),
    )
    fig_pie.update_traces(
        textposition="inside",
        textinfo="percent",
        marker=dict(line=dict(color=BG, width=2)),
    )
    st.plotly_chart(fig_pie, use_container_width=True)


# ── Anomaly detail entries ────────────────────────────────────

st.markdown('<div class="lc-section">Anomaly Detail</div>',
            unsafe_allow_html=True)

all_anomalies = report["daily_spikes"]
relevant = [a for a in all_anomalies if a["service"] in selected_services]

if relevant:
    order = {"P1": 0, "P2": 1, "P3": 2}
    relevant.sort(key=lambda a: order.get(a["severity"], 3))
    rows = ""
    for a in relevant:
        sev = a["severity"]
        color = SEV_COLORS.get(sev, MUTED)
        rows += (
            f'<div class="lc-anomaly">'
            f'<span class="lc-tag" style="color:{color}">{sev}</span>'
            f'<span class="lc-anomaly-text">{a["summary"]}</span>'
            f'</div>'
        )
    st.markdown(rows, unsafe_allow_html=True)
else:
    st.markdown(
        f'<div style="color:{OK};font-family:JetBrains Mono,monospace;'
        f'font-size:0.85rem;padding:1rem 0;">'
        f'No anomalies detected.</div>',
        unsafe_allow_html=True,
    )


# ── Savings recommendations ───────────────────────────────────

st.markdown('<div class="lc-section">Savings Recommendations</div>',
            unsafe_allow_html=True)

service_tips = {
    "Amazon EC2":
        ("Review EC2 instance sizes — Reserved Instances for steady "
         "workloads save up to 72%.", "$200-400/mo potential saving"),
    "Amazon RDS":
        ("Consider Aurora Serverless for variable workloads or "
         "right-size your RDS instance class.",
         "$100-250/mo potential saving"),
    "Amazon S3":
        ("Enable S3 Intelligent-Tiering for infrequently accessed "
         "data.", "$20-80/mo potential saving"),
    "AWS Data Transfer":
        ("Use VPC endpoints to reduce cross-region egress costs.",
         "$30-100/mo potential saving"),
    "Amazon CloudFront":
        ("Audit unused distributions and optimize cache TTLs.",
         "$10-50/mo potential saving"),
    "Amazon DynamoDB":
        ("Switch to on-demand pricing if traffic is unpredictable.",
         "$15-60/mo potential saving"),
    "AWS Lambda":
        ("Right-size Lambda memory allocation — less memory often "
         "means lower cost and similar duration.",
         "$5-30/mo potential saving"),
}

rec_cols = st.columns(3)
top_services = [s for s, _ in report["top_3_cost_drivers"]
                if s in selected_services]

for i, svc in enumerate(top_services[:3]):
    tip, saving = service_tips.get(svc, ("Review usage patterns.", "Variable"))
    short = svc.replace("Amazon ", "").replace("AWS ", "")
    with rec_cols[i]:
        st.markdown(f"""
<div class="lc-rec">
  <div class="lc-rec-service">{short}</div>
  <div class="lc-rec-tip">{tip}</div>
  <div class="lc-rec-saving">{saving}</div>
</div>
""", unsafe_allow_html=True)


# ── Footer ────────────────────────────────────────────────────
st.markdown(
    '<div class="lc-footer">CloudCostBot · '
    'PYTHON · AWS · PANDAS · PLOTLY · STREAMLIT · '
    'MIHIR SRIVASTAVA</div>',
    unsafe_allow_html=True,
)