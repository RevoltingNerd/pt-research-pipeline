"""
rerun_governance.py — v2.1 governance backfill
PT Research Pipeline v2

Re-runs ONLY Stage 6 (5-dimension governance/deployment-readiness audit) and
Stage 7 (synthesis) on articles that were already appraised under the old
binary governance schema (governance_recommendations /
governance_claim_without_method / governance_gap_detail).

Does NOT touch Stages 1-5 — those outputs (study design, methodology,
evidence grade, context, dissonance/spin) are reused as-is from the
existing *_layer2.json files. Only Stage 6 and Stage 7 are re-run, using
the NEW prompts (prompts/stages/stage6_governance_audit.txt and
stage7_synthesis.txt) and the model configured for Layer 2 (qwen2.5:14b
by default — same model these corpora were originally appraised with).

INPUT:  {target_dir}/summaries/deep/*_layer2.json   (existing appraisals)
        {target_dir}/cache/full_text/{pmid}.txt     (cached article text)

OUTPUT: same *_layer2.json files, updated in place (backup .bak written
        once per file on first run). Markdown (*_layer2.md) is regenerated
        using run_layer2.py's build_markdown().

TEST MODE (--test, default):
    Processes only the first --n articles (default 4), does NOT write any
    files, and prints old binary fields vs new 5-dimension fields side by
    side for manual comparison.

FULL MODE (--apply):
    Processes every *_layer2.json in the target directory, writes updates
    in place (with .bak backups), and regenerates markdown.

Usage:
    # Test on 4 cached myofascial pain articles, qwen2.5, print comparison
    python3 rerun_governance.py --dir archive/myofascial_pain_20260611 \\
        --topic myofascial_pain --test --n 4

    # After reviewing test output, backfill the full corpus
    python3 rerun_governance.py --dir archive/myofascial_pain_20260611 \\
        --topic myofascial_pain --apply

    # Dry needling scoping review corpus
    python3 rerun_governance.py --dir archive/scoping_review_20260611 \\
        --topic dry_needling --apply
"""

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path

PIPELINE_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PIPELINE_ROOT))

from pipeline.appraise_staged import (
    _run_stage, _governance_profile, _resolve_text_slices,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)


# ── Topic presets ────────────────────────────────────────────────────────────
# These reconstruct the research_question / governance_focus used for the two
# already-completed corpora. config.yaml is gitignored and gets overwritten
# between topic runs, so it isn't preserved in the archive — these presets
# restore the framing context Stage 6/7 need. Override with --research-question
# / --governance-focus if these don't match what was actually used.
TOPIC_PRESETS = {
    "dry_needling": {
        "research_question": (
            "What does the peer-reviewed literature report regarding the "
            "clinical effectiveness, safety, and implementation of dry "
            "needling in physical therapy and rehabilitation — including "
            "trigger point identification, needling technique and dosage, "
            "functional outcomes, impact on rehabilitation course, adverse "
            "events and contraindications, and scope-of-practice and "
            "governance frameworks for its responsible application by "
            "physical therapists?"
        ),
        "governance_focus": (
            "scope of practice for physical therapists performing dry "
            "needling, training and competency requirements, adverse-event "
            "reporting and patient safety, contraindications and "
            "precautions, and regulatory or professional oversight "
            "frameworks"
        ),
    },
    "myofascial_pain": {
        "research_question": (
            "In adults with myofascial pain syndrome, does dry needling — "
            "with or without ultrasound guidance — produce clinically "
            "meaningful reductions in pain intensity and functional "
            "disability compared to sham needling, active comparators, or "
            "no treatment, and what patient or technique factors predict "
            "treatment response?"
        ),
        "governance_focus": (
            "training and competency requirements for dry needling in "
            "myofascial pain treatment, adverse-event reporting including "
            "post-needling soreness and serious complications, "
            "contraindications and precautions specific to myofascial pain "
            "populations, and scope-of-practice frameworks for physical "
            "therapists"
        ),
    },
}

OLD_GOVERNANCE_KEYS = [
    "governance_recommendations",
    "governance_claim_without_method",
    "governance_gap_detail",
]


