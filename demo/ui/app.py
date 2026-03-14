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
COLOUR_HOLD          = "#EF4444"   # red-500
COLOUR_RELEASE       = "#22C55E"   # green-500
COLOUR_NORMAL        = "#6B7280"   # gray-500
COLOUR_CONTAMINATION = "#F97316"   # orange-500
COLOUR_SWAP          = "#8B5CF6"   # violet-500

# ---------------------------------------------------------------------------
# Page config — must be the first Streamlit call
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
# Snapshot visual renderer — builds modal HTML from snapshot_visual data
# ---------------------------------------------------------------------------
def _build_snapshot_html(sv: dict, why: str) -> str:
    """Render snapshot_visual as an HTML string embedded in the step modal."""
    p = []

    # ── "What happened" header ──────────────────────────────────────────
    p.append(
        '<div style="background:#F8FAFC;border-left:3px solid #3B82F6;border-radius:4px;'
        'padding:8px 12px;margin-bottom:12px">'
        '<div style="font-size:0.64rem;font-weight:700;color:#64748B;text-transform:uppercase;'
        'letter-spacing:0.06em;margin-bottom:3px">What happened</div>'
        f'<div style="font-size:0.72rem;color:#1E293B;line-height:1.45">{sv["changed"]}</div>'
        '</div>'
    )

    # ── Two-column: KG→param graph (left) + specimen circles (right) ───
    p.append('<div style="display:flex;gap:14px;margin-bottom:12px">')

    # LEFT: KG → parameter rows
    p.append(
        '<div style="flex:1;min-width:0">'
        '<div style="font-size:0.64rem;font-weight:700;color:#64748B;text-transform:uppercase;'
        'letter-spacing:0.06em;margin-bottom:6px">Knowledge graph → parameters</div>'
    )
    for param in sv.get("params", []):
        status = param.get("status", "ok")
        if status == "ok":
            bg, border, tc, sym = "#DCFCE7", "#22C55E", "#15803D", "✓"
        elif status == "warn":
            bg, border, tc, sym = "#FEF3C7", "#F59E0B", "#92400E", "≈"
        else:
            bg, border, tc, sym = "#FEE2E2", "#EF4444", "#B91C1C", "✗"

        src = param.get("kg_source", "")
        badge = (
            f'<span style="background:#EFF6FF;color:#3B82F6;border-radius:3px;'
            f'padding:1px 5px;font-size:0.59rem;font-family:monospace;white-space:nowrap">'
            f'{src}</span>'
        ) if src else '<span style="display:inline-block;width:6px"></span>'

        kg_note = (
            f'<span style="font-size:0.60rem;color:#9CA3AF;margin-left:4px">'
            f'→ KG: {param["kg"]}</span>'
        ) if param.get("kg") else ""

        p.append(
            f'<div style="display:flex;align-items:center;gap:5px;margin-bottom:5px">'
            f'{badge}'
            f'<span style="color:#CBD5E1;font-size:0.75rem;flex-shrink:0">→</span>'
            f'<div style="background:{bg};border:1px solid {border};border-radius:4px;'
            f'padding:3px 7px;font-size:0.68rem;color:{tc};flex:1;min-width:0">'
            f'<b>{param["name"]}</b>&nbsp;{param["value"]}{kg_note}'
            f'</div>'
            f'<span style="font-size:0.75rem;flex-shrink:0;color:{tc}">{sym}</span>'
            f'</div>'
        )
    p.append('</div>')  # end params column

    # RIGHT: specimen outcome circles
    p.append(
        '<div style="flex:0 0 auto">'
        '<div style="font-size:0.64rem;font-weight:700;color:#64748B;text-transform:uppercase;'
        'letter-spacing:0.06em;margin-bottom:6px">Triage result</div>'
        '<div style="display:flex;flex-wrap:wrap;gap:5px;max-width:150px">'
    )
    for spec in sv.get("specimens", []):
        h, sh = spec["hold"], spec["should_hold"]
        if h and sh:
            sbg, sborder, icon, stc = "#16A34A", "#15803D", "✓", "white"
        elif not h and not sh:
            sbg, sborder, icon, stc = "#F1F5F9", "#CBD5E1", "", "#9CA3AF"
        elif not h and sh:
            sbg, sborder, icon, stc = "#EF4444", "#B91C1C", "!", "white"
        else:
            sbg, sborder, icon, stc = "#F97316", "#EA580C", "?", "white"
        p.append(
            f'<div style="text-align:center">'
            f'<div style="width:26px;height:26px;border-radius:50%;background:{sbg};'
            f'border:2px solid {sborder};display:flex;align-items:center;'
            f'justify-content:center;font-size:0.60rem;font-weight:700;color:{stc}">{icon}</div>'
            f'<div style="font-size:0.55rem;color:#6B7280;margin-top:1px">{spec["id"]}</div>'
            f'</div>'
        )
    p.append(
        '</div>'
        '<div style="margin-top:7px;font-size:0.60rem;color:#9CA3AF;line-height:1.85">'
        '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;'
        'background:#16A34A;margin-right:3px"></span>caught<br>'
        '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;'
        'background:#EF4444;margin-right:3px"></span>unsafe<br>'
        '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;'
        'background:#F1F5F9;border:1px solid #CBD5E1;margin-right:3px"></span>normal'
        '</div>'
        '<div style="margin-top:8px;font-size:0.62rem;color:#9CA3AF;'
        'border-top:1px solid #F1F5F9;padding-top:7px;line-height:1.5">'
        'Final outcomes<br>&#8594; Results Dashboard'
        '</div>'
        '</div>'   # end specimens column
    )
    p.append('</div>')  # end two-column

    # ── Verdict bar ──────────────────────────────────────────────────────
    verdict = sv.get("verdict", "")
    if any(x in verdict for x in ["PASS", "1.00", "complete"]):
        vbg, vtc = "#F0FDF4", "#15803D"
    elif any(x in verdict for x in ["unsafe", "at risk"]):
        vbg, vtc = "#FEF2F2", "#B91C1C"
    else:
        vbg, vtc = "#FFFBEB", "#92400E"
    p.append(
        f'<div style="background:{vbg};border-radius:6px;padding:7px 12px;'
        f'font-size:0.71rem;font-weight:600;color:{vtc};margin-bottom:10px">'
        f'{verdict}</div>'
    )

    # ── Why this matters ─────────────────────────────────────────────────
    if why:
        p.append(
            '<div style="background:#F8FAFC;border-radius:6px;padding:9px 12px">'
            '<div style="font-size:0.64rem;font-weight:700;color:#64748B;text-transform:uppercase;'
            'letter-spacing:0.06em;margin-bottom:4px">Why this matters</div>'
            f'<div style="font-size:0.71rem;color:#475569;line-height:1.5">{why}</div>'
            '</div>'
        )

    return "".join(p)


