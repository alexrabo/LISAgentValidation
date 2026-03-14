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
RESULTS_FILE    = UI_DIR / "verified_run_results.json"
DECISIONS_FILE  = UI_DIR / "verified_run_decisions.json"
TRAJECTORY_FILE = UI_DIR / "trajectory.json"

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
    initial_sidebar_state="expanded",
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
  /* Hide native sidebar toggle — replaced by custom JS button */
  [data-testid="stSidebarCollapseButton"] { display: none !important; }
  [data-testid="collapsedControl"]        { display: none !important; }

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


@st.cache_data
def load_trajectory() -> list[dict]:
    """Load agent steps from trajectory.json committed to the image."""
    try:
        t = json.loads(TRAJECTORY_FILE.read_text())
        return [s for s in t["steps"] if s["source"] == "agent"]
    except Exception:
        return []


@st.cache_data(ttl=300)
def get_cast_markers(cast_content: str) -> dict:
    """Derive recording-relative timestamps from trajectory step timestamps.
    Falls back to empty dict if trajectory or cast epoch unavailable."""
    import json as _json
    from datetime import datetime
    try:
        header = _json.loads(cast_content.split('\n')[0])
        cast_epoch = header.get('timestamp')
        if not cast_epoch:
            return {}
        agent_steps = load_trajectory()
        if not agent_steps:
            return {}
        markers = {"0": 0.0}
        for i, step in enumerate(agent_steps):
            ts = datetime.fromisoformat(step['timestamp'].replace('Z', '+00:00'))
            rel = round(ts.timestamp() - cast_epoch, 1)
            if rel > 0:
                markers[str(i + 1)] = rel
        return markers
    except Exception:
        return {}


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
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### 🧪 LIS AI Validation")
    st.caption("CLSI EP33 · Two-layer evaluation framework")
    st.divider()

    page = st.radio(
        "",
        ["📊 Demo", "ℹ️ About"],
        index=0,
        label_visibility="collapsed",
    )

    st.divider()
    st.caption("Layer 1 — Decision quality  \nLayer 2 — Reasoning provenance")
    st.caption("Specimens: S100–S110 (11 total)")

# ---------------------------------------------------------------------------
# Custom sidebar toggle button (replaces unreliable native Streamlit button)
# Injected into parent DOM via same-origin iframe access
# ---------------------------------------------------------------------------
st.components.v1.html("""
<script>
(function () {
  function init() {
    var doc = window.parent.document;
    var sidebar = doc.querySelector('[data-testid="stSidebar"]');
    if (!sidebar) { setTimeout(init, 300); return; }

    // Remove any previous instance (hot-reload safety)
    var prev = doc.getElementById('lis-sidebar-toggle');
    if (prev) prev.remove();

    var btn = doc.createElement('button');
    btn.id = 'lis-sidebar-toggle';
    Object.assign(btn.style, {
      position:       'fixed',
      top:            '72px',
      zIndex:         '99999',
      background:     '#EFF6FF',
      border:         '2px solid #3B82F6',
      borderLeft:     'none',
      borderRadius:   '0 8px 8px 0',
      width:          '20px',
      height:         '52px',
      cursor:         'pointer',
      display:        'flex',
      alignItems:     'center',
      justifyContent: 'center',
      fontSize:       '16px',
      color:          '#3B82F6',
      boxShadow:      '3px 0 8px rgba(59,130,246,0.20)',
      padding:        '0',
      lineHeight:     '1',
      transition:     'left 0.3s ease, opacity 0.2s ease',
    });

    function update() {
      var expanded = sidebar.getAttribute('aria-expanded') !== 'false';
      btn.textContent = expanded ? '\u2039' : '\u203a';   // ‹ or ›
      var rect = sidebar.getBoundingClientRect();
      btn.style.left = (expanded ? rect.right - 2 : 0) + 'px';
    }

    btn.addEventListener('click', function () {
      var native = doc.querySelector('[data-testid="stSidebarCollapseButton"] button');
      if (native) { native.click(); setTimeout(update, 350); }
    });

    var observer = new MutationObserver(update);
    observer.observe(sidebar, {
      attributes: true,
      attributeFilter: ['aria-expanded', 'style', 'class'],
    });

    doc.body.appendChild(btn);
    update();

    // Force sidebar open on every page load regardless of browser-stored state
    if (sidebar.getAttribute('aria-expanded') === 'false') {
      var native = doc.querySelector('[data-testid="stSidebarCollapseButton"] button');
      if (native) { native.click(); setTimeout(update, 350); }
    }
  }

  // Run after Streamlit has finished rendering
  setTimeout(init, 800);
})();
</script>
""", height=0)


# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
results = load_results()
decisions = load_decisions()
agg = results["metrics"]["aggregate"]
provenance = results["provenance"]

# ===========================================================================
# ABOUT PAGE — shown when page == "ℹ️ About"; st.stop() prevents tab render
# ===========================================================================
if page == "ℹ️ About":

    st.markdown("## Welcome to the LIS AI Validation Demo")
    st.markdown("""
Clinical laboratories process thousands of specimens every day. Before any result reaches
a physician, it passes through **autoverification** — an automated review that checks
whether the result is clinically plausible and safe to release.

This demo shows an AI agent performing autoverification on a batch of 11 specimens.
It is evaluated against two questions every lab director must answer before deploying AI:

1. **Did it make the right call on every specimen?** — *Decision quality (Layer 1)*
2. **Can you prove it derived its rules from published clinical standards?** — *Reasoning provenance (Layer 2)*

Most validation frameworks stop at question 1. This framework evaluates both, independently.
The agent must not only get the right answers — it must get them *for the right reasons*.
""")

    st.divider()

    # --- Two problems ---
    st.markdown("## The two problems the agent must catch")
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("### 🧪 EDTA Contamination")
        st.markdown("""
EDTA is the anticoagulant in purple-top CBC tubes. When it contaminates a chemistry specimen
it artificially **raises potassium** and **depresses calcium**. A physician seeing the result
may treat aggressively for a critical condition the patient does not have.

The agent detects this using a **patient-relative delta check** — comparing the result against
the patient's *own* prior values, not a population range. This matters: a CKD patient may
have chronically elevated potassium that is normal *for them*. A population threshold flags
it as contamination. A delta check correctly releases it.
""")
    with col_b:
        st.markdown("### 🔀 Identity Swap")
        st.markdown("""
A swap occurs when two specimens are collected correctly but their tube labels are transposed.
Each individual result looks physiologically plausible — the error only appears when you
compare *across* specimens: patient A's glucose is reported under patient B's name.

The agent detects this through **pairwise comparison**: for every pair of specimens, it checks
whether swapping their patient assignments produces a better fit to both patients' prior
histories. A swap score near 1.0 means the swap hypothesis explains the data far better than
the current label assignment. Both specimens in the pair are held for review.
""")

    st.divider()

    # --- How the agent reasons ---
    st.markdown("## How the agent reasons")
    st.markdown(
        "Instead of hardcoded thresholds, the agent reads a **clinical knowledge graph** "
        "derived from CLSI EP33. Each parameter lives as a named node — the agent traverses "
        "the graph, derives its values, then applies them. An independent verifier checks the "
        "agent's workflow against the same graph after the run. This is what makes the "
        "decision **auditable**, not just accurate."
    )
    st.graphviz_chart("""
        digraph G {
            rankdir=LR
            fontname="Arial"
            node [fontname="Arial" fontsize=11 margin="0.2,0.1"]
            edge [fontname="Arial" fontsize=10]
            subgraph cluster_kg {
                label="Clinical Knowledge Graph  (CLSI EP33)"
                style=filled fillcolor="#EFF6FF" color="#3B82F6" fontcolor="#1E3A5F" fontsize=11
                N1 [label="K acute rise\\nthreshold"  shape=box style=filled fillcolor="#DBEAFE" color="#3B82F6"]
                N2 [label="Ca acute fall\\nthreshold" shape=box style=filled fillcolor="#DBEAFE" color="#3B82F6"]
                N3 [label="Swap detection\\nweights"  shape=box style=filled fillcolor="#DBEAFE" color="#3B82F6"]
                N4 [label="Decision\\npolicy"         shape=box style=filled fillcolor="#DBEAFE" color="#3B82F6"]
            }
            Agent  [label="AI Agent"            shape=box     style=filled fillcolor="#DCFCE7" color="#16A34A"]
            WF     [label="workflow.json"        shape=note    style=filled fillcolor="#FFFBEB" color="#D97706"]
            Spec   [label="Specimens S100–S110"  shape=cylinder style=filled fillcolor="#F3F4F6" color="#6B7280"]
            DE     [label="Decision Engine"      shape=diamond style=filled fillcolor="#F9FAFB" color="#374151"]
            Out    [label="HOLD / RELEASE"       shape=box     style=filled fillcolor="#FEE2E2" color="#EF4444"]
            PV     [label="Provenance Verifier"  shape=box     style=filled fillcolor="#FFF7ED" color="#F97316"]
            Report [label="Validation Report"    shape=box     style=filled fillcolor="#FFF7ED" color="#F97316"]
            subgraph cluster_phase2 {
                label="Phase 2 — Allotrope ADM" style=dashed color="#7C3AED" fontcolor="#7C3AED" fontsize=10
                ADM  [label="Analyser\\n(ADM)" shape=box style="filled,dashed" fillcolor="#F5F3FF" color="#7C3AED" fontcolor="#4C1D95"]
                ADMP [label="container_type\\ninstrument_id\\nreagent_lot" shape=note style="filled,dashed" fillcolor="#F5F3FF" color="#7C3AED" fontsize=9 fontcolor="#4C1D95"]
            }
            { rank=same; Spec; DE }
            { rank=same; ADM; ADMP }
            ADM -> ADMP [style=dashed color="#7C3AED"]
            ADMP -> N1  [label="enriches graph" style=dashed color="#7C3AED" fontcolor="#7C3AED"]
            ADM  -> Spec [style=dashed color="#7C3AED" label="ADM document"]
            N1 -> Agent [label="agent reads" style=dashed color="#3B82F6"]
            N2 -> Agent [style=dashed color="#3B82F6"]
            N3 -> Agent [style=dashed color="#3B82F6"]
            N4 -> Agent [style=dashed color="#3B82F6"]
            Agent -> WF [label="derives params"]
            WF -> DE
            Spec -> DE
            DE -> Out [label="scores"]
            N1 -> PV [label="independent check" style=dashed color="#F97316"]
            N4 -> PV [style=dashed color="#F97316"]
            WF -> PV
            PV -> Report [label="Layer 2 pass/fail"]
        }
    """, use_container_width=True)

    st.divider()

    # --- Tab guide ---
    st.markdown("## Your guide to the four tabs")
    st.markdown("Each tab answers a different question. Start with Results Dashboard, then explore.")
    c1, c2 = st.columns(2)
    c3, c4 = st.columns(2)
    with c1:
        with st.container(border=True):
            st.markdown("#### 📋 Results Dashboard")
            st.markdown(
                "The validated outcome. Four metric cards show whether the agent passed, "
                "per-specimen decisions show each HOLD/RELEASE with its clinical reason, "
                "and Layer 2 provenance shows where the thresholds came from."
            )
            st.caption("→ Start here")
    with c2:
        with st.container(border=True):
            st.markdown("#### 📊 Decision Space")
            st.markdown(
                "Every specimen plotted on contamination score (X) vs. identity swap score (Y). "
                "The dashed lines are the KG-derived decision boundaries. See at a glance why "
                "each specimen was held or released — and why S110 (CKD) sits at the origin."
            )
            st.caption("→ Best for visual explanation")
    with c3:
        with st.container(border=True):
            st.markdown("#### ▶ Agent Replay")
            st.markdown(
                "A terminal recording of the agent solving the task, synchronized with "
                "8 annotated narration cards. Watch the agent read the knowledge graph, "
                "derive thresholds, write its configuration, and run triage."
            )
            st.caption("→ The provenance story in real time")
    with c4:
        with st.container(border=True):
            st.markdown("#### 📖 Glossary")
            st.markdown(
                "Plain-English definitions of every clinical and statistical term used "
                "in the demo — from delta check and CLSI EP33 to F1 score, ALCOA+, "
                "and Allotrope ADM."
            )
            st.caption("→ Reference when a term is unfamiliar")

    st.divider()

    # --- Three runs ---
    st.markdown("## Three independent runs, one benchmark")
    st.markdown(
        "The same task was evaluated three times by the same agent model. "
        "All three scored **Reward 1.0** — every specimen correctly classified. "
        "The Agent Replay tab shows run `HsPAVBJ`."
    )
    rc1, rc2, rc3 = st.columns(3)
    rc1.metric("Run hJQzBJW", "4 steps · $0.08", "Reward 1.0 ✅",
               help="Most efficient run — solved in fewest reasoning steps.")
    rc2.metric("Run HsPAVBJ", "5 steps · $0.12", "Reward 1.0 ✅",
               help="Featured run — recording shown in Agent Replay tab.")
    rc3.metric("Run Zo4iCGU", "6 steps · $0.15", "Reward 1.0 ✅",
               help="Most deliberate run — most intermediate KG queries.")
    st.caption(
        "Agent: GPT-5 via TerminalBench harness · Task: `lis-swap-contamination-triage` · "
        "Date: 2026-02-21 · All runs used prior-relative delta check derived from CLSI EP33."
    )

    st.divider()

    # --- Harbor ---
    st.markdown("## Run it yourself — TerminalBench")
    st.markdown(
        "This benchmark is published on TerminalBench. You can evaluate any agent against "
        "it with a single command. The agent receives the task description, the knowledge "
        "graph, and the specimen batch — and must repair `workflow.json` to produce correct "
        "HOLD/RELEASE decisions."
    )
    harbor_cmd = (
        "harbor trials start \\\n"
        "  -p lis-swap-contamination-triage \\\n"
        "  -a claude-code \\\n"
        "  -m anthropic/claude-sonnet-4-6"
    )
    st.code(harbor_cmd, language="bash")
    harbor_available = subprocess.run(["which", "harbor"], capture_output=True).returncode == 0
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
        st.info("`harbor` not found — install: `pip install harbor-cli`", icon="ℹ️")

    st.divider()

    # --- Why provenance matters ---
    st.markdown("## Why Layer 2 — provenance verification — matters")
    st.markdown("""
An agent could pass Layer 1 simply by fitting its thresholds to the visible test specimens —
essentially memorising the answers. It would score well on the visible batch but fail on
patients it has never seen.

**Layer 2 checks whether the agent read the standard.**

After the run, the framework independently reads the `workflow.json` the agent wrote and
compares each threshold against the value specified in the knowledge graph. If the agent
derived its thresholds from the graph (within tolerance), it passes. If it arrived at
different values — even values that happen to work on this batch — it fails Layer 2.

This is the evidence a CAP inspector or CLIA surveyor asks for: not just *"did it work?"*
but *"where did the rules come from, and can you show me?"*
""")

    st.divider()

    # --- Allotrope ---
    st.markdown("## Phase 2 — Allotrope ADM")
    st.markdown(
        "This demo seeds specimen data manually. In production, data arrives as "
        "**Allotrope Foundation Data Model (ADM)** documents directly from analysers — "
        "the emerging industry standard for structured instrument output. "
        "ADM adds chain-of-custody fields (`container_type`, `instrument_id`, `reagent_lot`) "
        "that become additional nodes in the knowledge graph's contamination reasoning path. "
        "This demo is the decision framework. Allotrope ADM is the data layer that makes it production-grade."
    )

    st.stop()


