import os
import sys
import datetime
import subprocess
import pandas as pd
import plotly.express as px
import streamlit as st
from google.cloud import bigquery
from google.oauth2.credentials import Credentials

# --- Streamlit Page Configuration ---
st.set_page_config(
    page_title="Document Ingestion Insights",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# --- Configuration Constants ---
PROJECT_ID = os.environ.get("GCP_PROJECT") or os.environ.get("PROJECT_ID") or "scientific-glow-493210-i6"
BQ_DATASET = os.environ.get("BQ_DATASET", "document_processing")
BQ_TABLE = os.environ.get("BQ_TABLE", "metadata")

# --- Theme Setup ---
if "theme" not in st.session_state:
    st.session_state.theme = "dark"

def toggle_theme():
    st.session_state.theme = "light" if st.session_state.theme == "dark" else "dark"

IS_DARK = st.session_state.theme == "dark"

# --- CSS Styling Injection ---
# We inject custom CSS to apply our clean visual design system
CSS_VARIABLES = f"""
:root {{
    --bg: {"#09090b" if IS_DARK else "#ffffff"};
    --bg-subtle: {"#0c0c0f" if IS_DARK else "#f9fafb"};
    --card: {"#0c0c0f" if IS_DARK else "#ffffff"};
    --card-hover: {"#131316" if IS_DARK else "#f4f4f5"};
    --border: {"#1e1e24" if IS_DARK else "#e4e4e7"};
    --border-subtle: {"#16161a" if IS_DARK else "#f0f0f2"};
    --text: {"#fafafa" if IS_DARK else "#09090b"};
    --text-muted: #71717a;
    --text-dim: {"#52525b" if IS_DARK else "#a1a1aa"};
    --accent: #2563eb;
    --accent-muted: #1d4ed8;
    --green: {"#22c55e" if IS_DARK else "#16a34a"};
    --green-muted: {"rgba(34,197,94,0.12)" if IS_DARK else "rgba(22,163,74,0.08)"};
    --red: {"#ef4444" if IS_DARK else "#dc2626"};
    --red-muted: {"rgba(239,68,68,0.12)" if IS_DARK else "rgba(220,38,38,0.08)"};
    --shadow: {"none" if IS_DARK else "0 1px 3px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.03)"};
    --radius: 10px;
}}
"""

CUSTOM_CSS = """
<style>
/* Hide default streamlit headers/footers */
header[data-testid="stHeader"], #MainMenu, footer, [data-testid="stToolbar"],
[data-testid="stDecoration"], [data-testid="stStatusWidget"], .stDeployButton,
div[data-testid="stSidebarCollapsedControl"] {
    display: none !important;
}

/* Global resets and colors */
html, body, [data-testid="stAppViewContainer"], [data-testid="stApp"], .main, .block-container, section[data-testid="stMain"] {
    background-color: var(--bg) !important;
    color: var(--text) !important;
    font-family: 'Inter', -apple-system, sans-serif !important;
}

.block-container {
    padding: 2rem 2.5rem 3rem !important;
    max-width: 1360px !important;
}

/* Column margins */
[data-testid="stHorizontalBlock"] { gap: 1.25rem !important; }
[data-testid="stVerticalBlock"] > div:has(> [data-testid="stHorizontalBlock"]) {
    margin-bottom: 0.5rem !important;
}

/* Styled Card containers */
.metric-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1.25rem 1.4rem;
    box-shadow: var(--shadow);
}
.metric-label {
    font-size: 0.78rem;
    color: var(--text-muted);
    font-weight: 500;
}
.metric-value {
    font-size: 1.75rem;
    font-weight: 700;
    color: var(--text);
    letter-spacing: -0.03em;
    margin-top: 0.2rem;
}

.chart-wrap {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1.2rem;
    box-shadow: var(--shadow);
    margin-top: 1rem;
}
.chart-title {
    font-size: 0.82rem;
    font-weight: 600;
    color: var(--text);
}
.chart-subtitle {
    font-size: 0.72rem;
    color: var(--text-dim);
    margin-bottom: 0.8rem;
}

/* Data Table Styling */
.data-table-container {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1rem;
    box-shadow: var(--shadow);
    margin-top: 1.25rem;
    overflow-x: auto;
}
.data-table {
    width: 100%;
    border-collapse: separate;
    border-spacing: 0;
    font-size: 0.82rem;
}
.data-table th {
    text-align: left;
    padding: 0.75rem 0.8rem;
    color: var(--text-muted);
    font-weight: 600;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    border-bottom: 1px solid var(--border);
}
.data-table td {
    padding: 0.8rem 0.8rem;
    color: var(--text);
    border-bottom: 1px solid var(--border-subtle);
    vertical-align: middle;
}
.data-table tr:hover td {
    background-color: var(--card-hover);
}
.data-table tr:last-child td {
    border-bottom: none;
}

/* Status Badges */
.badge {
    display: inline-block;
    padding: 3px 8px;
    border-radius: 6px;
    font-size: 0.7rem;
    font-weight: 500;
    margin-right: 4px;
    margin-bottom: 2px;
}
.badge-blue {
    color: var(--accent);
    background: rgba(37, 99, 235, 0.1);
    border: 1px solid rgba(37, 99, 235, 0.15);
}
.badge-green {
    color: var(--green);
    background: var(--green-muted);
    border: 1px solid rgba(34, 197, 94, 0.15);
}
.badge-secondary {
    color: var(--text-muted);
    background: var(--bg-subtle);
    border: 1px solid var(--border);
}

/* Header branding */
.brand {
    display: flex;
    align-items: center;
    gap: 8px;
}
.brand-icon {
    font-size: 1.5rem;
    color: var(--accent);
}
.brand-name {
    font-size: 1.25rem;
    font-weight: 700;
    letter-spacing: -0.02em;
    color: var(--text);
}
.brand-subtitle {
    font-size: 0.75rem;
    color: var(--text-muted);
}
</style>
"""

st.markdown(f"<style>{CSS_VARIABLES}</style>", unsafe_allow_html=True)
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# --- BigQuery Credentials Helper ---
def get_bigquery_client(project):
    """Initializes BQ Client with fallback to active gcloud token if ADC is missing."""
    try:
        # Try Application Default Credentials (ADC)
        return bigquery.Client(project=project)
    except Exception as e:
        # Fallback to gcloud CLI access token extraction
        try:
            gcloud_paths = [
                "gcloud",
                r"C:\Users\GOLD\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd",
                r"C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
            ]
            token = None
            for path in gcloud_paths:
                try:
                    token = subprocess.check_output(
                        [path, "auth", "print-access-token"], 
                        stderr=subprocess.DEVNULL, 
                        text=True
                    ).strip()
                    if token:
                        break
                except Exception:
                    continue
            
            if not token:
                raise ValueError("No token obtained from gcloud.")
            
            credentials = Credentials(token)
            return bigquery.Client(project=project, credentials=credentials)
        except Exception as fallback_err:
            st.error(f"Failed to connect to Google Cloud: {fallback_err}. Showing simulated data.")
            return None

# --- Data Fetching ---
@st.cache_data(ttl=60)
def fetch_metadata(project_id, dataset, table):
    """Fetches document ingestion metadata from BigQuery, or returns mock data if BQ fails/is empty."""
    client = get_bigquery_client(project_id)
    if not client:
        return get_mock_dataframe(), True

    query = f"""
        SELECT filename, bucket, size, content_type, word_count, tags, process_timestamp
        FROM `{project_id}.{dataset}.{table}`
        ORDER BY process_timestamp DESC
    """
    try:
        query_job = client.query(query)
        rows = query_job.result()
        data = []
        for r in rows:
            data.append({
                "filename": r.filename,
                "bucket": r.bucket,
                "size": r.size,
                "content_type": r.content_type,
                "word_count": r.word_count,
                # Convert list-like objects or arrays
                "tags": list(r.tags) if r.tags is not None else [],
                "process_timestamp": r.process_timestamp
            })
        
        if not data:
            # Table is empty, return mock data
            return get_mock_dataframe(), True

        df = pd.DataFrame(data)
        # Ensure timestamp is datetime
        df["process_timestamp"] = pd.to_datetime(df["process_timestamp"])
        return df, False
    except Exception as e:
        st.warning(f"Unable to query BigQuery table: {e}. Falling back to simulated data.")
        return get_mock_dataframe(), True

def get_mock_dataframe():
    """Generates styled simulated data for fallback states."""
    mock_records = [
        {
            "filename": "integration_test_81d412c5.txt",
            "bucket": "scientific-glow-493210-i6-documents",
            "size": 98,
            "content_type": "text/plain",
            "word_count": 15,
            "tags": ["cloud", "document", "hello", "pipeline", "processing", "txt"],
            "process_timestamp": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=5)
        },
        {
            "filename": "financial_report_q1.pdf",
            "bucket": "scientific-glow-493210-i6-documents",
            "size": 1420500,
            "content_type": "application/pdf",
            "word_count": 1240,
            "tags": ["simulated-ocr", "pdf", "finance", "report"],
            "process_timestamp": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2)
        },
        {
            "filename": "invoice_2026_09.png",
            "bucket": "scientific-glow-493210-i6-documents",
            "size": 489300,
            "content_type": "image/png",
            "word_count": 124,
            "tags": ["simulated-ocr", "image", "invoice", "payment"],
            "process_timestamp": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
        },
        {
            "filename": "readme_quickstart.txt",
            "bucket": "scientific-glow-493210-i6-documents",
            "size": 2045,
            "content_type": "text/plain",
            "word_count": 348,
            "tags": ["readme", "txt", "guide", "setup"],
            "process_timestamp": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=3)
        },
        {
            "filename": "unstructured_notes.txt",
            "bucket": "scientific-glow-493210-i6-documents",
            "size": 560,
            "content_type": "text/plain",
            "word_count": 89,
            "tags": ["notes", "txt", "scratch"],
            "process_timestamp": datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)
        }
    ]
    df = pd.DataFrame(mock_records)
    df["process_timestamp"] = pd.to_datetime(df["process_timestamp"])
    return df