# ---------------------------------------------------------------------------
# REPLAY_STEPS — narration cards for Agent Replay tab (module-level constant)
# ---------------------------------------------------------------------------
# Shared specimen lists reused across steps
_SPEC_S1_S2 = [
    {"id": "S100", "hold": False, "should_hold": False},
    {"id": "S101", "hold": True,  "should_hold": True},
    {"id": "S102", "hold": False, "should_hold": False},
    {"id": "S103", "hold": False, "should_hold": False},
    {"id": "S104", "hold": False, "should_hold": False},
    {"id": "S105", "hold": False, "should_hold": True},   # unsafe release
    {"id": "S106", "hold": False, "should_hold": True},   # unsafe release
    {"id": "S107", "hold": True,  "should_hold": True},
    {"id": "S108", "hold": False, "should_hold": False},
    {"id": "S109", "hold": False, "should_hold": False},
    {"id": "S110", "hold": False, "should_hold": False},
]
_SPEC_S3_S4_S5 = [
    {"id": "S100", "hold": False, "should_hold": False},
    {"id": "S101", "hold": True,  "should_hold": True},
    {"id": "S102", "hold": False, "should_hold": False},
    {"id": "S103", "hold": False, "should_hold": False},
    {"id": "S104", "hold": False, "should_hold": False},
    {"id": "S105", "hold": True,  "should_hold": True},
    {"id": "S106", "hold": True,  "should_hold": True},
    {"id": "S107", "hold": True,  "should_hold": True},
    {"id": "S108", "hold": False, "should_hold": False},
    {"id": "S109", "hold": False, "should_hold": False},
    {"id": "S110", "hold": False, "should_hold": False},
]

