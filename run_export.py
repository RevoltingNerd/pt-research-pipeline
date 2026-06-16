"""
run_export.py — Step 6: Export Excel workbook
PT Research Pipeline v2

Reads the three ledger CSVs (layer0, layer2, layer3) and the Layer 3 cluster
definitions, then writes a single multi-sheet Excel workbook suitable for
SharePoint upload, Power BI connection, or direct distribution.

Sheets:
  1. Summary         — one row per cluster: GRADE certainty, recommendation,
                       governance finding, article count
  2. Articles_L2     — one row per Layer 2 appraised article: full appraisal
                       fields, Oxford level, spin, governance flags
  3. Articles_L0     — all screened articles: Oxford, relevance, study design
  4. Clusters        — cluster definitions discovered by Layer 3
  5. Governance      — extracted governance flags across all L2 articles
  6. Meta            — run metadata: topic, research question, date, model info

Usage:
    python3 run_export.py
    python3 run_export.py --output my_output.xlsx
"""

import argparse
import json
import logging
import os
import sys
import yaml
from datetime import datetime
from pathlib import Path

import pandas as pd

PIPELINE_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PIPELINE_ROOT))
os.chdir(PIPELINE_ROOT)

LOG_PATH = Path(f"logs/export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
LOG_PATH.parent.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_PATH)]
)
log = logging.getLogger(__name__)


# ── Column display maps ───────────────────────────────────────────────────────

OXFORD_LABELS = {
    "1a": "1a — SR of RCTs",
    "1b": "1b — Individual RCT",
    "1c": "1c — All-or-none",
    "2a": "2a — SR of cohorts",
    "2b": "2b — Cohort / low-quality RCT",
    "2c": "2c — Outcomes research",
    "3a": "3a — SR of case-control",
    "3b": "3b — Case-control",
    "4":  "4 — Case series",
    "5":  "5 — Expert opinion / review",
}

GRADE_ORDER = {"High": 0, "Moderate": 1, "Low": 2, "Very Low": 3, "": 9}