def rerun_one(data: dict, full_text: str, model_cfg: dict,
               research_question: str, governance_focus: str,
               text_slices: dict, pmid: str) -> dict | None:
    """Re-run Stage 6 + Stage 7 on a single article. Returns updated dict."""
    stages = data.get("stage_outputs", {})
    s1, s2, s3, s4, s5 = (stages.get(f"s{i}", {}) for i in range(1, 6))

    # ── Stage 6: 5-dimension governance/deployment-readiness audit ──────────
    s6_context = {
        "bias_risk_structured":  s2.get("bias_risk_structured", ""),
        "spin_detected":         s5.get("spin_detected", ""),
        "spin_detail":           s5.get("spin_detail", ""),
        "dropout_rate":          s2.get("dropout_rate", ""),
        "intention_to_treat":    s2.get("intention_to_treat", ""),
        "governance_focus":      governance_focus,
    }
    s6 = _run_stage(6, full_text, s6_context, model_cfg, pmid, text_slices)
    if not s6:
        log.error(f"PMID {pmid}: Stage 6 rerun failed")
        return None

    gp = _governance_profile(s6)

    # ── Stage 7: synthesis, with governance_profile substituted ─────────────
    s7_context = {
        "title":   data.get("title", ""),
        "authors": data.get("authors", ""),
        "journal": data.get("journal", ""),
        "year":    data.get("publication_year", ""),
        "research_question": research_question,
        # Stage 1
        "study_design":      s1.get("study_design", ""),
        "sample_size":       s1.get("sample_size", ""),
        "intervention":      s1.get("intervention", ""),
        "comparator":        s1.get("comparator", ""),
        "primary_outcome":   s1.get("primary_outcome", ""),
        "primary_result":    s1.get("primary_result", ""),
        "signal_quality_note": s1.get("signal_quality_note", ""),
        # Stage 2
        "randomization":               s2.get("randomization", ""),
        "blinding":                    s2.get("blinding", ""),
        "allocation_concealment":      s2.get("allocation_concealment", ""),
        "dropout_rate":                s2.get("dropout_rate", ""),
        "intention_to_treat":          s2.get("intention_to_treat", ""),
        "primary_methodology_strength": s2.get("primary_methodology_strength", ""),
        "primary_methodology_weakness": s2.get("primary_methodology_weakness", ""),
        "bias_risk_structured":        s2.get("bias_risk_structured", ""),
        # Stage 3
        "oxford_level":        s3.get("oxford_level", ""),
        "oxford_roman":        s3.get("oxford_roman", ""),
        "oxford_rationale":    s3.get("oxford_rationale", ""),
        "downgraded":          s3.get("downgraded", ""),
        "downgrade_reason":    s3.get("downgrade_reason", ""),
        "clinical_necessity":  s3.get("clinical_necessity", ""),
        "necessity_rationale": s3.get("necessity_rationale", ""),
        # Stage 4
        "population":                  s4.get("population", ""),
        "clinical_setting":            s4.get("clinical_setting", ""),
        "geographic_context":          s4.get("geographic_context", ""),
        "generalizability":            s4.get("generalizability", ""),
        "generalizability_rationale":  s4.get("generalizability_rationale", ""),
        # Stage 5
        "conclusion_claim":        s5.get("conclusion_claim", ""),
        "actual_primary_result":   s5.get("actual_primary_result", ""),
        "ci_width":                s5.get("ci_width", ""),
        "statistical_significance": s5.get("statistical_significance", ""),
        "clinical_significance":   s5.get("clinical_significance", ""),
        "spin_detected":           s5.get("spin_detected", ""),
        "spin_detail":             s5.get("spin_detail", ""),
        "implementation_result":   s5.get("implementation_result", ""),
        # Stage 6 -> governance_profile
        "power_adequate":                    s6.get("power_adequate", ""),
        "internal_consistency":              s6.get("internal_consistency", ""),
        "limitations_reflected_in_conclusion": s6.get("limitations_reflected_in_conclusion", ""),
        "governance_profile":                gp["profile_str"],
        "patient_safety_concerns":           s6.get("patient_safety_concerns", ""),
        "ethical_considerations":            s6.get("ethical_considerations", ""),
        "implementation_barriers":           s6.get("implementation_barriers", ""),
    }
    s7 = _run_stage(7, full_text, s7_context, model_cfg, pmid, text_slices)
    if not s7:
        log.error(f"PMID {pmid}: Stage 7 rerun failed")
        return None

    # ── Update stage_outputs ─────────────────────────────────────────────────
    stages["s6"] = s6
    stages["s7"] = s7
    data["stage_outputs"] = stages

    # ── Remove old binary governance fields ──────────────────────────────────
    for key in OLD_GOVERNANCE_KEYS:
        data.pop(key, None)

    # ── Write new 5-dimension governance fields + refreshed Stage 7 fields ──
    data["governance_implemented_count"]  = gp["counts"]["implemented"]
    data["governance_aspirational_count"] = gp["counts"]["aspirational"]
    data["governance_not_addressed_count"] = gp["counts"]["not_addressed"]
    data["governance_dimensions"]         = gp["dimensions"]
    data["governance_overall_summary"]    = s6.get("governance_overall_summary", "")
    data["patient_safety_concerns"]       = s6.get("patient_safety_concerns", "")
    data["ethical_considerations"]        = s6.get("ethical_considerations", "")
    data["implementation_barriers"]       = s6.get("implementation_barriers", "")
    data["future_research_stated"]        = s6.get("future_research_stated", "")
    data["internal_consistency"]          = s6.get("internal_consistency", "")
    data["limitations_stated"]            = s6.get("limitations_stated", "")
    data["limitations_content"]           = s6.get("limitations_content", "")

    data["grade_risk_of_bias"]   = s7.get("grade_risk_of_bias", "")
    data["grade_indirectness"]   = s7.get("grade_indirectness", "")
    data["grade_imprecision"]    = s7.get("grade_imprecision", "")
    data["key_takeaway"]         = s7.get("key_takeaway", "")
    data["evidence_statement"]   = s7.get("evidence_statement", "")
    data["governance_synthesis"] = s7.get("governance_synthesis", "")
    data["research_relevance"]   = s7.get("research_relevance", "")
    data["appraisal_confidence"] = s7.get("appraisal_confidence", "")
    data["appraisal_confidence_rationale"] = s7.get("appraisal_confidence_rationale", "")

    return data


