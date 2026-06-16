"""
run_layer2.py — Layer 2: Deep appraisal on relevant articles
PT Research Pipeline v2

Runs 7-stage appraisal on all articles where Layer 0 relevance = yes.
Uses qwen2.5:14b via Ollama.
Saves deep markdown and JSON to summaries/deep/
"""

import json
import logging
import os
import sys
import yaml
import pandas as pd
from datetime import datetime
from pathlib import Path

PIPELINE_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PIPELINE_ROOT))

from pipeline.fetch import fetch_full_text
from pipeline.ingest import fetch_pubmed_metadata, fetch_abstract_and_mesh
from pipeline.appraise_staged import run_staged_appraisal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.FileHandler(f"logs/layer2_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger(__name__)


GOVERNANCE_DIMENSION_LABELS = [
    ("scope_of_practice",        "Scope of Practice"),
    ("output_validation",        "Output Validation"),
    ("guardrails_safety",        "Guardrails / Safety"),
    ("accountability_liability", "Accountability / Liability"),
    ("training_competency",      "Training / Competency"),
]

STATUS_ICONS = {
    "implemented":   "🟢 implemented",
    "aspirational":  "🟡 aspirational",
    "not_addressed": "⚪ not addressed",
}


def _governance_dimension_table(dimensions: dict) -> str:
    """Render the 5-dimension governance taxonomy as a markdown table body."""
    rows = []
    for key, label in GOVERNANCE_DIMENSION_LABELS:
        entry  = dimensions.get(key, {}) or {}
        status = entry.get("status", "not_addressed")
        detail = entry.get("detail", "none")
        icon   = STATUS_ICONS.get(status, status)
        rows.append(f"| {label} | {icon} | {detail} |")
    return "\n".join(rows)


def build_markdown(article: dict, appraisal: dict) -> str:
    pmid  = article.get("pmid", "")
    today = datetime.now().strftime("%Y-%m-%d")
    conf  = appraisal.get("appraisal_confidence", "")
    conf_flag = "\n> ⚠️ **Low appraisal confidence** — verify manually before citing.\n" if conf == "low" else ""
    spin_flag = "\n> 🔴 **Spin detected** — conclusion language overstates findings. See dissonance section.\n" if appraisal.get("spin_detected", "").lower() == "yes" else ""
    gov_silent = appraisal.get("governance_not_addressed_count", 0)
    gov_flag  = "\n> 🔴 **Governance largely unaddressed** — most governance/deployment-readiness dimensions are not raised. See governance audit section.\n" if isinstance(gov_silent, int) and gov_silent >= 4 else ""

    return f"""# {appraisal.get('title', 'Unknown')}

**PMID:** {pmid}
**Authors:** {appraisal.get('authors', '')}
**Journal:** {appraisal.get('journal', '')} ({appraisal.get('publication_year', '')})
**DOI:** {article.get('doi', 'Not available')}
**Layer 2 appraisal:** {today} · **Model:** {article.get('model_used', 'qwen2.5:14b')}
{conf_flag}{spin_flag}{gov_flag}
---

## Evidence grade

| Field | Value |
|-------|-------|
| Oxford OCEBM level | **{appraisal.get('oxford_roman', '?')} ({appraisal.get('oxford_level', '?')})** |
| Oxford rationale | {appraisal.get('oxford_rationale', '')} |
| Downgraded | {appraisal.get('downgraded', '')} — {appraisal.get('downgrade_reason', '')} |
| Clinical necessity | {appraisal.get('clinical_necessity', '')} |
| Appraisal confidence | {conf} |

---

## Key takeaway

> {appraisal.get('key_takeaway', 'Not available')}

---

## Evidence statement

{appraisal.get('evidence_statement', 'Not available')}

---

## Signal

| Field | Value |
|-------|-------|
| Study design | {appraisal.get('study_design', '')} |
| Sample size | {appraisal.get('sample_size', '')} |
| Intervention | {appraisal.get('intervention', '')} |
| Comparator | {appraisal.get('comparator', '')} |
| Primary outcome | {appraisal.get('primary_outcome', '')} |
| Primary result | {appraisal.get('primary_result', '')} |

---

## Methodology

| Field | Value |
|-------|-------|
| Randomization | {appraisal.get('randomization', '')} |
| Blinding | {appraisal.get('blinding', '')} |
| Dropout rate | {appraisal.get('dropout_rate', '')} |
| ITT analysis | {appraisal.get('intention_to_treat', '')} |
| Bias risk | {appraisal.get('bias_risk_structured', '')} |

**Strength:** {appraisal.get('methodology_strength', '')}

**Weakness:** {appraisal.get('methodology_weakness', '')}

---

## Context

**Population:** {appraisal.get('population', '')}

**Setting:** {appraisal.get('clinical_setting', '')} | **Geography:** {appraisal.get('geographic_context', '')}

**Generalizability:** {appraisal.get('generalizability', '')} — {appraisal.get('generalizability_rationale', '')}



---

## Dissonance audit

**Conclusion claim:** {appraisal.get('conclusion_claim', '')}

**Actual result:** {appraisal.get('actual_primary_result', '')}

**Spin detected:** {appraisal.get('spin_detected', '')}

{f"**Spin detail:** {appraisal.get('spin_detail', '')}" if appraisal.get('spin_detected','').lower() == 'yes' else ''}

**Statistical significance:** {appraisal.get('statistical_significance', '')}

**Clinical significance:** {appraisal.get('clinical_significance', '')}

**Effect size summary:** {appraisal.get('effect_size_summary', '')}

---

## Governance / deployment-readiness audit

**Statistical honesty** — power adequate: {appraisal.get('power_adequate', '')} | internal consistency: {appraisal.get('internal_consistency', '')} | limitations reflected in conclusion: {appraisal.get('limitations_reflected_in_conclusion', '')}

{f"**Limitations stated by authors:** {appraisal.get('limitations_content', '')}" if appraisal.get('limitations_stated','').lower() == 'yes' else '**Limitations stated by authors:** none stated'}

### Five-dimension governance taxonomy

| Dimension | Status | Detail |
|-----------|--------|--------|
{_governance_dimension_table(appraisal.get('governance_dimensions') or {})}

**Overall governance summary:** {appraisal.get('governance_overall_summary', '')}

**Patient safety concerns:** {appraisal.get('patient_safety_concerns', 'None stated')}

**Ethical considerations:** {appraisal.get('ethical_considerations', 'None stated')}

**Implementation barriers:** {appraisal.get('implementation_barriers', 'None stated')}

**Future research priorities stated by authors:** {appraisal.get('future_research_stated', 'None stated')}

---

## GRADE inputs for Layer 3

| Domain | Rating |
|--------|--------|
| Risk of bias | {appraisal.get('grade_risk_of_bias', '')} |
| Indirectness | {appraisal.get('grade_indirectness', '')} |
| Imprecision | {appraisal.get('grade_imprecision', '')} |

*Consistency and publication bias assessed at Layer 3 across article clusters.*

---

## Research relevance

{appraisal.get('research_relevance', 'Not assessed')}

---

## Appraisal notes

{appraisal.get('appraisal_confidence_rationale', 'None')}

---

*Generated by PT Research Pipeline Layer 2 — 7-stage appraisal via Ollama. All grades should be verified by a qualified clinician before clinical application.*
"""


def main():
    os.chdir(PIPELINE_ROOT)

    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)

    for key, val in cfg["paths"].items():
        if not os.path.isabs(val):
            cfg["paths"][key] = str(PIPELINE_ROOT / val)

    deep_dir = PIPELINE_ROOT / "summaries" / "deep"
    deep_dir.mkdir(parents=True, exist_ok=True)

    # Load Layer 0 ledger — filter to relevant only
    layer0_path = PIPELINE_ROOT / "layer0_ledger.csv"
    if not layer0_path.exists():
        log.error("layer0_ledger.csv not found — run Layer 0 first")
        sys.exit(1)

    l0 = pd.read_csv(layer0_path, dtype=str)
    relevant = l0[l0["relevant_to_primary_question"].str.lower() == "yes"]
    log.info(f"Layer 2 targets: {len(relevant)} relevant articles from Layer 0")

    completed = failed = skipped = 0

    for _, row in relevant.iterrows():
        pmid = str(row["pmid"]).strip()
        md_path   = deep_dir / f"{pmid}_layer2.md"
        json_path = deep_dir / f"{pmid}_layer2.json"

        if md_path.exists() and json_path.exists():
            log.info(f"PMID {pmid}: already done — skipping")
            skipped += 1
            continue

        log.info(f"\nPMID {pmid}: {str(row.get('title', ''))[:70]}")

        article = row.to_dict()
        article["pmid"] = pmid

        # Fetch metadata if needed
        if not article.get("title") or article.get("title") == "nan":
            meta = fetch_pubmed_metadata([pmid], cfg["pubmed_api"])
            if pmid in meta:
                article.update(meta[pmid])

        if not article.get("abstract"):
            abst = fetch_abstract_and_mesh(pmid, cfg["pubmed_api"])
            article.update(abst)

        # Fetch full text
        article = fetch_full_text(article, cfg["paths"], cfg["pubmed_api"])

        if not article.get("full_text_available"):
            log.warning(f"PMID {pmid}: no full text — skipping")
            failed += 1
            continue

        article["model_used"] = cfg["model"]["layer2"]

        # Run 7-stage appraisal
        topic_cfg = {
            "research_question": cfg.get("research_question", ""),
            "intervention_noun": cfg.get("topic", {}).get("intervention_noun", "the intervention under study"),
            "governance_focus":  cfg.get("topic", {}).get("governance_focus", "governance and responsible practice"),
            "text_slices":       cfg.get("pipeline", {}).get("layer2_text_slices"),
        }
        appraisal = run_staged_appraisal(article, cfg["model"], topic_cfg)

        if not appraisal:
            log.error(f"PMID {pmid}: appraisal failed")
            failed += 1
            continue

        # Save outputs
        md_path.write_text(build_markdown(article, appraisal))
        json_path.write_text(json.dumps(appraisal, indent=2))
        log.info(f"PMID {pmid}: ✓ saved — Oxford {appraisal.get('oxford_roman','?')} | spin={appraisal.get('spin_detected','?')} | "
                 f"gov impl={appraisal.get('governance_implemented_count','?')} "
                 f"aspir={appraisal.get('governance_aspirational_count','?')} "
                 f"silent={appraisal.get('governance_not_addressed_count','?')}")
        completed += 1

    log.info("=" * 60)
    log.info("Layer 2 complete")
    log.info(f"  Completed: {completed}")
    log.info(f"  Failed:    {failed}")
    log.info(f"  Skipped:   {skipped}")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