REPLAY_STEPS = [
    # ── RULE DERIVATION ─────────────────────────────────────────────────
    {
        "group": "rule_derivation",
        "title": "Step 1 — Initial exploration",
        "annotation": "Discovers broken seed config; re-derives contamination rules from KG",
        "why": (
            "The seed workflow used fixed absolute limits — useless for patients with no prior values. "
            "The agent had to identify this failure mode from the KG and switch to prior-relative "
            "delta-check detection before any contamination could be caught."
        ),
        "kg_nodes": ["EDTA_contamination", "K_acute_rise", "Ca_acute_fall"],
        "flag": None,
        "snapshot_visual": {
            "changed": (
                "Found broken seed: absolute-only contamination rules, swap detection disabled. "
                "Read KG, switched to prior-relative delta check, enabled swap. "
                "First triage: contamination HOLDs appeared — swap specimens still released."
            ),
            "params": [
                {"name": "detection mode",  "value": "prior_relative", "status": "ok",    "kg_source": "EDTA_contamination"},
                {"name": "Ca_delta_max",    "value": "−3.0 SD",        "status": "error", "kg_source": "Ca_acute_fall",       "kg": "−2.5 SD"},
                {"name": "fallback_Ca_max", "value": "1.80",            "status": "error", "kg_source": "new_patient_fallback", "kg": "7.2 mg/dL"},
                {"name": "swap enabled",    "value": "true",            "status": "ok",    "kg_source": "specimen_swap"},
                {"name": "Glucose weight",  "value": "0.01",            "status": "error", "kg_source": "specimen_swap",        "kg": "3.0"},
                {"name": "swap threshold",  "value": "1.0",             "status": "error", "kg_source": "decision_policy",      "kg": "0.3"},
            ],
            "specimens": _SPEC_S1_S2,
            "verdict": "2 of 4 problems caught · 2 unsafe releases · swap effectively disabled (threshold 1.0 unreachable)",
        },
    },
    {
        "group": "rule_derivation",
        "title": "Step 2 — Fixing contamination thresholds",
        "annotation": "Ca unit error caught — fallback threshold corrected from KG",
        "why": (
            "A Ca_max of 1.80 would have triggered HOLD on nearly every specimen in the batch. "
            "The KG node new_patient_fallback specifies the correct mg/dL value of 7.2. "
            "Getting units right is the difference between a useful rule and a false-hold flood."
        ),
        "kg_nodes": ["Ca_acute_fall", "new_patient_fallback", "contamination_detection"],
        "flag": None,
        "snapshot_visual": {
            "changed": (
                "Ca_delta_max was −3.0 SD (too strict) and fallback_Ca_max was 1.80 — "
                "mmol/L, wrong units. KG node Ca_acute_fall specifies −2.5 SD; "
                "new_patient_fallback specifies 7.2 mg/dL. Both corrected. "
                "Swap threshold still 1.0 — unreachable, so S105 and S106 remain at risk."
            ),
            "params": [
                {"name": "detection mode",  "value": "prior_relative", "status": "ok",    "kg_source": "EDTA_contamination"},
                {"name": "Ca_delta_max",    "value": "−2.5 SD",        "status": "ok",    "kg_source": "Ca_acute_fall"},
                {"name": "fallback_Ca_max", "value": "7.2 mg/dL",      "status": "ok",    "kg_source": "new_patient_fallback"},
                {"name": "swap enabled",    "value": "true",            "status": "ok",    "kg_source": "specimen_swap"},
                {"name": "Glucose weight",  "value": "0.04",            "status": "error", "kg_source": "specimen_swap",   "kg": "3.0"},
                {"name": "swap threshold",  "value": "1.0",             "status": "error", "kg_source": "decision_policy", "kg": "0.3"},
            ],
            "specimens": _SPEC_S1_S2,
            "verdict": "2 of 4 problems caught · swap threshold 1.0 is unreachable — identity swap specimens still at risk",
        },
    },
    {
        "group": "rule_derivation",
        "title": "Step 3 — Deriving exact swap weights",
        "annotation": "Glucose weight 3× extracted from KG; swap detection activated",
        "why": (
            "Glucose has roughly 3× the inter-patient variability of common electrolytes. "
            "Without this KG-derived weight, identity swaps between patients with similar K/Na/Ca "
            "but different glucose would score below the hold threshold and be silently released. "
            "The weight is not tunable by the agent — it is a published CLSI EP33 constant."
        ),
        "kg_nodes": ["specimen_swap", "glucose_recommended_weight", "decision_policy"],
        "flag": None,
        "snapshot_visual": {
            "changed": (
                "Read nodes specimen_swap and decision_policy. "
                "Set swap_hold_threshold to 0.3 — S105 and S106 now HOLDed. "
                "Glucose weight raised toward KG value but not exact (0.5 vs 3.0). "
                "contamination_hold_threshold still 1.0 — KG specifies 0.5."
            ),
            "params": [
                {"name": "Ca_delta_max",    "value": "−2.5 SD",  "status": "ok",    "kg_source": "Ca_acute_fall"},
                {"name": "fallback_Ca_max", "value": "7.2 mg/dL","status": "ok",    "kg_source": "new_patient_fallback"},
                {"name": "Glucose weight",  "value": "0.5",       "status": "warn",  "kg_source": "specimen_swap",   "kg": "3.0"},
                {"name": "swap threshold",  "value": "0.3",       "status": "ok",    "kg_source": "decision_policy"},
                {"name": "contam threshold","value": "1.0",       "status": "error", "kg_source": "decision_policy", "kg": "0.5"},
            ],
            "specimens": _SPEC_S3_S4_S5,
            "verdict": "4 of 4 caught · but Glucose weight and contam threshold not KG-exact — Layer 2 provenance check would fail",
        },
    },
    # ── DECISIONS REACHED ────────────────────────────────────────────────
    {
        "group": "decisions",
        "title": "Step 4 — Final workflow and correct triage",
        "annotation": "All 4 problem specimens correctly HOLDed; 7 normals released",
        "why": (
            "Four correct parameters — two contamination, two swap — must align simultaneously for "
            "F1 1.00. A single mis-set threshold drops either precision (excess holds) or recall "
            "(missed detections). S110, a CKD patient with chronically elevated K, tests whether "
            "the prior-relative rule avoids a false hold on an expected outlier."
        ),
        "kg_nodes": ["contamination_hold_threshold", "swap_hold_threshold"],
        "flag": "decisions",
        "snapshot_visual": {
            "changed": (
                "Finalised all parameters to exact KG values: "
                "Glucose weight 3.0 from nodes.specimen_swap.glucose_recommended_weight, "
                "contamination_hold_threshold 0.5 from nodes.decision_policy. "
                "Every parameter now traces to a named KG node. Layer 2: PASS."
            ),
            "params": [
                {"name": "Ca_delta_max",    "value": "−2.5 SD",  "status": "ok", "kg_source": "Ca_acute_fall"},
                {"name": "fallback_Ca_max", "value": "7.2 mg/dL","status": "ok", "kg_source": "new_patient_fallback"},
                {"name": "Glucose weight",  "value": "3.0",       "status": "ok", "kg_source": "specimen_swap"},
                {"name": "swap threshold",  "value": "0.3",       "status": "ok", "kg_source": "decision_policy"},
                {"name": "contam threshold","value": "0.5",       "status": "ok", "kg_source": "decision_policy"},
            ],
            "specimens": _SPEC_S3_S4_S5,
            "verdict": "4 of 4 caught · F1 1.00 · all parameters KG-derived · Layer 2: PASS",
        },
    },
    {
        "group": "decisions",
        "title": "Step 5 — Task confirmed complete",
        "annotation": "All thresholds traced to CLSI EP33; provenance verification passes",
        "why": (
            "Calling mark_task_complete triggers Layer 2 provenance verification: the framework "
            "compares each workflow parameter against its KG-sourced expected value. "
            "Because the agent read its thresholds from the graph rather than tuning them to the "
            "visible data, every parameter is within tolerance and the provenance check passes."
        ),
        "kg_nodes": [],
        "flag": "decisions",
        "snapshot_visual": {
            "changed": (
                "Marked task complete. Provenance verifier compared each workflow parameter "
                "against its KG node independently — every value within tolerance. "
                "No thresholds were fitted to the visible batch specimens. "
                "Reward 1.0 awarded."
            ),
            "params": [
                {"name": "F1 score",          "value": "1.00", "status": "ok"},
                {"name": "Unsafe releases",   "value": "0",    "status": "ok"},
                {"name": "False hold rate",   "value": "0.00", "status": "ok"},
                {"name": "Layer 2 provenance","value": "PASS", "status": "ok"},
                {"name": "Reward",            "value": "1.0",  "status": "ok"},
            ],
            "specimens": _SPEC_S3_S4_S5,
            "verdict": "Reward 1.0 · $0.12 · provenance verified · task complete",
        },
    },
]


