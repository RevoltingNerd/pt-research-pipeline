"""
run_report.py — Step 7: Generate markdown synthesis report
PT Research Pipeline v2

Reads the Layer 3 GRADE syntheses and Layer 2 appraisals, then writes a
single structured markdown report suitable for distribution, publication
as a scoping review summary, or upload to SharePoint/Confluence.

Report sections:
  1. Header — topic, research question, run date
  2. Executive Summary — corpus stats, GRADE distribution, key headline findings
  3. Per-cluster synthesis — GRADE certainty, recommendation, key findings,
     governance finding, spin rate
  4. Governance Synthesis — cross-cluster governance and safety findings
  5. Spin Analysis — cross-cluster spin detection summary
  6. Methods note — pipeline description for Methods sections
  7. Appendix — Oxford level distribution, article count by cluster

Usage:
    python3 run_report.py
    python3 run_report.py --output my_report.md
"""

import argparse
import json
import logging
import os
import sys
import yaml
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd

PIPELINE_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PIPELINE_ROOT))
os.chdir(PIPELINE_ROOT)

LOG_PATH = Path(f"logs/report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
LOG_PATH.parent.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_PATH)]
)
log = logging.getLogger(__name__)

GRADE_ICON  = {"High": "🟢", "Moderate": "🟡", "Low": "🟠", "Very Low": "🔴"}
GRADE_ORDER = {"High": 0, "Moderate": 1, "Low": 2, "Very Low": 3}


def load_l2_articles() -> list:
    deep_dir = Path("summaries/deep")
    articles = []
    for f in sorted(deep_dir.glob("*_layer2.json")):
        articles.append(json.loads(f.read_text()))
    return articles


def load_syntheses() -> list:
    master = Path("summaries/layer3/MASTER_GRADE_SYNTHESIS.json")
    if not master.exists():
        return []
    return json.loads(master.read_text())


def load_cluster_definitions() -> dict:
    p = Path("layer3_cluster_definitions.json")
    if not p.exists():
        return {}
    return json.loads(p.read_text()).get("definitions", {})


def corpus_stats(articles: list) -> dict:
    n = len(articles)
    if not n:
        return {}

    oxford_counts = Counter(a.get("oxford_roman", "?") for a in articles)
    spin_count    = sum(1 for a in articles if a.get("spin_detected", "").lower() == "yes")
    gov_count     = sum(1 for a in articles
                        if a.get("governance_recommendations", "none stated").lower()
                        not in ("none stated", "", "not_stated")
                        and len(a.get("governance_recommendations", "")) > 20)
    gov_gap_count = sum(1 for a in articles
                        if a.get("governance_claim_without_method", "").lower() == "yes")
    bias_counts   = Counter(a.get("bias_risk_structured", "unclear") for a in articles)

    return {
        "n": n,
        "oxford_counts": dict(oxford_counts),
        "spin_count": spin_count,
        "spin_pct": round(100 * spin_count / n),
        "gov_count": gov_count,
        "gov_pct": round(100 * gov_count / n),
        "gov_gap_count": gov_gap_count,
        "gov_gap_pct": round(100 * gov_gap_count / n),
        "bias_counts": dict(bias_counts),
    }


def oxford_table(counts: dict) -> str:
    order = ["I", "II", "III", "IV", "V"]
    labels = {
        "I":   "Level I (SR/RCT)",
        "II":  "Level II (Cohort/low-quality RCT)",
        "III": "Level III (Case-control)",
        "IV":  "Level IV (Case series)",
        "V":   "Level V (Expert opinion/review)",
    }
    total = sum(counts.values())
    lines = ["| Oxford Level | n | % |", "|---|---|---|"]
    for lvl in order:
        n = counts.get(lvl, 0)
        if n:
            pct = round(100 * n / total)
            lines.append(f"| {labels.get(lvl, lvl)} | {n} | {pct}% |")
    return "\n".join(lines)