def load_csv(path: str, label: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        log.warning(f"{label} not found at {path} — sheet will be empty")
        return pd.DataFrame()
    df = pd.read_csv(p, dtype=str).fillna("")
    log.info(f"  {label}: {len(df)} rows")
    return df


def build_summary_sheet(cfg: dict) -> pd.DataFrame:
    """One row per cluster — the executive summary sheet."""
    layer3_dir = Path("summaries/layer3")
    master_path = layer3_dir / "MASTER_GRADE_SYNTHESIS.json"

    if not master_path.exists():
        log.warning("MASTER_GRADE_SYNTHESIS.json not found — Summary sheet will be empty")
        return pd.DataFrame()

    syntheses = json.loads(master_path.read_text())

    rows = []
    for s in syntheses:
        rows.append({
            "Cluster":                s.get("cluster", "").replace("_", " ").title(),
            "GRADE Certainty":        s.get("grade_certainty", ""),
            "Recommendation":         s.get("recommendation_direction", "").upper(),
            "Strength":               s.get("recommendation_strength", "").title(),
            "Articles (n)":           s.get("article_count", ""),
            "Clinician Recommendation": s.get("clinician_recommendation", ""),
            "Key Caveat":             s.get("key_caveat", ""),
            "Key Findings":           s.get("key_findings", ""),
            "Spin Summary":           s.get("spin_summary", ""),
            "Governance Finding":     s.get("governance_finding", ""),
            "Governance Recommendation": s.get("governance_recommendation", ""),
            "Future Research Priority": s.get("future_research_priority", ""),
            "Oxford Distribution":    s.get("oxford_summary", ""),
            "Certainty Rationale":    s.get("grade_certainty_rationale", ""),
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df["_sort"] = df["GRADE Certainty"].map(GRADE_ORDER)
        df = df.sort_values("_sort").drop(columns=["_sort"])
    return df


def build_articles_l2_sheet(clusters_df: pd.DataFrame) -> pd.DataFrame:
    """One row per Layer 2 article with full appraisal fields."""
    deep_dir = Path("summaries/deep")
    jsons = list(deep_dir.glob("*_layer2.json"))

    if not jsons:
        log.warning("No Layer 2 JSON files found — Articles_L2 sheet will be empty")
        return pd.DataFrame()

    # Build cluster lookup from CSV if available
    cluster_lookup = {}
    if not clusters_df.empty and "pmid" in clusters_df.columns:
        for _, row in clusters_df.iterrows():
            cluster_lookup[str(row["pmid"])] = row.get("cluster", "")

    rows = []
    for f in sorted(jsons):
        d = json.loads(f.read_text())
        pmid = str(d.get("pmid", ""))
        rows.append({
            "PMID":                    pmid,
            "PMID Link":               f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
            "Title":                   d.get("title", ""),
            "Authors":                 d.get("authors", ""),
            "Journal":                 d.get("journal", ""),
            "Year":                    d.get("publication_year", ""),
            "Cluster":                 cluster_lookup.get(pmid, ""),
            "Oxford Level":            OXFORD_LABELS.get(d.get("oxford_level",""), d.get("oxford_level","")),
            "Oxford Roman":            d.get("oxford_roman", ""),
            "Downgraded":              d.get("downgraded", ""),
            "Downgrade Reason":        d.get("downgrade_reason", ""),
            "Study Design":            d.get("study_design", ""),
            "Clinical Domain":         d.get("clinical_domain", ""),
            "Sample Size":             d.get("sample_size", ""),
            "Intervention":            d.get("intervention", ""),
            "Comparator":              d.get("comparator", ""),
            "Primary Outcome":         d.get("primary_outcome", ""),
            "Primary Result":          d.get("primary_result", ""),
            "Bias Risk":               d.get("bias_risk_structured", ""),
            "Blinding":                d.get("blinding", ""),
            "Dropout Rate":            d.get("dropout_rate", ""),
            "ITT Analysis":            d.get("intention_to_treat", ""),
            "Population":              d.get("population", ""),
            "Setting":                 d.get("clinical_setting", ""),
            "Geography":               d.get("geographic_context", ""),
            "Generalizability":        d.get("generalizability", ""),
            "Spin Detected":           d.get("spin_detected", ""),
            "Spin Detail":             d.get("spin_detail", ""),
            "Statistical Significance": d.get("statistical_significance", ""),
            "Clinical Significance":   d.get("clinical_significance", ""),
            "Effect Size Summary":     d.get("effect_size_summary", ""),
            "Implementation Result":   d.get("implementation_result", ""),
            "GRADE Bias":              d.get("grade_risk_of_bias", ""),
            "GRADE Indirectness":      d.get("grade_indirectness", ""),
            "GRADE Imprecision":       d.get("grade_imprecision", ""),
            "Key Takeaway":            d.get("key_takeaway", ""),
            "Evidence Statement":      d.get("evidence_statement", ""),
            "Clinical Necessity":      d.get("clinical_necessity", ""),
            "Appraisal Confidence":    d.get("appraisal_confidence", ""),
            "Research Relevance":      d.get("research_relevance", ""),
            # 5-dimension governance/deployment-readiness taxonomy (Stage 6)
            "Gov Implemented (/5)":    d.get("governance_implemented_count", ""),
            "Gov Aspirational (/5)":   d.get("governance_aspirational_count", ""),
            "Gov Not Addressed (/5)":  d.get("governance_not_addressed_count", ""),
            "Governance Overall Summary": d.get("governance_overall_summary", ""),
        })

    df = pd.DataFrame(rows)
    # Sort by cluster then Oxford level
    if not df.empty:
        df = df.sort_values(["Cluster", "Oxford Roman"])
    return df


GOVERNANCE_DIMENSIONS = [
    ("scope_of_practice",        "Scope of Practice"),
    ("output_validation",        "Output Validation"),
    ("guardrails_safety",        "Guardrails / Safety"),
    ("accountability_liability", "Accountability / Liability"),
    ("training_competency",      "Training / Competency"),
]


def build_governance_sheet(l2_df: pd.DataFrame) -> pd.DataFrame:
    """
    Governance / deployment-readiness flags extracted from all L2 articles —
    key sheet for the SIG chair. Uses the 5-dimension implemented /
    aspirational / not_addressed taxonomy from Stage 6.
    """
    if l2_df.empty:
        return pd.DataFrame()

    gov_cols = [
        "PMID", "PMID Link", "Title", "Journal", "Year", "Cluster",
        "Oxford Roman", "Spin Detected",
    ]
    existing = [c for c in gov_cols if c in l2_df.columns]
    df = l2_df[existing].copy()

    # Re-read full governance data from JSON (not all fields are in the L2 sheet)
    deep_dir = Path("summaries/deep")
    gov_data = {}
    for f in deep_dir.glob("*_layer2.json"):
        d = json.loads(f.read_text())
        pmid = str(d.get("pmid", ""))
        dims = d.get("governance_dimensions", {}) or {}

        row = {
            "Gov Implemented (/5)":   d.get("governance_implemented_count", 0),
            "Gov Aspirational (/5)":  d.get("governance_aspirational_count", 0),
            "Gov Not Addressed (/5)": d.get("governance_not_addressed_count", 0),
            "Governance Overall Summary": d.get("governance_overall_summary", ""),
            "Governance Synthesis":   d.get("governance_synthesis", ""),
            "Patient Safety Concerns": d.get("patient_safety_concerns", ""),
            "Ethical Considerations": d.get("ethical_considerations", ""),
            "Implementation Barriers": d.get("implementation_barriers", ""),
            "Future Research":        d.get("future_research_stated", ""),
            "Internal Consistency":   d.get("internal_consistency", ""),
            "Limitations Stated":     d.get("limitations_stated", ""),
        }

        # One column per dimension: "<status> — <detail>" or just status if no detail
        for key, label in GOVERNANCE_DIMENSIONS:
            entry  = dims.get(key, {}) or {}
            status = entry.get("status", "not_addressed")
            detail = entry.get("detail", "none")
            if detail and detail.lower() != "none":
                row[label] = f"{status} — {detail}"
            else:
                row[label] = status

        gov_data[pmid] = row

    all_cols = (
        ["Gov Implemented (/5)", "Gov Aspirational (/5)", "Gov Not Addressed (/5)"]
        + [label for _, label in GOVERNANCE_DIMENSIONS]
        + ["Governance Overall Summary", "Governance Synthesis",
           "Patient Safety Concerns", "Ethical Considerations",
           "Implementation Barriers", "Future Research",
           "Internal Consistency", "Limitations Stated"]
    )
    for col in all_cols:
        df[col] = df["PMID"].map(lambda p: gov_data.get(p, {}).get(col, ""))

    # Sort: articles that engage MOST with governance first (lowest "not
    # addressed" count, then highest "implemented" count) — surfaces the
    # most actionable articles for SIG education planning at the top.
    df = df.sort_values(
        ["Gov Not Addressed (/5)", "Gov Implemented (/5)"],
        ascending=[True, False],
    )
    return df


def build_clusters_sheet() -> pd.DataFrame:
    """Cluster definitions discovered by the dynamic clustering pass."""
    defs_path = Path("layer3_cluster_definitions.json")
    if not defs_path.exists():
        log.warning("layer3_cluster_definitions.json not found — Clusters sheet will be empty")
        return pd.DataFrame()

    data = json.loads(defs_path.read_text())
    clusters    = data.get("clusters", [])
    definitions = data.get("definitions", {})

    rows = [{"Cluster": c.replace("_", " ").title(),
             "Cluster Key": c,
             "Definition": definitions.get(c, "")}
            for c in clusters]
    return pd.DataFrame(rows)


def build_meta_sheet(cfg: dict) -> pd.DataFrame:
    """Run metadata for audit trail."""
    topic  = cfg.get("topic", {})
    models = cfg.get("model", {})

    rows = [
        ("Topic",              topic.get("short_name", "")),
        ("Research Question",  cfg.get("research_question", "").strip()),
        ("Relevance Criterion", topic.get("relevance_criterion", "").strip()),
        ("Intervention Noun",  topic.get("intervention_noun", "")),
        ("Governance Focus",   topic.get("governance_focus", "").strip()),
        ("Layer 0 Model",      models.get("layer0", "")),
        ("Layer 2 Model",      models.get("layer2", "")),
        ("Layer 3 Model",      models.get("layer3", "")),
        ("Export Date",        datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("Pipeline Version",   "PT Research Pipeline v2"),
    ]
    return pd.DataFrame(rows, columns=["Field", "Value"])


def apply_formatting(writer, df: pd.DataFrame, sheet_name: str,
                     col_widths: dict = None):
    """Apply basic column widths and freeze the header row."""
    if df.empty:
        return
    ws = writer.sheets[sheet_name]
    # Freeze header
    ws.freeze_panes(1, 0)
    # Auto-width with cap
    for i, col in enumerate(df.columns):
        width = col_widths.get(col, None) if col_widths else None
        if width is None:
            max_len = max(
                len(str(col)),
                df[col].astype(str).str.len().max() if not df.empty else 0
            )
            width = min(max(max_len + 2, 10), 60)
        ws.set_column(i, i, width)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=str, default=None,
                        help="Output path for the Excel workbook")
    args = parser.parse_args()

    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)

    for key, val in cfg["paths"].items():
        if not os.path.isabs(val):
            cfg["paths"][key] = str(PIPELINE_ROOT / val)

    topic_name  = cfg.get("topic", {}).get("short_name", "research")
    today       = datetime.now().strftime("%Y%m%d")
    safe_topic  = topic_name.replace(" ", "_").lower()
    output_path = args.output or f"{safe_topic}_evidence_base_{today}.xlsx"

    log.info("=" * 60)
    log.info(f"PT Research Pipeline v2 — Export")
    log.info(f"Topic:  {topic_name}")
    log.info(f"Output: {output_path}")
    log.info("=" * 60)

    log.info("Loading data...")
    l0_df       = load_csv(cfg["paths"]["layer0_ledger"], "Layer 0 ledger")
    if not l0_df.empty and "pmid" in l0_df.columns:
        # Insert link column right after pmid for readability
        pmid_idx = l0_df.columns.get_loc("pmid")
        l0_df.insert(pmid_idx + 1, "pmid_link",
                      l0_df["pmid"].map(lambda p: f"https://pubmed.ncbi.nlm.nih.gov/{p}/" if p else ""))
    clusters_df = load_csv("layer3_clusters.csv",         "Layer 3 clusters")

    log.info("Building sheets...")
    summary_df    = build_summary_sheet(cfg)
    l2_df         = build_articles_l2_sheet(clusters_df)
    governance_df = build_governance_sheet(l2_df)
    cluster_df    = build_clusters_sheet()
    meta_df       = build_meta_sheet(cfg)

    log.info(f"Writing workbook: {output_path}")
    try:
        import xlsxwriter
    except ImportError:
        log.error("xlsxwriter not installed — run: pip install xlsxwriter")
        sys.exit(1)

    with pd.ExcelWriter(output_path, engine="xlsxwriter") as writer:

        sheets = [
            ("Summary",      summary_df),
            ("Articles_L2",  l2_df),
            ("Articles_L0",  l0_df),
            ("Clusters",     cluster_df),
            ("Governance",   governance_df),
            ("Meta",         meta_df),
        ]

        LINK_COLS = {"PMID Link", "pmid_link"}
        link_fmt = writer.book.add_format({
            "font_color": "#1155CC", "underline": 1, "align": "left", "valign": "top",
        })

        for sheet_name, df in sheets:
            if df.empty:
                pd.DataFrame({"Note": [f"No data available for {sheet_name}"]}).to_excel(
                    writer, sheet_name=sheet_name, index=False)
                log.warning(f"  {sheet_name}: empty — placeholder written")
            else:
                df.to_excel(writer, sheet_name=sheet_name, index=False)
                apply_formatting(writer, df, sheet_name)

                # Convert plain-text PubMed URLs into clickable hyperlinks
                link_cols = [c for c in df.columns if c in LINK_COLS]
                if link_cols:
                    ws = writer.sheets[sheet_name]
                    for col_name in link_cols:
                        col_idx = df.columns.get_loc(col_name)
                        for row_idx, url in enumerate(df[col_name], start=1):
                            if url:
                                ws.write_url(row_idx, col_idx, url,
                                              cell_format=link_fmt, string="PubMed")
                        ws.set_column(col_idx, col_idx, 10)

                log.info(f"  {sheet_name}: {len(df)} rows")

        # Workbook-level formatting
        wb = writer.book
        header_fmt = wb.add_format({
            "bold": True, "bg_color": "#1F4E79", "font_color": "white",
            "border": 1, "text_wrap": True, "valign": "top",
        })
        # Apply header format to all sheets
        for sheet_name, df in sheets:
            if df.empty:
                continue
            ws = writer.sheets[sheet_name]
            for col_num, col_name in enumerate(df.columns):
                ws.write(0, col_num, col_name, header_fmt)

    log.info(f"\nExport complete: {output_path}")
    log.info(f"Sheets: Summary, Articles_L2, Articles_L0, Clusters, Governance, Meta")


if __name__ == "__main__":
    main()
