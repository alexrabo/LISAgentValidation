"""
LIS AI Validation Demo — Streamlit Dashboard
"""
import json
import os
import subprocess
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
UI_DIR = Path(__file__).parent
RESULTS_FILE = UI_DIR / "verified_run_results.json"
DECISIONS_FILE = UI_DIR / "verified_run_decisions.json"

GCS_BUCKET = os.environ.get("GCS_BUCKET", "")
GCS_RECORDING_OBJECT = os.environ.get("GCS_RECORDING_OBJECT", "recording.cast")
GOOGLE_APPLICATION_CREDENTIALS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")

# Decision colours
COLOUR_HOLD = "#EF4444"       # red-500
COLOUR_RELEASE = "#22C55E"    # green-500
COLOUR_NORMAL = "#6B7280"     # gray-500
COLOUR_CONTAMINATION = "#F97316"  # orange-500
COLOUR_SWAP = "#8B5CF6"       # violet-500

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="LIS AI Validation",
    page_icon="🧪",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# CSS — clean clinical look
# ---------------------------------------------------------------------------
st.markdown("""
<style>
  .metric-card {
    background: #F9FAFB;
    border: 1px solid #E5E7EB;
    border-radius: 8px;
    padding: 1.2rem 1.5rem;
    text-align: center;
  }
  .metric-value { font-size: 2.4rem; font-weight: 700; line-height: 1.1; }
  .metric-label { font-size: 0.78rem; color: #6B7280; margin-top: 0.3rem; letter-spacing: 0.04em; text-transform: uppercase; }
  .verdict-pass { color: #16A34A; font-weight: 600; }
  .verdict-fail { color: #DC2626; font-weight: 600; }
  .badge-hold    { background:#FEE2E2; color:#991B1B; border-radius:4px; padding:2px 8px; font-size:0.8rem; font-weight:600; }
  .badge-release { background:#DCFCE7; color:#166534; border-radius:4px; padding:2px 8px; font-size:0.8rem; font-weight:600; }
  .section-header { font-size: 0.72rem; font-weight: 600; color: #9CA3AF; letter-spacing: 0.08em; text-transform: uppercase; margin-bottom: 0.5rem; }
  div[data-testid="stTab"] button { font-size: 0.9rem; }

  /* Step-view cards */
  .step-card {
    border: 1px solid #E5E7EB;
    border-radius: 8px;
    padding: 0.75rem 1rem;
    margin-bottom: 0.5rem;
    background: #FFFFFF;
    max-width: 860px;
  }
  .step-card.phase-standards { border-left: 4px solid #3B82F6; }
  .step-card.phase-triage    { border-left: 4px solid #6B7280; }
  .step-card.phase-triage.hold { border-left: 4px solid #EF4444; background: #FFF9F9; }
  .step-card.phase-triage.ckd  { border-left: 4px solid #8B5CF6; background: #FDFBFF; }
  .step-card.phase-audit     { border-left: 4px solid #F97316; }
  .step-tool  { font-family: monospace; font-size: 0.82rem; color: #374151; font-weight: 600; }
  .step-meta  { font-size: 0.75rem; color: #6B7280; margin-top: 0.15rem; }
  .step-detail { font-size: 0.82rem; color: #4B5563; margin-top: 0.35rem; }

  /* Hide Streamlit chrome */
  #MainMenu { visibility: hidden; }
  [data-testid="stDeployButton"] { display: none; }
  [data-testid="stToolbar"] { display: none; }
  header[data-testid="stHeader"] { background: transparent; }
  footer { visibility: hidden; }
  /* Hide sidebar — navigation lives in the top bar */
  [data-testid="stSidebar"] { display: none !important; }
  [data-testid="stSidebarCollapseButton"] { display: none !important; }
  [data-testid="collapsedControl"] { display: none !important; }
  /* Top bar */
  .topbar-title { font-size: 1.05rem; font-weight: 700; color: #111827; }
  .topbar-sub   { font-size: 0.75rem; color: #6B7280; margin-top: 0.1rem; }
  .topbar-meta  { font-size: 0.75rem; color: #9CA3AF; text-align: right; line-height: 1.6; }

  /* Copyright footer */
  .copyright {
    position: fixed;
    bottom: 0.6rem;
    right: 1rem;
    font-size: 0.68rem;
    color: #9CA3AF;
    pointer-events: none;
  }
</style>
<div class="copyright">© 2026 LIS AI Validation. All rights reserved.</div>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------
@st.cache_data
def load_results() -> dict:
    return json.loads(RESULTS_FILE.read_text())


@st.cache_data
def load_decisions() -> list[dict]:
    data = json.loads(DECISIONS_FILE.read_text())
    return data["specimens"]


@st.cache_data(ttl=300)
def fetch_recording_cast() -> str | None:
    """Fetch recording.cast from GCS. Returns content as string or None on failure."""
    if not GCS_BUCKET:
        return None
    try:
        from google.cloud import storage  # type: ignore
        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET)
        blob = bucket.blob(GCS_RECORDING_OBJECT)
        return blob.download_as_text()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Top bar
# ---------------------------------------------------------------------------
tb_left, tb_mid, tb_right = st.columns([3, 2, 2])

with tb_left:
    st.markdown(
        "<div class='topbar-title'>🧪 LIS AI Validation</div>"
        "<div class='topbar-sub'>CLSI EP33 · Two-layer agent validation framework</div>",
        unsafe_allow_html=True,
    )

with tb_mid:
    mode = st.selectbox(
        "Mode",
        ["Demo", "Harbor"],
        index=0,
        help="Demo: pre-computed results from a verified run.\nHarbor: run via TerminalBench.",
    )

with tb_right:
    st.markdown(
        "<div class='topbar-meta'>"
        "Layer 1 — Decision quality &nbsp;·&nbsp; Layer 2 — Reasoning provenance<br>"
        "Specimens: S100–S110 &nbsp;·&nbsp; 11 total"
        "</div>",
        unsafe_allow_html=True,
    )

st.divider()


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
results = load_results()
decisions = load_decisions()
agg = results["metrics"]["aggregate"]
provenance = results["provenance"]

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_results, tab_scatter, tab_replay, tab_about = st.tabs([
    "📋  Results Dashboard",
    "📊  Decision Space",
    "▶   Agent Replay",
    "ℹ️  About this Demo",
])


# ===========================================================================
# TAB 1 — Results Dashboard
# ===========================================================================
with tab_results:

    # --- Header ---
    overall_pass = results["passed"]
    verdict_class = "verdict-pass" if overall_pass else "verdict-fail"
    verdict_text = "VALIDATED ✅" if overall_pass else "FAILED ❌"
    st.markdown(
        f"<p class='section-header'>Overall verdict — "
        f"<span class='{verdict_class}'>{verdict_text}</span></p>",
        unsafe_allow_html=True,
    )

    # --- Layer 1 metric cards ---
    st.markdown("<p class='section-header'>Layer 1 — Decision quality</p>", unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)

    unsafe = int(agg["unsafe_release_count"])
    f1 = agg["f1"]
    fhr = agg["false_hold_rate"]
    prec = agg["precision"]
    recall = agg["recall"]

    c1.metric(
        label="F1 Score",
        value=f"{f1:.2f}",
        delta="Pass ✓" if f1 >= 0.80 else "Fail ✗",
        delta_color="normal" if f1 >= 0.80 else "inverse",
        help=(
            "F1 is the harmonic mean of Precision and Recall — it balances two competing risks: "
            "missing a bad specimen (low recall) and over-holding good ones (low precision). "
            "A score of 1.0 means every HOLD and RELEASE decision was correct. "
            "Pass threshold: ≥ 0.80."
        ),
    )
    c2.metric(
        label="Unsafe Releases",
        value=str(unsafe),
        delta="Pass ✓" if unsafe == 0 else f"Fail — {unsafe} unsafe",
        delta_color="normal" if unsafe == 0 else "inverse",
        help=(
            "The number of contaminated or swapped specimens that were incorrectly released. "
            "This is the primary patient safety gate — a single unsafe release means a wrong result "
            "may have been reported to a clinician. Zero is the only acceptable value. "
            "No amount of good precision or F1 compensates for a non-zero count here."
        ),
    )
    c3.metric(
        label="False Hold Rate",
        value=f"{fhr:.2f}",
        delta="Pass ✓" if fhr <= 0.34 else "Fail ✗",
        delta_color="normal" if fhr <= 0.34 else "inverse",
        help=(
            "The fraction of normal specimens that were incorrectly held for review. "
            "A high false hold rate disrupts lab workflow and delays reporting of legitimate results. "
            "This metric keeps the agent honest — it cannot simply HOLD everything to guarantee safety. "
            "Pass threshold: ≤ 0.34 (no more than 1 in 3 normal specimens incorrectly flagged)."
        ),
    )
    c4.metric(
        label="Precision",
        value=f"{prec:.2f}",
        help=(
            "Of all specimens the agent chose to HOLD, what fraction actually needed to be held? "
            "Precision = True Holds ÷ All Holds. "
            "Low precision means the agent is over-cautious — holding normal specimens unnecessarily, "
            "adding review workload without clinical benefit."
        ),
    )

    st.markdown("<br>", unsafe_allow_html=True)

    # Visible vs hidden split
    col_vis, col_hid = st.columns(2)
    for col, batch_key, label in [
        (col_vis, "visible", "Visible batch"),
        (col_hid, "hidden", "Hidden batch"),
    ]:
        m = results["metrics"][batch_key]
        col.markdown(f"<p class='section-header'>{label}</p>", unsafe_allow_html=True)
        col.markdown(
            f"Precision **{m['precision']:.2f}** · "
            f"Recall **{m['recall']:.2f}** · "
            f"F1 **{m['f1']:.2f}** · "
            f"Unsafe releases **{int(m['unsafe_release_count'])}**"
        )

    st.divider()

    # --- Per-specimen decisions table ---
    st.markdown("<p class='section-header'>Per-specimen decisions</p>", unsafe_allow_html=True)

    header_cols = st.columns([1, 1.1, 1.4, 1.1, 1.1, 2.2, 2.8])
    for col, h in zip(header_cols, ["Specimen", "Patient", "Decision", "Contam.", "Swap", "Category", "Hold reason"]):
        col.markdown(f"**{h}**")

    for spec in decisions:
        is_hold = spec["decision"] == "HOLD"
        cols = st.columns([1, 1.1, 1.4, 1.1, 1.1, 2.2, 2.8])
        badge = (
            "<span class='badge-hold'>HOLD</span>"
            if is_hold
            else "<span class='badge-release'>RELEASE</span>"
        )
        cols[0].write(spec["specimen_id"])
        cols[1].write(spec["patient_id"])
        cols[2].markdown(badge, unsafe_allow_html=True)
        cols[3].write(f"{spec['contamination_score']:.3f}")
        cols[4].write(f"{spec['swap_score']:.3f}")
        cols[5].write(spec["truth_category"])
        if is_hold:
            cols[6].write(spec.get("hold_reason", ""))

    # Expandable detail cards for each HOLD specimen
    hold_specs = [s for s in decisions if s["decision"] == "HOLD"]
    if hold_specs:
        st.markdown("<br><p class='section-header'>Hold explanations</p>", unsafe_allow_html=True)
        for spec in hold_specs:
            detail = spec.get("hold_detail", "")
            if not detail:
                continue
            label_map = {"CONTAMINATION": "🧪 EDTA Contamination", "SWAP": "🔀 Identity Swap"}
            icon_label = label_map.get(spec["truth_label"], "⚠️ Hold")
            with st.expander(f"{spec['specimen_id']} — {icon_label}"):
                st.markdown(detail)

    st.divider()

    # --- Layer 2 — Provenance ---
    st.markdown("<p class='section-header'>Layer 2 — Reasoning provenance (CLSI EP33)</p>", unsafe_allow_html=True)

    prov_overall = provenance["overall_verdict"]
    prov_class = "verdict-pass" if prov_overall == "PASS" else "verdict-fail"
    st.markdown(
        f"Knowledge graph: **{provenance['kg_version']}** · "
        f"Overall: <span class='{prov_class}'>{prov_overall}</span>",
        unsafe_allow_html=True,
    )

    for param in provenance["parameters"]:
        icon = "✅" if param["verdict"] == "graph-derived" else "❌"
        st.markdown(f"- **{param['display_name']}**: graph-derived {icon}")

    st.divider()

    # --- CKD S110 callout ---
    st.markdown("<p class='section-header'>CKD interference guard — S110</p>", unsafe_allow_html=True)
    st.info(
        "**S110** is a CKD patient with chronically elevated potassium (K 6.10 mmol/L) "
        "and preserved calcium (Ca 7.95 mg/dL). An agent using absolute thresholds would "
        "flag this as EDTA contamination and incorrectly HOLD it. This agent derived its "
        "delta-check divisor from CLSI EP33 and applied it as a *patient-relative* check: "
        "K is stable within this patient's own historical range, Ca is preserved. "
        "**Correct decision: RELEASE.**",
        icon="🔬",
    )


# ===========================================================================
# TAB 2 — Decision Space scatter
# ===========================================================================
with tab_scatter:

    st.markdown("<p class='section-header'>Contamination score vs identity swap score — all specimens</p>", unsafe_allow_html=True)
    st.caption(
        "Each point is one specimen. Threshold lines mark the decision boundary — "
        "values are not shown (proprietary KG parameters)."
    )

    # Build trace data grouped by truth label
    groups = {
        "NORMAL":        {"colour": COLOUR_NORMAL,        "symbol": "circle"},
        "CONTAMINATION": {"colour": COLOUR_CONTAMINATION, "symbol": "diamond"},
        "SWAP":          {"colour": COLOUR_SWAP,           "symbol": "star"},
    }

    fig = go.Figure()

    for label, style in groups.items():
        subset = [s for s in decisions if s["truth_label"] == label]
        if not subset:
            continue
        fig.add_trace(go.Scatter(
            x=[s["contamination_score"] for s in subset],
            y=[s["swap_score"] for s in subset],
            mode="markers+text",
            name=label.replace("_", " ").title(),
            text=[s["specimen_id"] for s in subset],
            textposition="top center",
            textfont=dict(size=11),
            marker=dict(
                size=14,
                color=style["colour"],
                symbol=style["symbol"],
                line=dict(width=1.5, color="white"),
            ),
            hovertemplate=(
                "<b>%{text}</b><br>"
                "Contamination: %{x:.3f}<br>"
                "Swap: %{y:.3f}<br>"
                f"Category: {label.replace('_', ' ').title()}"
                "<extra></extra>"
            ),
        ))

    # Threshold lines — no numeric labels (IP protection)
    CONTAM_THRESHOLD = 0.5   # not displayed
    SWAP_THRESHOLD = 0.3     # not displayed

    fig.add_shape(
        type="line",
        x0=CONTAM_THRESHOLD, x1=CONTAM_THRESHOLD,
        y0=0, y1=1.05,
        line=dict(color="#374151", width=1.5, dash="dash"),
    )
    fig.add_annotation(
        x=CONTAM_THRESHOLD, y=1.05,
        text="threshold", showarrow=False,
        font=dict(size=10, color="#374151"),
        xanchor="left", xshift=4,
    )

    fig.add_shape(
        type="line",
        x0=0, x1=1.6,
        y0=SWAP_THRESHOLD, y1=SWAP_THRESHOLD,
        line=dict(color="#374151", width=1.5, dash="dash"),
    )
    fig.add_annotation(
        x=1.55, y=SWAP_THRESHOLD,
        text="threshold", showarrow=False,
        font=dict(size=10, color="#374151"),
        yanchor="bottom", yshift=4,
    )

    # HOLD region shading
    fig.add_shape(
        type="rect",
        x0=CONTAM_THRESHOLD, x1=1.65,
        y0=0, y1=SWAP_THRESHOLD,
        fillcolor="rgba(239,68,68,0.05)",
        line=dict(width=0),
        layer="below",
    )
    fig.add_shape(
        type="rect",
        x0=0, x1=1.65,
        y0=SWAP_THRESHOLD, y1=1.05,
        fillcolor="rgba(239,68,68,0.05)",
        line=dict(width=0),
        layer="below",
    )

    fig.update_layout(
        xaxis_title="Contamination Score",
        yaxis_title="Identity Swap Score",
        xaxis=dict(range=[-0.05, 1.65], showgrid=True, gridcolor="#F3F4F6"),
        yaxis=dict(range=[-0.02, 1.08], showgrid=True, gridcolor="#F3F4F6"),
        plot_bgcolor="white",
        paper_bgcolor="white",
        legend=dict(orientation="h", y=-0.15),
        margin=dict(l=50, r=20, t=20, b=80),
        height=480,
        font=dict(family="Inter, sans-serif", size=12),
    )

    st.plotly_chart(fig, use_container_width=True)

    st.caption(
        "**Red shaded regions**: HOLD zone (score exceeds KG-derived threshold on either axis).  "
        "**S110** plots at (0, 0) — CKD patient correctly in the RELEASE zone despite elevated K."
    )


# ===========================================================================
# TAB 3 — Agent Replay
# ===========================================================================
REPLAY_STEPS = [
    {
        "tool": "query_knowledge",
        "specimen": None,
        "phase": "standards",
        "decision": None,
        "scores": None,
        "result": "CLSI EP33 graph retrieved",
        "detail": (
            "The agent reads the rules before touching any specimen. "
            "The server enforces this: <code>apply_autoverification</code> returns an error until "
            "<code>query_knowledge</code> has been called. The agent cannot skip the standards-reading step."
        ),
        "flag": None,
    },
    {
        "tool": "apply_autoverification",
        "specimen": "S100",
        "phase": "triage",
        "decision": "RELEASE",
        "scores": "contamination 0.000  ·  swap 0.021",
        "result": None,
        "detail": "Values within patient-relative delta-check range. No contamination or swap signature.",
        "flag": None,
    },
    {
        "tool": "apply_autoverification",
        "specimen": "S101",
        "phase": "triage",
        "decision": "HOLD",
        "scores": "contamination 1.500  ·  swap 0.000",
        "result": None,
        "detail": (
            "EDTA contamination. K elevated 1.5 SD above patient's own prior; "
            "Ca depressed simultaneously. Classic purple-top tube signature."
        ),
        "flag": "hold",
    },
    {
        "tool": "apply_autoverification",
        "specimen": "S102",
        "phase": "triage",
        "decision": "RELEASE",
        "scores": "contamination 0.030  ·  swap 0.000",
        "result": None,
        "detail": "Trace contamination score well below threshold. Released.",
        "flag": None,
    },
    {
        "tool": "apply_autoverification",
        "specimen": "S103",
        "phase": "triage",
        "decision": "RELEASE",
        "scores": "contamination 0.000  ·  swap 0.030",
        "result": None,
        "detail": "Low swap score — patient assignment is the better fit. Released.",
        "flag": None,
    },
    {
        "tool": "apply_autoverification",
        "specimen": "S104",
        "phase": "triage",
        "decision": "RELEASE",
        "scores": "contamination 0.021  ·  swap 0.000",
        "result": None,
        "detail": "Both scores near zero. Released.",
        "flag": None,
    },
    {
        "tool": "apply_autoverification",
        "specimen": "S105",
        "phase": "triage",
        "decision": "HOLD",
        "scores": "contamination 0.335  ·  swap 0.970",
        "result": None,
        "detail": (
            "Identity swap — swap pair with S106. "
            "Swapping their patient assignments reduces mismatch score by 0.97 SD. "
            "Both specimens held pending re-labelling."
        ),
        "flag": "hold",
    },
    {
        "tool": "apply_autoverification",
        "specimen": "S106",
        "phase": "triage",
        "decision": "HOLD",
        "scores": "contamination 0.000  ·  swap 0.970",
        "result": None,
        "detail": (
            "Identity swap — swap pair with S105. "
            "No contamination signature; the hold is driven entirely by pairwise swap evidence."
        ),
        "flag": "hold",
    },
    {
        "tool": "apply_autoverification",
        "specimen": "S107",
        "phase": "triage",
        "decision": "HOLD",
        "scores": "contamination 1.414  ·  swap 0.000",
        "result": None,
        "detail": (
            "EDTA contamination. K and Ca both deviate from patient prior by 1.41 SD. "
            "No swap component — the tube contents are wrong, not the label."
        ),
        "flag": "hold",
    },
    {
        "tool": "apply_autoverification",
        "specimen": "S108",
        "phase": "triage",
        "decision": "RELEASE",
        "scores": "contamination 0.000  ·  swap 0.000",
        "result": None,
        "detail": "Both scores zero. Released.",
        "flag": None,
    },
    {
        "tool": "apply_autoverification",
        "specimen": "S109",
        "phase": "triage",
        "decision": "RELEASE",
        "scores": "contamination 0.000  ·  swap 0.000",
        "result": None,
        "detail": "Both scores zero. Released.",
        "flag": None,
    },
    {
        "tool": "apply_autoverification",
        "specimen": "S110",
        "phase": "triage",
        "decision": "RELEASE",
        "scores": "contamination 0.000  ·  swap 0.000",
        "result": None,
        "detail": (
            "CKD patient — chronically elevated K (6.10 mmol/L). "
            "An absolute-threshold agent would flag this as contamination. "
            "The patient-relative delta check finds K stable within his own baseline. "
            "Correctly released."
        ),
        "flag": "ckd",
    },
    {
        "tool": "get_audit_log",
        "specimen": None,
        "phase": "audit",
        "decision": None,
        "scores": None,
        "result": "ALCOA+ audit trail verified — 13 events",
        "detail": (
            "Append-only log confirmed: every tool call timestamped, attributed to session ID, "
            "specimen values write-once. Provides the CAP/CLIA documentation trail."
        ),
        "flag": None,
    },
]


with tab_replay:

    st.markdown("<p class='section-header'>Agent terminal session — verified run</p>", unsafe_allow_html=True)
    st.caption(
        "Recording of Claude calling MCP tools against the LIMS server in real time. "
        "Run ID: `lis-swap-contamination-triage__HsPAVBJ` · Reward: 1.0 · Cost: $0.12"
    )

    cast_content = fetch_recording_cast()

    replay_view = st.radio(
        "View",
        ["Step view", "Terminal recording"],
        horizontal=True,
        label_visibility="collapsed",
    )
    st.markdown("<br>", unsafe_allow_html=True)

    # ------------------------------------------------------------------
    # STEP VIEW
    # ------------------------------------------------------------------
    if replay_view == "Step view":
        # Legend inline at top
        st.markdown(
            "<span class='badge-hold'>HOLD</span> &nbsp; specimen flagged for review &nbsp;&nbsp; "
            "<span class='badge-release'>RELEASE</span> &nbsp; safe to report &nbsp;&nbsp; "
            "<span style='display:inline-block;width:10px;height:10px;background:#8B5CF6;"
            "border-radius:2px;vertical-align:middle;margin-right:4px'></span>"
            "<span style='font-size:0.8rem;color:#4B5563'>CKD edge case</span>",
            unsafe_allow_html=True,
        )
        st.markdown("<br>", unsafe_allow_html=True)

        PHASE_LABELS = {
            "standards": ("📖", "Phase 1 — Standards retrieval"),
            "triage":    ("🧪", "Phase 2 — Specimen triage"),
            "audit":     ("📋", "Phase 3 — Audit verification"),
        }
        current_phase = None

        for i, step in enumerate(REPLAY_STEPS, 1):
            phase = step["phase"]
            if phase != current_phase:
                icon, label = PHASE_LABELS[phase]
                st.markdown(
                    f"<p class='section-header' style='margin-top:1rem'>{icon} {label}</p>",
                    unsafe_allow_html=True,
                )
                current_phase = phase

            flag = step.get("flag") or ""
            card_class = f"step-card phase-{phase} {flag}".strip()

            tool_line = f"{step['tool']}({step['specimen']})" if step["specimen"] else step["tool"]

            if step["decision"] == "HOLD":
                badge = "<span class='badge-hold'>HOLD</span>"
            elif step["decision"] == "RELEASE":
                badge = "<span class='badge-release'>RELEASE</span>"
            else:
                badge = "<span></span>"  # placeholder — keeps flex row intact, prevents markdown blank-line injection

            meta = step["scores"] or step["result"] or ""
            meta_html = f"<div class='step-meta'>{meta}</div>" if meta else ""

            st.markdown(
                f"""<div class="{card_class}">
                  <div style="display:flex;justify-content:space-between;align-items:flex-start">
                    <div>
                      <span class="step-tool">#{i} &nbsp; {tool_line}</span>
                      {meta_html}
                    </div>
                    {badge}
                  </div>
                  <div class="step-detail">{step['detail']}</div>
                </div>""",
                unsafe_allow_html=True,
            )

    # ------------------------------------------------------------------
    # TERMINAL RECORDING
    # ------------------------------------------------------------------
    else:
        if cast_content:
            cast_escaped = cast_content.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")
            player_html = f"""
            <link rel="stylesheet" type="text/css"
                  href="https://cdn.jsdelivr.net/npm/asciinema-player@3.8.0/dist/bundle/asciinema-player.min.css"/>
            <div id="player"></div>
            <script src="https://cdn.jsdelivr.net/npm/asciinema-player@3.8.0/dist/bundle/asciinema-player.min.js"></script>
            <script>
              const castText = `{cast_escaped}`;
              const blob = new Blob([castText], {{type: 'text/plain'}});
              const url  = URL.createObjectURL(blob);
              AsciinemaPlayer.create(url, document.getElementById('player'), {{
                cols: 120,
                rows: 24,
                autoPlay: false,
                loop: false,
                speed: 1.5,
                theme: 'monokai',
                fit: false,
                terminalFontSize: 13,
              }});
            </script>
            """
            st.info("**Click inside the terminal to reveal playback controls** — play/pause, progress bar, and speed.", icon="▶")
            st.components.v1.html(player_html, height=600, scrolling=False)

            st.divider()
            st.markdown("<p class='section-header'>What you are watching</p>", unsafe_allow_html=True)
            c1, c2, c3 = st.columns(3)
            c1.markdown("**Phase 1 — Standards retrieval**")
            c1.markdown(
                "The agent calls `query_knowledge` first. "
                "The JSON response contains CLSI EP33 graph nodes with the delta-check thresholds and swap weights. "
                "The server blocks triage until this call succeeds."
            )
            c2.markdown("**Phase 2 — Specimen triage (S100–S110)**")
            c2.markdown(
                "One `apply_autoverification` call per specimen. Each returns a verbose JSON blob with "
                "contamination score, swap score, and decision. "
                "Watch for: **S101, S107** (EDTA contamination HOLDs) · "
                "**S105, S106** (swap pair, both held) · "
                "**S110** (CKD patient — elevated K, correctly released)."
            )
            c3.markdown("**Phase 3 — Audit verification**")
            c3.markdown(
                "Final `get_audit_log` call retrieves the append-only session audit trail. "
                "Confirms every tool call is timestamped, attributed, and specimen values are write-once. "
                "This is the ALCOA+ evidence a CAP inspector would ask for."
            )
        else:
            if not GCS_BUCKET:
                st.warning(
                    "Recording not available — set `GCS_BUCKET` environment variable "
                    "and upload `recording.cast` to your GCS bucket.",
                    icon="⚠️",
                )
            else:
                st.warning(
                    f"Could not fetch recording from `gs://{GCS_BUCKET}/{GCS_RECORDING_OBJECT}`. "
                    "Check service account permissions.",
                    icon="⚠️",
                )


# ===========================================================================
# TAB 4 — About this Demo
# ===========================================================================
with tab_about:

    st.markdown("## What this demo shows")
    st.markdown("""
A clinical laboratory processes thousands of specimens every day. Before any result can be
reported to a physician, it passes through **autoverification** — an automated review step
that checks whether the result is clinically plausible and safe to release.

This demo answers two questions that every lab director must be able to answer before
deploying an AI autoverification agent:

1. **Did it make the right call on every specimen?** (Decision quality)
2. **Can you prove it derived its rules from published clinical standards — not from the test data?** (Reasoning provenance)

Most validation frameworks stop at question 1. This framework evaluates both, independently.
""")

    st.divider()

    # --- Why it matters ---
    st.markdown("## The two problems it catches")

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("### 🧪 EDTA Contamination")
        st.markdown("""
EDTA is the anticoagulant in purple-top collection tubes. It should never appear in a serum
specimen. When it does — from a contaminated needle, an incorrectly labelled tube, or a
processing error — it artificially **raises potassium** and **depresses calcium**.

If this result is released, a physician sees apparent critical hyperkalemia and may treat
aggressively for a condition the patient does not have. The specimen needs to be recollected,
not reported.

The agent identifies this by comparing each result against **the patient's own prior values**
(delta check), not against population reference ranges. This matters: a CKD patient may have
chronically elevated potassium that is normal *for them* — a population threshold would flag
it as contamination. A patient-relative delta check correctly releases it.
""")

    with col_b:
        st.markdown("### 🔀 Identity Swap")
        st.markdown("""
An identity swap occurs when two specimens are collected from the correct patients but their
tube labels are transposed — specimen A gets patient B's label, and vice versa.

The values in each tube are real and physiologically plausible. No single result looks
obviously wrong. The error only becomes visible when you compare *across* specimens: patient A's
glucose is reported to patient B, who has a completely different glucose history.

The agent detects this through **pairwise comparison**: for every pair of specimens in a batch,
it checks whether swapping their patient assignments would produce a better fit to both patients'
prior histories. A swap score near 1.0 means the swap hypothesis explains the data far better
than the current assignment. Both specimens in the pair are held.
""")

    st.divider()

    # --- How the agent reasons — diagram ---
    st.markdown("## How the agent reasons")
    st.markdown(
        "Instead of hardcoded thresholds, the agent reads a **clinical knowledge graph** "
        "derived from CLSI EP33. Each decision parameter lives as a named node — the agent "
        "traverses the graph, derives its values, then applies them to specimens. "
        "An independent verifier checks the agent's workflow against the same graph after the run. "
        "This is what makes the decision auditable, not just accurate."
    )

    st.graphviz_chart("""
        digraph G {
            rankdir=LR
            fontname="Arial"
            node [fontname="Arial" fontsize=11 margin="0.2,0.1"]
            edge [fontname="Arial" fontsize=10]

            subgraph cluster_kg {
                label="Clinical Knowledge Graph  (CLSI EP33)"
                style=filled
                fillcolor="#EFF6FF"
                color="#3B82F6"
                fontcolor="#1E3A5F"
                fontsize=11

                N1 [label="K acute rise\\nthreshold"   shape=box style=filled fillcolor="#DBEAFE" color="#3B82F6"]
                N2 [label="Ca acute fall\\nthreshold"  shape=box style=filled fillcolor="#DBEAFE" color="#3B82F6"]
                N3 [label="Swap detection\\nweights"   shape=box style=filled fillcolor="#DBEAFE" color="#3B82F6"]
                N4 [label="Decision\\npolicy"          shape=box style=filled fillcolor="#DBEAFE" color="#3B82F6"]
            }

            Agent    [label="AI Agent"             shape=box style=filled fillcolor="#DCFCE7" color="#16A34A"]
            WF       [label="workflow.json"         shape=note style=filled fillcolor="#FFFBEB" color="#D97706"]
            Spec     [label="Specimens\\nS100–S110" shape=cylinder style=filled fillcolor="#F3F4F6" color="#6B7280"]
            DE       [label="Decision\\nEngine"     shape=diamond style=filled fillcolor="#F9FAFB" color="#374151"]
            Out      [label="HOLD / RELEASE"        shape=box style=filled fillcolor="#FEE2E2" color="#EF4444"]
            PV       [label="Provenance\\nVerifier" shape=box style=filled fillcolor="#FFF7ED" color="#F97316"]
            Report   [label="Validation\\nReport"   shape=box style=filled fillcolor="#FFF7ED" color="#F97316"]

            subgraph cluster_phase2 {
                label="Phase 2"
                style=dashed
                color="#7C3AED"
                fontcolor="#7C3AED"
                fontsize=10

                ADM  [label="Analyser\\n(Allotrope ADM)" shape=box style="filled,dashed" fillcolor="#F5F3FF" color="#7C3AED" fontcolor="#4C1D95"]
                ADMP [label="container_type\\ninstrument_id\\nreagent_lot"  shape=note style="filled,dashed" fillcolor="#F5F3FF" color="#7C3AED" fontsize=9 fontcolor="#4C1D95"]
            }

            { rank=same; Spec; DE }
            { rank=same; ADM; ADMP }

            ADM -> ADMP [style=dashed color="#7C3AED"]
            ADMP -> N1  [label="enriches\\ngraph nodes" style=dashed color="#7C3AED" fontcolor="#7C3AED"]
            ADM  -> Spec [style=dashed color="#7C3AED" label="ADM\\ndocument"]

            N1 -> Agent [label="agent reads" style=dashed color="#3B82F6"]
            N2 -> Agent [style=dashed color="#3B82F6"]
            N3 -> Agent [style=dashed color="#3B82F6"]
            N4 -> Agent [style=dashed color="#3B82F6"]

            Agent -> WF  [label="derives params"]
            WF    -> DE
            Spec  -> DE
            DE    -> Out [label="scores"]

            N1 -> PV [label="independent\\ncheck" style=dashed color="#F97316"]
            N4 -> PV [style=dashed color="#F97316"]
            WF -> PV
            PV -> Report [label="Layer 2\\npass / fail"]
        }
    """, use_container_width=True)

    st.divider()

    # --- Allotrope ---
    st.markdown("## Phase 2 — Allotrope ADM")
    st.markdown(
        "This demo seeds specimen data manually. In production, data arrives as "
        "**Allotrope Foundation Data Model (ADM)** documents directly from analysers — "
        "the emerging industry standard for structured instrument output. "
        "ADM adds chain-of-custody fields (`container_type`, `instrument_id`, `reagent_lot`) "
        "that become additional nodes in the knowledge graph's contamination reasoning path. "
        "An EDTA tube flagged at the container level, confirmed by delta check, and traced to "
        "a specific instrument lot is a qualitatively stronger clinical finding than a value "
        "anomaly with no provenance. This demo is the decision framework. Allotrope ADM is "
        "the data layer that makes it production-grade."
    )

    st.divider()

    # --- Why Layer 2 matters ---
    st.markdown("## Why provenance verification matters")
    st.markdown("""
An agent could pass the decision quality tests simply by fitting its thresholds to the test
specimens — essentially memorising the answer. This would score well on the visible batch but
fail on patients it has never seen.

**Layer 2 checks whether the agent read the standard.**

The agent is given access to a clinical knowledge graph derived from **CLSI EP33** — the
published guideline for autoverification systems. After the run, the framework independently
reads the `workflow.json` the agent wrote and compares each threshold against the value
specified in the knowledge graph. If the agent derived its thresholds from the graph (within
tolerance), it passes. If it arrived at different values — even values that happen to work on
the test batch — it fails Layer 2.

This is the validation evidence a CAP inspector or CLIA surveyor would ask for: not just
"did it work?" but "where did the rules come from, and can you show me?"
""")

    st.divider()

    # --- Tab guide ---
    st.markdown("## Guide to each tab")

    with st.expander("📋  Results Dashboard", expanded=True):
        st.markdown("""
**Start here.** This tab gives you the complete validation summary.

- **Metric cards** (top) — the four numbers that determine whether the agent passes validation.
  Hover over the **?** on each card for a plain-English explanation of what it measures and why.
- **Per-specimen decisions table** — every specimen in the batch, with the agent's decision,
  the underlying scores, and for HOLD decisions, the one-line clinical reason.
- **Hold explanations** — expandable cards below the table with the full clinical narrative
  for each held specimen: which analytes deviated, by how many standard deviations, and why
  that pattern points to contamination or a swap rather than a clinical condition.
- **Reasoning provenance** — Layer 2 results. Shows whether each threshold in the agent's
  workflow was graph-derived (from CLSI EP33) or arrived at by other means.
- **CKD interference guard** — a callout for specimen S110, the critical edge case that
  separates a naive absolute-threshold agent from one that reads the standard correctly.
""")

    with st.expander("📊  Decision Space"):
        st.markdown("""
**The visual summary of how the agent sees the batch.**

Each specimen is plotted on two axes:
- **X axis — Contamination score**: how strongly the analyte pattern resembles EDTA contamination
  (elevated K, depressed Ca, both relative to the patient's own prior values)
- **Y axis — Identity swap score**: how much better the data fits if this specimen's patient
  assignment is swapped with another specimen in the batch

The dashed lines are the decision boundaries derived from the clinical knowledge graph.
Specimens in the shaded red regions were held; specimens in the white region were released.

**What to look for:**
- Contamination specimens (orange diamonds) cluster near the top of the X axis — high
  contamination score, near-zero swap score
- Swap specimens (purple stars) cluster near the top of the Y axis — high swap score
- S110 (CKD patient) sits at the origin — zero on both axes, correctly in the release zone
  despite having elevated potassium
""")

    with st.expander("▶   Agent Replay"):
        st.markdown("""
**Two views of the same verified run.**

Use the toggle at the top of the tab to switch between:

- **Step view** — 13 annotated tool-call cards, one per agent action, with clinical context for
  each decision. Clean at any zoom level; every frame is screenshot-ready. Start here for presentations.
- **Terminal recording** — the raw asciinema session from the actual run. Proves the agent
  operated in real time against a live LIMS server. Use this to show the raw evidence.

The tool call sequence is enforced by the server: `apply_autoverification` returns an error
until `query_knowledge` has been called. The agent cannot skip the standards-reading step.

**Run ID:** `lis-swap-contamination-triage__HsPAVBJ` · **Reward:** 1.0 · **Cost:** $0.12
""")

    st.divider()

    # --- Glossary ---
    st.markdown("## Glossary")

    terms = [
        ("Autoverification",
         "The automated process of reviewing laboratory results before they are released to "
         "the ordering physician. Rules-based systems have done this for decades; this demo "
         "shows an AI agent doing it with two-layer validation."),
        ("Delta Check",
         "A comparison of a patient's current result against their own prior results. More "
         "sensitive than population reference ranges because it accounts for each patient's "
         "individual baseline. CLSI EP33 specifies delta check as the preferred method for "
         "detecting EDTA contamination."),
        ("CLSI EP33",
         "Clinical and Laboratory Standards Institute guideline EP33 — 'Autoverification of "
         "Medical Laboratory Test Results.' The published standard that defines how autoverification "
         "rules should be constructed and validated. The agent's thresholds are derived from this "
         "document."),
        ("F1 Score",
         "The harmonic mean of Precision and Recall. Balances the risk of missing a bad specimen "
         "(false negative) against the risk of holding a good one unnecessarily (false positive). "
         "Range 0–1; pass threshold for this task is ≥ 0.80."),
        ("Precision",
         "Of all specimens the agent held, what fraction actually needed to be held? "
         "Low precision = too many unnecessary holds, disrupting lab workflow."),
        ("Recall",
         "Of all specimens that needed to be held, what fraction did the agent catch? "
         "Low recall = missed detections. A missed contamination or swap is a patient safety event."),
        ("Unsafe Release",
         "A contaminated or swapped specimen that the agent incorrectly released. "
         "The primary safety gate. Zero is the only acceptable value."),
        ("False Hold Rate",
         "The fraction of normal specimens incorrectly held. Too high a rate means the agent "
         "is over-cautious — adding review workload without clinical benefit. Pass threshold: ≤ 0.34."),
        ("Layer 1 / Layer 2",
         "Layer 1 evaluates decision quality (did the agent make the right calls?). "
         "Layer 2 evaluates reasoning provenance (did the agent derive its thresholds from "
         "the published standard, not from the test data?). Both must pass for a valid run."),
        ("Provenance Verification",
         "The process of checking that the agent's workflow parameters match the values "
         "specified in the clinical knowledge graph, within tolerance. Provides the regulatory "
         "evidence that rules are grounded in validated methodology, not data-fitting."),
        ("ALCOA+",
         "Data integrity principles required by CAP (GEN.43875): Attributable, Legible, "
         "Contemporaneous, Original, Accurate — plus Complete, Consistent, Enduring, Available. "
         "The audit log in this framework enforces these principles: every tool call is "
         "timestamped, attributed to a session, append-only, and the original specimen values "
         "are write-once."),
        ("MCP (Model Context Protocol)",
         "The protocol through which the AI agent calls laboratory tools — querying the knowledge "
         "graph, creating specimen records, running triage, reading the audit log. MCP provides "
         "a structured, auditable interface between the agent and the LIMS server."),
        ("Knowledge Graph",
         "A structured representation of CLSI EP33 clinical rules in which clinical concepts "
         "are nodes and their relationships are edges. The agent traverses this graph to derive "
         "contamination thresholds, swap detection weights, and delta-check parameters — rather "
         "than reading from a flat config file. The graph is versioned and injected at runtime; "
         "updating a clinical rule requires only a graph update and server restart, not a code "
         "change. The traversal path is recorded in the audit log, making the reasoning auditable."),
        ("Allotrope ADM",
         "Allotrope Foundation Data Model — an emerging industry standard for structured "
         "instrument output from clinical analysers, maintained by the Allotrope Foundation. "
         "ADM documents carry chain-of-custody fields (instrument ID, reagent lot, container "
         "type, method) that are not present in manually entered data. In a production "
         "deployment, the LIMS server would receive ADM documents directly from analysers, "
         "and the knowledge graph would use container_type and instrument provenance as "
         "additional nodes in the contamination reasoning path."),
        ("CKD Interference Guard",
         "Specimen S110 — a patient with chronic kidney disease and chronically elevated "
         "potassium. An agent using absolute thresholds would incorrectly flag this as "
         "contamination. The delta-check approach correctly identifies the elevated K as "
         "stable within this patient's own baseline and releases the specimen."),
    ]

    for term, definition in terms:
        with st.expander(term):
            st.markdown(definition)


# ===========================================================================
# Harbor mode overlay
# ===========================================================================
if mode == "Harbor":
    st.divider()
    st.markdown("### Harbor — TerminalBench task runner")
    st.caption(
        "This task is published as a TerminalBench benchmark. "
        "Run it with the Harbor CLI to evaluate any agent."
    )

    harbor_cmd = (
        "harbor trials start \\\n"
        "  -p lis-swap-contamination-triage \\\n"
        "  -a claude-code \\\n"
        "  -m anthropic/claude-sonnet-4-6"
    )
    st.code(harbor_cmd, language="bash")

    harbor_available = subprocess.run(
        ["which", "harbor"], capture_output=True
    ).returncode == 0

    if harbor_available:
        if st.button("▶  Run trial now", type="primary"):
            with st.spinner("Running Harbor trial…"):
                result = subprocess.run(
                    ["harbor", "trials", "start",
                     "-p", "lis-swap-contamination-triage",
                     "-a", "claude-code",
                     "-m", "anthropic/claude-sonnet-4-6"],
                    capture_output=True, text=True, timeout=600,
                )
            if result.returncode == 0:
                st.success("Trial complete.")
                st.code(result.stdout, language="text")
            else:
                st.error("Trial failed.")
                st.code(result.stderr, language="text")
    else:
        st.info(
            "`harbor` not found in PATH.  \n"
            "Install: `pip install harbor-cli`  \n"
            "Docs: https://harbor-bench.ai/docs",
            icon="ℹ️",
        )