# ===========================================================================
# Welcome dialog — shown once per session on first load
# ===========================================================================
@st.dialog("Welcome to LIS AI Validation", width="large")
def welcome_dialog():
    st.markdown(
        "An AI agent runs a laboratory safety task — classifying 11 specimens as safe to "
        "release or requiring review. Evaluated three times independently. Every run scored perfect.\n\n"
        "**But the score is not the interesting part.**"
    )
    st.markdown("**Three things to notice as you explore:**")
    with st.container(border=True):
        st.markdown(
            "**🔵 The knowledge graph is the agent's source of truth — not instructions or raw data**  \n"
            "The agent reads named nodes from a CLSI EP33 knowledge graph: `K_acute_rise`, "
            "`Ca_acute_fall`, `swap_hold_threshold`. Not a config file someone wrote — the "
            "published standard, translated into verifiable nodes. An independent verifier "
            "reads the same nodes after the run. That is what makes decisions auditable, not just correct."
        )
    with st.container(border=True):
        st.markdown(
            "**🟠 The agent modifies a workflow file using KG-derived parameters — "
            "so failures are trapped and the lab is notified**  \n"
            "The agent's only output is `workflow.json`. Every parameter in it traces to a KG node. "
            "The decision engine runs against this file — when a contaminated or swapped specimen "
            "matches the derived rules, it is held and the lab is informed."
        )
    with st.container(border=True):
        st.markdown(
            "**🟢 The audit trail is a first-class design requirement — not an afterthought**  \n"
            "Provenance verification is Layer 2 of the evaluation, equal in weight to decision quality. "
            "The framework asks not just 'did it work?' but 'can you prove every threshold came from "
            "the published standard?' That answer is recorded before the first specimen is processed."
        )
    st.markdown("")
    col_demo, col_about = st.columns(2)
    with col_demo:
        if st.button("📊 Start with the Demo", use_container_width=True, type="primary"):
            st.session_state.welcome_shown = True
            st.rerun()
    with col_about:
        if st.button("📖 Read the Introduction", use_container_width=True):
            st.session_state.welcome_shown = True
            st.session_state.go_about = True
            st.rerun()