def build_report(cfg: dict) -> str:
    topic     = cfg.get("topic", {})
    rq        = cfg.get("research_question", "").strip()
    short     = topic.get("short_name", "the intervention")
    gov_focus = topic.get("governance_focus", "governance and responsible practice").strip()
    today     = datetime.now().strftime("%Y-%m-%d")
    models    = cfg.get("model", {})

    articles    = load_l2_articles()
    syntheses   = load_syntheses()
    cluster_defs = load_cluster_definitions()
    stats       = corpus_stats(articles)

    # Sort syntheses by GRADE certainty
    syntheses_sorted = sorted(
        syntheses, key=lambda s: GRADE_ORDER.get(s.get("grade_certainty", ""), 9))

    lines = []

    # ── Header ───────────────────────────────────────────────────────────────
    lines += [
        f"# Evidence Synthesis Report: {short.title()}",
        f"",
        f"**Generated:** {today}  ",
        f"**Pipeline:** PT Research Pipeline v2  ",
        f"**Models:** Layer 0 — {models.get('layer0','')} · "
        f"Layer 2 — {models.get('layer2','')} · "
        f"Layer 3 — {models.get('layer3','')}",
        f"",
        f"---",
        f"",
        f"## Research Question",
        f"",
        f"> {rq}",
        f"",
        f"---",
        f"",
    ]

    # ── Executive Summary ────────────────────────────────────────────────────
    n_clusters = len(syntheses)
    if stats:
        high_mod = sum(1 for s in syntheses
                       if s.get("grade_certainty","") in ("High","Moderate"))
        lines += [
            f"## Executive Summary",
            f"",
            f"This scoping review synthesised **{stats.get('n',0)} articles** "
            f"across **{n_clusters} clinical clusters** on {short}.",
            f"",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total articles appraised (Layer 2) | {stats.get('n', 0)} |",
            f"| Clinical clusters identified | {n_clusters} |",
            f"| Clusters with High/Moderate GRADE certainty | {high_mod}/{n_clusters} |",
            f"| Articles with spin detected | {stats.get('spin_count',0)} "
            f"({stats.get('spin_pct',0)}%) |",
            f"| Articles with governance recommendations | {stats.get('gov_count',0)} "
            f"({stats.get('gov_pct',0)}%) |",
            f"| Articles with governance claim unsupported by methods | "
            f"{stats.get('gov_gap_count',0)} ({stats.get('gov_gap_pct',0)}%) |",
            f"",
            f"### Oxford Evidence Level Distribution",
            f"",
            oxford_table(stats.get("oxford_counts", {})),
            f"",
            f"---",
            f"",
        ]

    # ── Per-cluster synthesis ─────────────────────────────────────────────────
    lines += [f"## Findings by Clinical Cluster", f""]

    for s in syntheses_sorted:
        cluster_name = s.get("cluster", "")
        cluster_label = cluster_name.replace("_", " ").title()
        cert   = s.get("grade_certainty", "")
        icon   = GRADE_ICON.get(cert, "⚪")
        rec    = s.get("recommendation_direction", "").upper()
        rec_str = s.get("recommendation_strength", "").title()
        n_art  = s.get("article_count", "?")
        defn   = cluster_defs.get(cluster_name, "")

        lines += [
            f"### {cluster_label}",
            f"",
        ]
        if defn:
            lines += [f"*{defn}*", f""]

        lines += [
            f"**GRADE Certainty:** {icon} {cert} &nbsp;|&nbsp; "
            f"**Recommendation:** {rec} ({rec_str}) &nbsp;|&nbsp; "
            f"**Articles:** {n_art}",
            f"",
            f"**Key findings:** {s.get('key_findings','')}",
            f"",
            f"**Clinician recommendation:** {s.get('clinician_recommendation','')}",
            f"",
            f"**Key caveat:** {s.get('key_caveat','')}",
            f"",
            f"**Spin:** {s.get('spin_summary','')}",
            f"",
        ]

        gov = s.get("governance_finding", "")
        gov_rec = s.get("governance_recommendation", "")
        if gov:
            lines += [
                f"**Governance finding:** {gov}",
                f"",
            ]
        if gov_rec:
            lines += [
                f"**Governance recommendation:** {gov_rec}",
                f"",
            ]

        future = s.get("future_research_priority", "")
        if future:
            lines += [f"**Future research priority:** {future}", f""]

        lines += ["---", ""]

    # ── Cross-cluster governance synthesis ────────────────────────────────────
    lines += [
        f"## Governance Synthesis",
        f"",
        f"*Governance focus for this review: {gov_focus}*",
        f"",
    ]

    gov_articles = [a for a in articles
                    if a.get("governance_recommendations", "").lower()
                    not in ("none stated", "", "not_stated")
                    and len(a.get("governance_recommendations", "")) > 20]
    gap_articles = [a for a in articles
                    if a.get("governance_claim_without_method", "").lower() == "yes"]

    lines += [
        f"Of {stats.get('n',0)} appraised articles:",
        f"- **{len(gov_articles)} ({stats.get('gov_pct',0)}%)** stated explicit "
        f"governance recommendations relevant to {gov_focus}.",
        f"- **{len(gap_articles)} ({stats.get('gov_gap_pct',0)}%)** made governance "
        f"or safety claims in abstracts or conclusions that were **not supported** "
        f"by methods section content (governance claim without method).",
        f"",
    ]

    if gap_articles:
        lines += [f"### Articles with Unsupported Governance Claims", f"",
                  f"| PMID | Title | Governance Gap |",
                  f"|------|-------|----------------|"]
        for a in gap_articles[:20]:  # cap at 20
            title = (a.get("title","") or "")[:70]
            gap   = (a.get("governance_gap_detail","") or "")[:100]
            lines.append(f"| {a.get('pmid','')} | {title} | {gap} |")
        lines += ["", "---", ""]

    # ── Spin analysis ─────────────────────────────────────────────────────────
    spin_articles = [a for a in articles if a.get("spin_detected","").lower() == "yes"]
    lines += [
        f"## Spin Detection Analysis",
        f"",
        f"**{len(spin_articles)} of {stats.get('n',0)} articles ({stats.get('spin_pct',0)}%)** "
        f"had conclusion language that overstated what the reported numbers support.",
        f"",
    ]

    if spin_articles:
        lines += [f"| PMID | Title | Oxford | Spin Detail |",
                  f"|------|-------|--------|-------------|"]
        for a in sorted(spin_articles, key=lambda x: x.get("oxford_roman","V"))[:20]:
            title = (a.get("title","") or "")[:60]
            detail = (a.get("spin_detail","") or "")[:100]
            lines.append(
                f"| {a.get('pmid','')} | {title} | "
                f"{a.get('oxford_roman','')} | {detail} |")
        lines += ["", "---", ""]

    # ── Methods note ──────────────────────────────────────────────────────────
    lines += [
        f"## Methods Note",
        f"",
        f"This evidence synthesis was produced by PT Research Pipeline v2, an automated "
        f"scoping review system using local large language models via Ollama.",
        f"",
        f"**Layer 0 ({models.get('layer0','')}):** All articles screened for relevance "
        f"using the configured relevance criterion. Oxford OCEBM level and GRADE domain "
        f"flags extracted from full text (first 8,000 characters).",
        f"",
        f"**Layer 2 ({models.get('layer2','')}):** Relevant articles subjected to "
        f"7-stage deep appraisal: Signal, Preparation, Evidence Grade, Context, "
        f"Dissonance (spin detection), Governance Audit, and Synthesis. Each stage "
        f"reads a targeted slice of the full text and passes structured outputs to "
        f"subsequent stages.",
        f"",
        f"**Layer 3 ({models.get('layer3','')}):** Dynamic cluster discovery from "
        f"extracted clinical domains, followed by GRADE certainty of evidence synthesis "
        f"per cluster.",
        f"",
        f"All outputs are AI-generated and should be reviewed by qualified clinicians "
        f"before informing clinical policy. Intra-AI reliability (phi4 vs qwen2.5, "
        f"Oxford level agreement) on the validation corpus: Kappa = 0.505 (Moderate).",
        f"",
        f"---",
        f"",
        f"## Appendix: Article Count by Cluster",
        f"",
        f"| Cluster | Articles | GRADE Certainty | Recommendation |",
        f"|---------|----------|-----------------|----------------|",
    ]

    for s in syntheses_sorted:
        lines.append(
            f"| {s.get('cluster','').replace('_',' ').title()} | "
            f"{s.get('article_count','?')} | "
            f"{GRADE_ICON.get(s.get('grade_certainty',''),'⚪')} {s.get('grade_certainty','')} | "
            f"{s.get('recommendation_direction','').upper()} "
            f"({s.get('recommendation_strength','').title()}) |"
        )

    lines += [
        f"",
        f"---",
        f"",
        f"*PT Research Pipeline v2 — automated evidence synthesis. "
        f"Generated {today}. All grades should be verified by a qualified clinician "
        f"before clinical application.*",
    ]

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)

    for key, val in cfg["paths"].items():
        if not os.path.isabs(val):
            cfg["paths"][key] = str(PIPELINE_ROOT / val)

    topic_name  = cfg.get("topic", {}).get("short_name", "research")
    today       = datetime.now().strftime("%Y%m%d")
    safe_topic  = topic_name.replace(" ", "_").lower()
    output_path = args.output or f"{safe_topic}_synthesis_report_{today}.md"

    log.info("=" * 60)
    log.info(f"PT Research Pipeline v2 — Report")
    log.info(f"Topic:  {topic_name}")
    log.info(f"Output: {output_path}")
    log.info("=" * 60)

    report = build_report(cfg)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)

    log.info(f"Report written: {output_path}")
    log.info(f"  {len(report.splitlines())} lines, "
             f"{round(len(report)/1000)}KB")


if __name__ == "__main__":
    main()