def print_comparison(pmid: str, old: dict, new: dict):
    print("=" * 78)
    print(f"PMID {pmid}: {old.get('title','')[:70]}")
    print("=" * 78)

    print("\n--- OLD (binary governance) ---")
    for k in OLD_GOVERNANCE_KEYS:
        v = old.get(k, "<absent>")
        v = (v[:200] + "…") if isinstance(v, str) and len(v) > 200 else v
        print(f"  {k}: {v}")

    print("\n--- NEW (5-dimension taxonomy) ---")
    print(f"  implemented={new['governance_implemented_count']} "
          f"aspirational={new['governance_aspirational_count']} "
          f"not_addressed={new['governance_not_addressed_count']}")
    for dim, entry in new["governance_dimensions"].items():
        detail = entry.get("detail", "none")
        detail = (detail[:120] + "…") if len(detail) > 120 else detail
        print(f"  {dim:28s} {entry.get('status',''):14s} {detail}")
    print(f"\n  governance_overall_summary:")
    print(f"    {new['governance_overall_summary']}")

    print("\n--- Stage 7 spot-check ---")
    print(f"  key_takeaway (old): {(old.get('key_takeaway','') or '')[:150]}")
    print(f"  key_takeaway (new): {(new.get('key_takeaway','') or '')[:150]}")
    print(f"  appraisal_confidence: {old.get('appraisal_confidence','?')} -> {new.get('appraisal_confidence','?')}")
    print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True,
                         help="Archive directory containing summaries/deep/ and cache/full_text/")
    parser.add_argument("--topic", choices=list(TOPIC_PRESETS.keys()), default=None,
                         help="Topic preset for research_question/governance_focus")
    parser.add_argument("--research-question", default=None,
                         help="Override research_question (required if --topic not given)")
    parser.add_argument("--governance-focus", default=None,
                         help="Override governance_focus (required if --topic not given)")
    parser.add_argument("--model", default="qwen2.5:14b",
                         help="Layer 2 model (default: qwen2.5:14b — same as original runs)")
    parser.add_argument("--base-url", default="http://localhost:11434")
    parser.add_argument("--test", action="store_true", default=True,
                         help="Test mode: process first --n articles, print comparison, write nothing (default)")
    parser.add_argument("--apply", action="store_true",
                         help="Full mode: process every article, write updates in place")
    parser.add_argument("--n", type=int, default=4,
                         help="Number of articles to process in test mode (default 4)")
    args = parser.parse_args()

    target = Path(args.dir).resolve()
    deep_dir = target / "summaries" / "deep"
    cache_dir = target / "cache" / "full_text"

    if not deep_dir.exists():
        log.error(f"{deep_dir} not found")
        sys.exit(1)
    if not cache_dir.exists():
        log.error(f"{cache_dir} not found")
        sys.exit(1)

    if args.topic:
        preset = TOPIC_PRESETS[args.topic]
        research_question = args.research_question or preset["research_question"]
        governance_focus   = args.governance_focus or preset["governance_focus"]
    else:
        if not args.research_question or not args.governance_focus:
            log.error("Either --topic or both --research-question and --governance-focus are required")
            sys.exit(1)
        research_question = args.research_question
        governance_focus  = args.governance_focus

    model_cfg = {"layer2": args.model, "base_url": args.base_url}
    text_slices = _resolve_text_slices(None)  # qwen2.5 8K-staged defaults

    jsons = sorted(deep_dir.glob("*_layer2.json"))
    apply_mode = args.apply
    if apply_mode:
        targets = jsons
        log.info(f"FULL MODE — processing {len(targets)} articles, writing updates in place")
    else:
        targets = jsons[:args.n]
        log.info(f"TEST MODE — processing first {len(targets)} of {len(jsons)} articles, no files written")

    log.info(f"Target dir: {target}")
    log.info(f"Model: {args.model} @ {args.base_url}")
    log.info(f"Research question: {research_question[:100]}…")
    log.info(f"Governance focus: {governance_focus[:100]}…")
    log.info("")

    completed = failed = 0
    for f in targets:
        old = json.loads(f.read_text())
        pmid = str(old.get("pmid", f.stem.replace("_layer2", "")))

        cache_file = cache_dir / f"{pmid}.txt"
        if not cache_file.exists():
            log.warning(f"PMID {pmid}: no cached full text at {cache_file} — skipping")
            failed += 1
            continue
        full_text = cache_file.read_text(errors="ignore")

        new = rerun_one(
            dict(old), full_text, model_cfg,
            research_question, governance_focus, text_slices, pmid,
        )
        if not new:
            failed += 1
            continue

        if not apply_mode:
            print_comparison(pmid, old, new)
        else:
            backup = f.with_suffix(".json.bak")
            if not backup.exists():
                shutil.copy(f, backup)
            f.write_text(json.dumps(new, indent=2))

            # Regenerate markdown
            try:
                from run_layer2 import build_markdown
                md_path = f.with_suffix("").with_suffix(".md")  # *_layer2.md
                md_path = deep_dir / f"{pmid}_layer2.md"
                article = {"pmid": pmid, "doi": new.get("doi", "Not available")}
                md_path.write_text(build_markdown(article, new))
            except Exception as e:
                log.warning(f"PMID {pmid}: markdown regeneration failed: {e}")

            gp_counts = (new["governance_implemented_count"],
                         new["governance_aspirational_count"],
                         new["governance_not_addressed_count"])
            log.info(f"PMID {pmid}: ✓ impl={gp_counts[0]} aspir={gp_counts[1]} silent={gp_counts[2]}")

        completed += 1

    log.info("")
    log.info(f"Done: {completed} completed | {failed} failed")
    if not apply_mode:
        log.info("Test mode — no files written. Review output above, then re-run with --apply.")


if __name__ == "__main__":
    main()