# ===========================================================================
# PAGE — Introduction
# ===========================================================================
def page_about():
    with st.sidebar:
        st.divider()
        st.caption("Layer 1 — Decision quality  \nLayer 2 — Reasoning provenance")
        st.caption("Specimens: S100–S110 (11 total)")

    st.markdown("## LIS AI Validation — Introduction")
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

    # --- Three learning objectives ---
    st.markdown("---")
    st.markdown("## Three things this demo shows")
    oc1, oc2, oc3 = st.columns(3)
    with oc1:
        with st.container(border=True):
            st.markdown("**🔵 KG as source of truth**")
            st.markdown(
                "The agent reads named CLSI EP33 nodes — `K_acute_rise`, `Ca_acute_fall`, "
                "`swap_hold_threshold`. These are not instructions. They are the published standard "
                "translated into verifiable graph nodes. An independent verifier reads the same "
                "nodes after the run and checks every parameter independently."
            )
    with oc2:
        with st.container(border=True):
            st.markdown("**🟠 Workflow repair traps failures**")
            st.markdown(
                "The agent's only output is `workflow.json` with KG-derived parameters. "
                "The decision engine runs against it. When a contaminated or swapped specimen "
                "matches the derived rules, the hold is recorded and the lab is notified. "
                "The KG controls what failures are caught — not the agent's judgment."
            )
    with oc3:
        with st.container(border=True):
            st.markdown("**🟢 Audit is designed in**")
            st.markdown(
                "Provenance verification is Layer 2 of the evaluation — not a log viewer added "
                "after the fact. The framework records whether each parameter traces to the KG "
                "before the first specimen is processed. A CAP inspector asks for exactly this evidence."
            )

    st.markdown("---")

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
                "annotated narration cards. Watch the agent read the knowledge graph, "
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

    # --- Run it yourself ---
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
    st.link_button(
        "Setup instructions on GitHub →",
        "https://github.com/alexrabo/LISAgentValidation/blob/master/demo/README.md",
    )

    st.divider()

    # --- Why Layer 2 ---
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

**In most observability systems, the audit log is added after the system is built.** Here,
provenance verification is a first-class evaluation criterion — designed in before the first
specimen was processed. The KG is not just where the agent gets its rules. It is the chain
of evidence that an auditor, inspector, or patient safety officer can verify independently.
""")

    st.divider()

    # --- Repeatability and the feedback loop ---
    st.markdown("## Repeatability — the real strength of this approach")
    st.markdown("""
The featured run (`HsPAVBJ`) illustrates something important: even with clear instructions
to read the knowledge graph, the agent approximated the Glucose analyte weight in step 3
rather than reading its exact value from the KG. It corrected this in step 5 — but only
after guessing first.