# ---------------------------------------------------------------------------
# Tabs (Demo mode only — About page calls st.stop() above)
# ---------------------------------------------------------------------------
tab_results, tab_scatter, tab_replay, tab_glossary = st.tabs([
    "📋  Results Dashboard",
    "📊  Decision Space",
    "▶   Agent Replay",
    "📖  Glossary",
])


# ===========================================================================
# TAB 1 — Results Dashboard
# ===========================================================================
with tab_results:
    st.caption("Validation outcome — metric cards, per-specimen decisions with clinical explanations, and Layer 2 reasoning provenance.")

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
    st.caption("Every specimen plotted on contamination score vs. swap score — see where the agent drew the line and why S110 (CKD) sits at the origin.")

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
    # ── RULE DERIVATION ─────────────────────────────────────────────────
    {
        "group": "rule_derivation",
        "title": "Step 1 — Initial exploration",
        "command": "ls -la /app  ·  cat workflow.json  ·  cat clinical_knowledge.json  ·  /app/triage",
        "detail": (
            "Agent reads the flawed `workflow.json` (absolute thresholds only, swap disabled) "
            "then reads the full knowledge graph. Runs a first triage pass — all specimens "
            "release because contamination rules are wrong. Writes a corrected first version: "
            "prior-relative EDTA signature, swap detection enabled."
        ),
        "kg_nodes": ["EDTA_contamination", "K_acute_rise", "Ca_acute_fall"],
        "flag": None,
    },
    {
        "group": "rule_derivation",
        "title": "Step 2 — Fixing contamination thresholds",
        "command": "grep paths  ·  grep specimen_swap  ·  cat clinical_knowledge.json",
        "detail": (
            "Agent identifies two errors in its first attempt: "
            "Ca_delta_max should be −2.5 SD (it set −3.0), and fallback_Ca_max must be "
            "7.2 mg/dL (it used 1.80 — wrong units). "
            "Reads `Ca_acute_fall` and `new_patient_fallback` nodes. Corrects both and re-runs triage."
        ),
        "kg_nodes": ["Ca_acute_fall", "new_patient_fallback", "contamination_detection"],
        "flag": None,
    },
    {
        "group": "rule_derivation",
        "title": "Step 3 — Deriving exact swap weights",
        "command": "grep glucose_recommended_weight  ·  grep other_analytes_weight  ·  grep hold_threshold",
        "detail": (
            "Agent extracts exact values from `specimen_swap` and `decision_policy` KG nodes: "
            "Glucose weight = 3.0 (highest inter-patient variability), all other analytes = 1.0, "
            "swap_hold_threshold = 0.3 (must be < 1.0). "
            "Writes corrected workflow — triage now correctly HOLDs S105 and S106 as identity swap pair."
        ),
        "kg_nodes": ["specimen_swap", "glucose_recommended_weight", "decision_policy"],
        "flag": None,
    },
    # ── DECISIONS REACHED ────────────────────────────────────────────────
    {
        "group": "decisions",
        "title": "Step 4 — Final workflow and correct triage",
        "command": "cat > /app/workflow.json  ·  python3 validate JSON  ·  /app/triage  ·  cat decisions.json",
        "detail": (
            "Agent finalises `workflow.json` with all KG-derived values: "
            "K_delta_min 3.0 SD, Ca_delta_max −2.5 SD, fallback K ≥ 6.5 mmol/L, "
            "fallback Ca ≤ 7.2 mg/dL, Glucose weight 3.0, contamination threshold 0.5, swap threshold 0.3. "
            "Triage result: S101, S107 → HOLD (contamination) · S105, S106 → HOLD (swap) · "
            "S100, S102–S104, S108–S110 → RELEASE · S110 (CKD) correctly released."
        ),
        "kg_nodes": ["contamination_hold_threshold", "swap_hold_threshold"],
        "flag": "decisions",
    },
    {
        "group": "decisions",
        "title": "Step 5 — Task confirmed complete",
        "command": "mark_task_complete",
        "detail": (
            "Agent confirms task complete. All parameters derived from the CLSI EP33 knowledge graph — "
            "no values fitted to the visible batch specimens. "
            "Final score: F1 1.00 · Unsafe releases 0 · Reward 1.0 · Total cost $0.12."
        ),
        "kg_nodes": [],
        "flag": "decisions",
    },
]