# --- Render KPI Metrics ---
def render_kpi_metrics(df):
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        # Total Docs
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Processed Documents</div>
            <div class="metric-value">{len(df)}</div>
        </div>
        """, unsafe_allow_html=True)
    with c2:
        # Total Word Count
        total_words = df["word_count"].sum()
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Total Word Count</div>
            <div class="metric-value">{total_words:,}</div>
        </div>
        """, unsafe_allow_html=True)
    with c3:
        # Avg Word Count
        avg_words = int(df["word_count"].mean()) if len(df) > 0 else 0
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Avg Words / Document</div>
            <div class="metric-value">{avg_words:,}</div>
        </div>
        """, unsafe_allow_html=True)
    with c4:
        # Unique Tags
        all_tags = []
        for tags_list in df["tags"]:
            all_tags.extend(tags_list)
        unique_tags_count = len(set(all_tags))
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">Unique Extracted Tags</div>
            <div class="metric-value">{unique_tags_count}</div>
        </div>
        """, unsafe_allow_html=True)

# --- Render Header ---
head_left, head_right = st.columns([6, 2])
with head_left:
    st.markdown(f"""
    <div class="brand">
        <span class="brand-icon">◆</span>
        <div>
            <span class="brand-name">Document Ingestion Insights</span>
            <div class="brand-subtitle">Serverless Event-Driven Processing Pipeline Insights</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
with head_right:
    # A row containing refresh button and theme toggle
    btn_col1, btn_col2 = st.columns(2)
    with btn_col1:
        if st.button("🔄 Refresh Data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
    with btn_col2:
        theme_label = "☀️ Light" if IS_DARK else "🌙 Dark"
        st.button(theme_label, on_click=toggle_theme, use_container_width=True)

st.markdown("<div style='height: 1rem;'></div>", unsafe_allow_html=True)

# --- Load Data ---
df, is_mocked = fetch_metadata(PROJECT_ID, BQ_DATASET, BQ_TABLE)

# Display simulated data warning banner if appropriate
if is_mocked:
    st.info("⚠️ Currently displaying **simulated dashboard data** because the BigQuery table is empty or credentials are not configured in the host environment.")

# --- Filter Controls ---
st.markdown("### Filters")
filter_col1, filter_col2 = st.columns([1, 1])

# Extract unique list of tags from dataframe
unique_tags = sorted(list(set([t for sublist in df["tags"] for t in sublist])))

with filter_col1:
    search_query = st.text_input("🔍 Search by filename", "").strip()

with filter_col2:
    selected_tags = st.multiselect("🏷️ Filter by tags", options=unique_tags)

# Apply filters
filtered_df = df.copy()

if search_query:
    filtered_df = filtered_df[filtered_df["filename"].str.contains(search_query, case=False)]

if selected_tags:
    filtered_df = filtered_df[filtered_df["tags"].apply(lambda x: any(t in x for t in selected_tags))]

# --- Metrics Row ---
render_kpi_metrics(filtered_df)

# --- Main Dashboard Visuals ---
left_panel, right_panel = st.columns([5, 3])

with left_panel:
    st.markdown("<h4 style='font-size:0.95rem; font-weight:600; margin-bottom: 0px;'>Processed Documents</h4>", unsafe_allow_html=True)
    
    if len(filtered_df) == 0:
        st.info("No documents found matching the selected filter criteria.")
    else:
        # Build beautiful HTML table
        table_rows = ""
        for _, row in filtered_df.iterrows():
            # Format timestamp
            date_formatted = row["process_timestamp"].strftime("%b %d, %Y, %H:%M")
            # Format size (Bytes vs KB vs MB)
            size_bytes = row["size"]
            if size_bytes < 1024:
                size_formatted = f"{size_bytes} B"
            elif size_bytes < 1048576:
                size_formatted = f"{size_bytes / 1024:.1f} KB"
            else:
                size_formatted = f"{size_bytes / 1048576:.1f} MB"
            
            # Format tags into HTML badges
            tags_html = ""
            for idx, tag in enumerate(row["tags"]):
                badge_class = "badge-blue" if idx % 2 == 0 else "badge-green"
                tags_html += f'<span class="badge {badge_class}">{tag}</span>'
            
            table_rows += f"""
            <tr>
                <td style="font-family:'JetBrains Mono', monospace; font-weight:600;">{row['filename']}</td>
                <td>{date_formatted}</td>
                <td>{tags_html}</td>
                <td style="text-align:right; font-family:'JetBrains Mono', monospace;">{row['word_count']:,}</td>
                <td style="text-align:right; font-family:'JetBrains Mono', monospace; color:var(--text-muted);">{size_formatted}</td>
            </tr>
            """
            
        table_html = f"""
        <div class="data-table-container">
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Filename</th>
                        <th>Processed Date</th>
                        <th>Tags</th>
                        <th style="text-align:right;">Word Count</th>
                        <th style="text-align:right;">Size</th>
                    </tr>
                </thead>
                <tbody>
                    {table_rows}
                </tbody>
            </table>
        </div>
        """
        st.markdown(table_html, unsafe_allow_html=True)

with right_panel:
    # 1. Plotly Theming config
    PLOT_LAYOUT = dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, sans-serif", color="#71717a" if not IS_DARK else "#a1a1aa", size=11),
        margin=dict(l=40, r=10, t=10, b=20),
        xaxis=dict(
            gridcolor="rgba(0,0,0,0.06)" if not IS_DARK else "rgba(255,255,255,0.06)",
            zerolinecolor="rgba(0,0,0,0.06)" if not IS_DARK else "rgba(255,255,255,0.06)",
            tickfont=dict(size=10, color="#71717a"),
        ),
        yaxis=dict(
            gridcolor="rgba(0,0,0,0.06)" if not IS_DARK else "rgba(255,255,255,0.06)",
            zerolinecolor="rgba(0,0,0,0.06)" if not IS_DARK else "rgba(255,255,255,0.06)",
            tickfont=dict(size=10, color="#71717a"),
        ),
    )

    # 2. Tag Frequency Chart
    st.markdown("""
    <div class="chart-wrap">
        <div class="chart-title">Top Tags Frequency</div>
        <div class="chart-subtitle">Distribution of automatically extracted tags</div>
    """, unsafe_allow_html=True)
    
    flat_tags = [t for sublist in filtered_df["tags"] for t in sublist]
    if not flat_tags:
        st.text("No tags available to chart.")
    else:
        tags_series = pd.Series(flat_tags).value_counts().reset_index()
        tags_series.columns = ["Tag", "Count"]
        tags_series = tags_series.head(8) # Top 8 tags

        fig_tags = px.bar(
            tags_series, 
            y="Tag", 
            x="Count", 
            orientation="h",
            color_discrete_sequence=["#2563eb"]
        )
        fig_tags.update_layout(**PLOT_LAYOUT)
        fig_tags.update_yaxes(autorange="reversed") # Highest count on top
        st.plotly_chart(fig_tags, use_container_width=True, config={"displayModeBar": False})
    
    st.markdown("</div>", unsafe_allow_html=True)

    # 3. Word Count Comparison Chart
    st.markdown("""
    <div class="chart-wrap">
        <div class="chart-title">Word Count by Document</div>
        <div class="chart-subtitle">Comparison of text volume per document</div>
    """, unsafe_allow_html=True)
    
    if filtered_df.empty:
        st.text("No documents available to chart.")
    else:
        fig_words = px.bar(
            filtered_df.head(10), # Show up to 10 docs
            x="filename",
            y="word_count",
            color_discrete_sequence=["#16a34a" if IS_DARK else "#22c55e"]
        )
        fig_words.update_layout(**PLOT_LAYOUT)
        fig_words.update_xaxes(tickangle=45, tickfont=dict(size=9))
        st.plotly_chart(fig_words, use_container_width=True, config={"displayModeBar": False})
    
    st.markdown("</div>", unsafe_allow_html=True)