This is not a failure of the framework. **It is exactly what the framework is designed to expose.**

The expanded Layer 2 verifier now checks four parameters — including `swap_detection.analyte_weights.Glucose`.
A run that guesses this value instead of reading it from `nodes.specimen_swap.glucose_recommended_weight`
will fail Layer 2, even if the triage decisions happen to be correct on the visible batch.
Run `hJQzBJW` (4 steps) would not pass this check.

This is the feedback mechanism:

1. **Run** — agent attempts the task
2. **Evaluate** — Layer 2 finds any parameter not grounded in the KG
3. **Improve** — the task prompt is strengthened to close the gap
4. **Re-run** — verify the improvement holds across multiple independent runs

**Repeatability across runs — not any single run — is what builds confidence.**
An agent that reads every threshold from the KG, independently, on every run, under varying
conditions, with the same result each time: that is the evidence a lab director, CAP inspector,
or patient safety officer can stand behind. A single lucky run is not.

The TerminalBench framework makes this loop systematic: every run is an independent trial,
every parameter is verifiable, and the prompt can be improved in response to what Layer 2 finds.

**The ultimate goal is to move from non-deterministic to deterministic agent behaviour.**
Today, different runs produce different reasoning paths to the same answer — some read the KG
correctly on the first attempt, some guess and self-correct, one got lucky with a fallback default.
That is non-determinism. The target is a prompt so precise, and a verifier so complete, that
every future run derives every parameter from the KG by construction — with no guessing, no
approximation, and no dependence on which commands happen to work.
A fully deterministic run is one where Layer 2 passes not because the agent was careful,
but because the task design left no room for any other outcome.