with tab_replay:

    st.caption("Watch the agent derive rules from the knowledge graph and triage all 11 specimens — terminal recording synchronized with annotated decision steps.")
    st.markdown("<p class='section-header'>Agent terminal session — verified run</p>", unsafe_allow_html=True)
    st.caption("Run ID: `lis-swap-contamination-triage__HsPAVBJ` · Reward: 1.0 · Cost: $0.12 · GPT-5")
    st.info("**Click inside the terminal for playback controls** — play/pause, progress bar, speed.", icon="▶")

    cast_content = fetch_recording_cast()

    if cast_content:
        markers     = get_cast_markers(cast_content)
        markers_json = json.dumps(markers)
        cast_escaped = cast_content.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")

        # ------------------------------------------------------------------
        # Build narration panel HTML (inline styles — lives inside iframe)
        # ------------------------------------------------------------------
        GROUP_HEADERS = {
            "rule_derivation": ("📐", "Rule Derivation", "#3B82F6", "#EFF6FF"),
            "decisions":       ("✅", "Decisions Reached", "#16A34A", "#F0FDF4"),
        }

        cards_html = []
        current_group = None
        for idx, step in enumerate(REPLAY_STEPS):
            group = step["group"]

            if group != current_group:
                icon, label, colour, bg_header = GROUP_HEADERS[group]
                cards_html.append(
                    f'<div style="display:flex;align-items:center;gap:6px;'
                    f'background:{bg_header};border-left:3px solid {colour};'
                    f'border-radius:4px;padding:5px 10px;margin:{"0" if idx == 0 else "14px"} 0 8px">'
                    f'<span style="font-size:0.85rem">{icon}</span>'
                    f'<span style="font-size:0.72rem;font-weight:700;color:{colour};'
                    f'letter-spacing:0.06em;text-transform:uppercase">{label}</span>'
                    f'</div>'
                )
                current_group = group

            flag     = step.get("flag") or ""
            border   = "#16A34A" if flag == "decisions" else "#6B7280"
            bg_card  = "#F0FDF4" if flag == "decisions" else "#ffffff"

            cmd_div = (
                f'<div style="font-family:monospace;font-size:0.70rem;color:#9CA3AF;'
                f'margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">'
                f'{step["command"]}</div>'
            )
            kg_nodes = step.get("kg_nodes") or []
            kg_html = "".join(
                f'<span style="background:#EFF6FF;color:#3B82F6;border-radius:3px;'
                f'padding:1px 6px;font-size:0.63rem;margin-right:3px;font-family:monospace">'
                f'{n}</span>'
                for n in kg_nodes
            )
            kg_div = (
                f'<div style="margin-top:5px">{kg_html}</div>' if kg_html else ""
            )
            cards_html.append(
                f'<div class="n-card" data-step="{idx}" style="'
                f'border:1px solid #E5E7EB;border-left:4px solid {border};border-radius:6px;'
                f'padding:8px 10px;margin-bottom:6px;background:{bg_card};'
                f'transition:background 0.25s,box-shadow 0.25s">'
                f'<div style="font-size:0.80rem;font-weight:600;color:#111827">'
                f'{step["title"]}</div>'
                f'{cmd_div}'
                f'{kg_div}'
                f'<div style="font-size:0.75rem;color:#4B5563;margin-top:5px;line-height:1.45">'
                f'{step["detail"]}</div>'
                f'</div>'
            )

        narration_html = "\n".join(cards_html)

        # ------------------------------------------------------------------
        # Combined component: player (left 58%) + narration panel (right 42%)
        # ------------------------------------------------------------------
        component_html = (
            '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/asciinema-player@3.8.0/dist/bundle/asciinema-player.min.css"/>'
            '<style>'
            '.n-card.active{background:#EFF6FF!important;border-left-color:#3B82F6!important;box-shadow:0 0 0 1px #BFDBFE}'
            '</style>'
            '<div style="display:flex;gap:14px;height:560px">'
            '  <div style="flex:3;min-width:0;display:flex;flex-direction:column">'
            '    <div id="player" style="flex:1"></div>'
            '  </div>'
            '  <div id="narration" style="flex:2;overflow-y:auto;padding:0 6px 0 2px;'
            '       scrollbar-width:thin;scrollbar-color:#E5E7EB transparent">'
            + narration_html +
            '  </div>'
            '</div>'
            '<script src="https://cdn.jsdelivr.net/npm/asciinema-player@3.8.0/dist/bundle/asciinema-player.min.js"></script>'
            '<script>'
            f'const MARKERS={markers_json};'
            f'const castText=`{cast_escaped}`;'
            'const blob=new Blob([castText],{type:"text/plain"});'
            'const url=URL.createObjectURL(blob);'
            'const player=AsciinemaPlayer.create(url,document.getElementById("player"),{'
            '  cols:80,rows:24,autoPlay:false,loop:false,speed:1.5,'
            '  theme:"monokai",fit:false,terminalFontSize:13'
            '});'
            'var lastActive=-1;'
            'setInterval(function(){'
            '  var t=0;try{t=player.getCurrentTime();}catch(e){}'
            '  var active=-1;'
            '  for(var i=1;i<=5;i++){if(MARKERS[String(i)]!==undefined&&t>=MARKERS[String(i)])active=i-1;}'
            '  if(active===lastActive)return;'
            '  lastActive=active;'
            '  document.querySelectorAll(".n-card").forEach(function(c,i){'
            '    if(i===active){c.classList.add("active");c.scrollIntoView({behavior:"smooth",block:"nearest"});}'
            '    else{c.classList.remove("active");}'
            '  });'
            '},250);'
            '</script>'
        )

        st.components.v1.html(component_html, height=580, scrolling=False)

    else:
        if not GCS_BUCKET:
            st.warning(
                "Recording not available — set `GCS_BUCKET` and upload `recording.cast`.",
                icon="⚠️",
            )
        else:
            st.warning(
                f"Could not fetch recording from `gs://{GCS_BUCKET}/{GCS_RECORDING_OBJECT}`.",
                icon="⚠️",
            )
        # Fallback: static step cards (no recording)
        st.markdown("<br>", unsafe_allow_html=True)
        GROUP_LABELS = {
            "rule_derivation": ("📐", "Rule Derivation"),
            "decisions":       ("✅", "Decisions Reached"),
        }
        current_group = None
        for i, step in enumerate(REPLAY_STEPS, 1):
            group = step["group"]
            if group != current_group:
                icon, label = GROUP_LABELS[group]
                st.markdown(f"<p class='section-header' style='margin-top:1rem'>{icon} {label}</p>", unsafe_allow_html=True)
                current_group = group
            flag = step.get("flag") or ""
            kg = " · ".join(step.get("kg_nodes") or [])
            kg_line = f"<div style='font-size:0.70rem;color:#3B82F6;margin-top:3px'>{kg}</div>" if kg else ""
            st.markdown(
                f'<div class="step-card phase-triage {flag}">'
                f'<div style="font-size:0.80rem;font-weight:600;color:#111827">{step["title"]}</div>'
                f'<div style="font-family:monospace;font-size:0.70rem;color:#9CA3AF;margin-top:2px">{step["command"]}</div>'
                f'{kg_line}'
                f'<div class="step-detail">{step["detail"]}</div></div>',
                unsafe_allow_html=True,
            )


# ===========================================================================
# TAB 4 — Glossary
# ===========================================================================
with tab_glossary:
    st.caption("Plain-English definitions of every clinical and statistical term used in the demo.")
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