The implementation of both must be **sticky** — co-designed and tightened together.
A precise prompt without a complete verifier can be bypassed by a lucky approximation that
happens to produce correct decisions on the visible batch.
A complete verifier without a precise prompt generates failures but gives the agent no
structural path to the right answer.
Only when the prompt makes KG adherence the path of least resistance, and the verifier
catches every deviation from it, does the system become self-reinforcing:
the agent is guided toward determinism, and any regression is immediately visible.
""")

    st.divider()

    # --- Phase 2 / Allotrope ---
    st.markdown("## Phase 2 — Allotrope ADM")
    st.markdown(
        "This demo seeds specimen data manually. In production, data arrives as "
        "**Allotrope Foundation Data Model (ADM)** documents directly from analysers — "
        "the emerging industry standard for structured instrument output. "
        "ADM adds chain-of-custody fields (`container_type`, `instrument_id`, `reagent_lot`) "
        "that become additional nodes in the knowledge graph's contamination reasoning path. "
        "This demo is the decision framework. Allotrope ADM is the data layer that makes it production-grade."
    )


# ===========================================================================
# PAGE — Demo
# ===========================================================================
def page_demo():
    with st.sidebar:
        st.divider()
        st.caption("Layer 1 — Decision quality  \nLayer 2 — Reasoning provenance")
        st.caption("Specimens: S100–S110 (11 total)")

    results   = load_results()
    decisions = load_decisions()
    agg       = results["metrics"]["aggregate"]
    provenance = results["provenance"]

    tab_results, tab_scatter, tab_replay, tab_glossary = st.tabs([
        "📋  Results Dashboard",
        "📊  Decision Space",
        "▶   Agent Replay",
        "📖  Glossary",
    ])

    # =========================================================================
    # TAB 1 — Results Dashboard
    # =========================================================================
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
        f1     = agg["f1"]
        fhr    = agg["false_hold_rate"]
        prec   = agg["precision"]
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
            (col_hid, "hidden",  "Hidden batch"),
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

    # =========================================================================
    # TAB 2 — Decision Space scatter
    # =========================================================================
    with tab_scatter:
        st.caption("Every specimen plotted on contamination score vs. swap score — see where the agent drew the line and why S110 (CKD) sits at the origin.")

        st.markdown("<p class='section-header'>Contamination score vs identity swap score — all specimens</p>", unsafe_allow_html=True)
        st.caption(
            "Each point is one specimen. Threshold lines mark the decision boundary — "
            "values are not shown (proprietary KG parameters)."
        )

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

        CONTAM_THRESHOLD = 0.5   # not displayed
        SWAP_THRESHOLD   = 0.3   # not displayed

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

    # =========================================================================
    # TAB 3 — Agent Replay
    # =========================================================================
    with tab_replay:
        st.caption("Watch the agent derive rules from the knowledge graph and triage all 11 specimens — terminal recording synchronized with annotated decision steps.")
        st.markdown("<p class='section-header'>Agent terminal session — verified run</p>", unsafe_allow_html=True)
        st.caption("Run ID: `lis-swap-contamination-triage__HsPAVBJ` · Reward: 1.0 · Cost: $0.12 · GPT-5")
        st.info("**Click inside the terminal for playback controls** — play/pause, progress bar, speed.", icon="▶")

        cast_content = fetch_recording_cast()

        if cast_content:
            markers      = get_cast_markers(cast_content)
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

                flag    = step.get("flag") or ""
                border  = "#16A34A" if flag == "decisions" else "#6B7280"
                bg_card = "#F0FDF4" if flag == "decisions" else "#ffffff"

                annotation_div = (
                    f'<div style="font-size:0.71rem;color:#6B7280;font-style:italic;'
                    f'margin-top:2px;line-height:1.35">'
                    f'{step["annotation"]}</div>'
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
                    f'{annotation_div}'
                    f'{kg_div}'
                    f'<div style="text-align:right;margin-top:6px">'
                    f'<a class="snap-link" href="#" onclick="openStepModal({idx});return false;" '
                    f'style="font-size:0.68rem;color:#3B82F6;text-decoration:none;'
                    f'opacity:0.75;transition:opacity 0.15s,font-weight 0.15s" '
                    f'onmouseover="this.style.opacity=1" onmouseout="this.style.opacity=0.75">'
                    f'View full snapshot &#8594;</a>'
                    f'</div>'
                    f'</div>'
                )

                resume_bar_html = (
                '<div id="resume-bar" style="display:none;background:#DBEAFE;border-radius:6px;'
                'padding:6px 10px;margin-bottom:8px;align-items:center;gap:8px;'
                'position:sticky;top:0;z-index:10">'
                '<span style="font-size:0.68rem;color:#1E40AF;flex:1">'
                '&#9646;&nbsp;Paused — review this step, then</span>'
                '<button onclick="resumePlayer()" style="font-size:0.68rem;padding:3px 12px;'
                'background:#3B82F6;color:white;border:none;border-radius:4px;cursor:pointer;'
                'white-space:nowrap">&#9654;&nbsp;Resume</button>'
                '</div>'
            )
            narration_html = resume_bar_html + "\n" + "\n".join(cards_html)

            snapshots_json = json.dumps([
                {
                    "title":         s["title"],
                    "annotation":    s["annotation"],
                    "kg_nodes":      s.get("kg_nodes") or [],
                    "snapshot_html": _build_snapshot_html(
                        s.get("snapshot_visual", {}),
                        s.get("why", ""),
                    ),
                }
                for s in REPLAY_STEPS
            ])

            # ------------------------------------------------------------------
            # Modal overlay HTML
            # ------------------------------------------------------------------
            modal_html = (
                '<div id="step-modal" onclick="if(event.target===this)closeStepModal()" '
                'style="display:none;position:fixed;top:0;left:0;width:100%;height:100%;'
                'background:rgba(0,0,0,0.52);z-index:9999;box-sizing:border-box">'
                '  <div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);'
                '       width:92%;max-width:640px;max-height:88%;overflow-y:auto;'
                '       background:#fff;border-radius:10px;padding:20px 22px 16px;'
                '       box-shadow:0 12px 40px rgba(0,0,0,0.22);box-sizing:border-box">'
                '    <div id="step-modal-content"></div>'
                '    <div style="display:flex;justify-content:flex-end;margin-top:14px">'
                '      <button onclick="closeStepModal()" style="padding:5px 18px;border:1px solid #D1D5DB;'
                '              border-radius:5px;background:#F9FAFB;cursor:pointer;font-size:0.78rem;'
                '              color:#374151">Close</button>'
                '    </div>'
                '  </div>'
                '</div>'
            )

            # ------------------------------------------------------------------
            # Combined component: player (left) + narration panel (right)
            # ------------------------------------------------------------------
            component_html = (
                '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/asciinema-player@3.8.0/dist/bundle/asciinema-player.min.css"/>'
                '<style>'
                '.n-card.active{background:#EFF6FF!important;border-left-color:#3B82F6!important;box-shadow:0 0 0 1px #BFDBFE}'
                '.n-card.active .snap-link{opacity:1!important;font-weight:700!important;color:#1D4ED8!important;font-size:0.73rem!important}'
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
                + modal_html +
                '<script src="https://cdn.jsdelivr.net/npm/asciinema-player@3.8.0/dist/bundle/asciinema-player.min.js"></script>'
                '<script>'
                f'const MARKERS={markers_json};'
                f'const SNAPSHOTS={snapshots_json};'
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
                '  if(active>=0){'
                '    try{player.pause();}catch(e){}'
                '    document.getElementById("resume-bar").style.display="flex";'
                '  }'
                '  document.querySelectorAll(".n-card").forEach(function(c,i){'
                '    if(i===active){c.classList.add("active");c.scrollIntoView({behavior:"smooth",block:"nearest"});}'
                '    else{c.classList.remove("active");}'
                '  });'
                '},250);'
                'function resumePlayer(){'
                '  try{player.play();}catch(e){}'
                '  document.getElementById("resume-bar").style.display="none";'
                '}'
                'function openStepModal(i){'
                '  var s=SNAPSHOTS[i];'
                '  var kgBadges=s.kg_nodes.map(function(n){'
                '    return \'<span style="background:#EFF6FF;color:#3B82F6;border-radius:3px;padding:1px 6px;\'+\'font-size:0.63rem;margin-right:3px;font-family:monospace">\'+n+\'</span>\';'
                '  }).join("");'
                '  var kgSection=kgBadges?\'<div style="margin-bottom:10px">\'+kgBadges+\'</div>\':"";'
                '  document.getElementById("step-modal-content").innerHTML='
                '    \'<div style="font-size:0.85rem;font-weight:700;color:#111827;margin-bottom:2px">\'+s.title+\'</div>\''
                '   +\'<div style="font-size:0.72rem;color:#6B7280;font-style:italic;margin-bottom:10px">\'+s.annotation+\'</div>\''
                '   +kgSection'
                '   +s.snapshot_html;'
                '  document.getElementById("step-modal").style.display="block";'
                '}'
                'function closeStepModal(){'
                '  document.getElementById("step-modal").style.display="none";'
                '}'
                'document.addEventListener("keydown",function(e){if(e.key==="Escape")closeStepModal();});'
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
                kg = " · ".join(step.get("kg_nodes") or [])
                kg_line = f"<div style='font-size:0.70rem;color:#3B82F6;margin-top:3px'>{kg}</div>" if kg else ""
                st.markdown(
                    f'<div class="step-card phase-triage {step.get("flag") or ""}">'
                    f'<div style="font-size:0.80rem;font-weight:600;color:#111827">{step["title"]}</div>'
                    f'<div style="font-size:0.71rem;color:#6B7280;font-style:italic;margin-top:2px">{step["annotation"]}</div>'
                    f'{kg_line}</div>',
                    unsafe_allow_html=True,
                )
                with st.expander("View full snapshot"):
                    st.markdown(f"**{step['title']}**")
                    st.markdown(step["detail"])
                    if step.get("why"):
                        st.markdown("**Why this matters**")
                        st.markdown(step["why"])
                    if step.get("command"):
                        st.code(step["command"], language=None)

    # =========================================================================
    # TAB 4 — Glossary
    # =========================================================================
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


# ===========================================================================
# Entrypoint — runs on every page load
# ===========================================================================

# Sidebar header (appears above nav links)
with st.sidebar:
    st.markdown("### 🧪 LIS AI Validation")
    st.caption("CLSI EP33 · Two-layer evaluation framework")

# Custom sidebar toggle button (replaces native Streamlit button)
# Injected into parent DOM via same-origin iframe access
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

# Session state
if "welcome_shown" not in st.session_state:
    st.session_state.welcome_shown = False
if "go_about" not in st.session_state:
    st.session_state.go_about = False

# Page definitions
PAGE_DEMO  = st.Page(page_demo,  title="Demo",         icon="📊", default=True,  url_path="demo")
PAGE_ABOUT = st.Page(page_about, title="Introduction",  icon="📖", default=False, url_path="about")

# Register navigation (renders nav links in sidebar)
pg = st.navigation([PAGE_DEMO, PAGE_ABOUT])

# Deferred navigation from welcome dialog "Read Introduction" button
if st.session_state.go_about:
    st.session_state.go_about = False
    st.switch_page(PAGE_ABOUT)

# Run selected page
pg.run()

# Show welcome modal on first visit (overlays rendered page content)
if not st.session_state.welcome_shown:
    welcome_dialog()
