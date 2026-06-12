"""
appraise_staged.py — Layer 2: 7-stage deep appraisal
PT Research Pipeline v2

Revised stage framework:
  1. Signal             — raw signal, N, intervention, primary outcome
  2. Preparation        — methodology audit, randomization, blinding, bias
  3. Evidence Grades    — Oxford level with quality adjustment, clinical justification
  4. Context            — external validity, population, setting, generalizability
  5. Dissonance         — narrative vs numbers, spin detection, implementation result
  6. Governance Audit   — statistical honesty, governance honesty audit
  7. Synthesis          — unvarnished net synthesis, GRADE inputs, key takeaway

Model: qwen2.5:14b (configured via config.yaml)
"""

from __future__ import annotations
import json
import logging
import time
import requests
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

STAGES_DIR = Path(__file__).parent.parent / "prompts" / "stages"

# Text slices per stage — (start_char, end_char) or None for context-only
STAGE_TEXT_SLICES = {
    1: (0, 4000),
    2: (0, 4000),
    3: None,        # Reasons from prior stage outputs only
    4: (2000, 6000),
    5: (2000, 6000),
    6: (4000, 8000),
    7: None,        # Synthesises prior stage outputs only
}

STAGE_NAMES = {
    1: "signal",
    2: "preparation",
    3: "evidence_grade",
    4: "context",
    5: "dissonance",
    6: "governance_audit",
    7: "synthesis",
}


def run_staged_appraisal(article: dict, model_cfg: dict, topic_cfg: dict = None) -> Optional[dict]:
    """
    Run all 7 stages for a single article.
    Returns complete appraisal dict or None on failure.
    """
    pmid      = article.get("pmid", "")
    full_text = article.get("full_text_content", "").strip()
    title     = article.get("title", "")
    authors   = article.get("authors", "")
    journal   = article.get("journal", "")
    year      = article.get("publication_year", "")

    topic_cfg         = topic_cfg or {}
    research_question = topic_cfg.get("research_question", "")
    intervention_noun = topic_cfg.get("intervention_noun", "the intervention under study")
    governance_focus  = topic_cfg.get("governance_focus", "governance and responsible practice")

    if not full_text:
        log.error(f"PMID {pmid}: no full text for staged appraisal")
        return None

    log.info(f"PMID {pmid}: starting 7-stage appraisal")
    stages = {}

    # ── Stage 1: Signal ────────────────────────────────────────────────────
    s1 = _run_stage(1, full_text, {"intervention_noun": intervention_noun}, model_cfg, pmid)
    if not s1:
        log.error(f"PMID {pmid}: Stage 1 failed")
        return None
    stages["s1"] = s1
    log.info(f"PMID {pmid}: Stage 1 ✓ — {s1.get('study_design','')} | N={s1.get('sample_size','')} | signal={s1.get('signal_present','')}")

    # ── Stage 2: Preparation ──────────────────────────────────────────────────
    s2 = _run_stage(2, full_text, {
        "study_design":   s1.get("study_design", ""),
        "intervention":   s1.get("intervention", ""),
        "sample_size":    s1.get("sample_size", ""),
        "primary_outcome": s1.get("primary_outcome", ""),
    }, model_cfg, pmid)
    if not s2:
        log.error(f"PMID {pmid}: Stage 2 failed")
        return None
    stages["s2"] = s2
    log.info(f"PMID {pmid}: Stage 2 ✓ — bias={s2.get('bias_risk_structured','')} | blinding={s2.get('blinding','')}")

    # ── Stage 3: Evidence Grade ────────────────────────────────────────────────────
    s3 = _run_stage(3, full_text, {
        "study_design":                s1.get("study_design", ""),
        "intervention":                s1.get("intervention", ""),
        "clinical_domain":             s1.get("clinical_domain", ""),
        "bias_risk_structured":        s2.get("bias_risk_structured", ""),
        "primary_methodology_strength": s2.get("primary_methodology_strength", ""),
        "primary_methodology_weakness": s2.get("primary_methodology_weakness", ""),
    }, model_cfg, pmid)
    if not s3:
        log.error(f"PMID {pmid}: Stage 3 failed")
        return None
    stages["s3"] = s3
    log.info(f"PMID {pmid}: Stage 3 ✓ — Oxford {s3.get('oxford_level','')} ({s3.get('oxford_roman','')}) | necessity={s3.get('clinical_necessity','')}")

    # ── Stage 4: Context ──────────────────────────────────────────────────────
    s4 = _run_stage(4, full_text, {
        "clinical_domain": s1.get("clinical_domain", ""),
        "intervention":    s1.get("intervention", ""),
        "sample_size":     s1.get("sample_size", ""),
        "oxford_level":    s3.get("oxford_level", ""),
    }, model_cfg, pmid)
    if not s4:
        log.error(f"PMID {pmid}: Stage 4 failed")
        return None
    stages["s4"] = s4
    log.info(f"PMID {pmid}: Stage 4 ✓ — generalizability={s4.get('generalizability','')} | setting={s4.get('clinical_setting','')}")

    # ── Stage 5: Dissonance ───────────────────────────────────────────────────
    s5 = _run_stage(5, full_text, {
        "intervention":    s1.get("intervention", ""),
        "primary_outcome": s1.get("primary_outcome", ""),
        "primary_result":  s1.get("primary_result", ""),
        "sample_size":     s1.get("sample_size", ""),
        "dropout_rate":    s2.get("dropout_rate", ""),
        "blinding":        s2.get("blinding", ""),
    }, model_cfg, pmid)
    if not s5:
        log.error(f"PMID {pmid}: Stage 5 failed")
        return None
    stages["s5"] = s5
    log.info(f"PMID {pmid}: Stage 5 ✓ — spin={s5.get('spin_detected','')} | implementation={s5.get('implementation_result','')}")

    # ── Stage 6: Governance Audit ────────────────────────────────────────────────
    s6 = _run_stage(6, full_text, {
        "bias_risk_structured":        s2.get("bias_risk_structured", ""),
        "spin_detected":               s5.get("spin_detected", ""),
        "spin_detail":                 s5.get("spin_detail", ""),
        "dropout_rate":                s2.get("dropout_rate", ""),
        "intention_to_treat":          s2.get("intention_to_treat", ""),
        "governance_focus":            governance_focus,
    }, model_cfg, pmid)
    if not s6:
        log.error(f"PMID {pmid}: Stage 6 failed")
        return None
    stages["s6"] = s6
    gov = s6.get("governance_recommendations", "none stated")
    gov_claim = s6.get("governance_claim_without_method", "no")
    log.info(f"PMID {pmid}: Stage 6 ✓ — governance={'stated' if gov.lower() != 'none stated' else 'none stated'} | gov_claim_without_method={gov_claim}")

    # ── Stage 7: Synthesis ─────────────────────────────────────────────────────
    s7 = _run_stage(7, full_text, {
        "title":   title, "authors": authors, "journal": journal, "year": year,
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
        "clinician_role":          s5.get("clinician_role", ""),
        # Stage 6
        "power_adequate":                    s6.get("power_adequate", ""),
        "internal_consistency":              s6.get("internal_consistency", ""),
        "limitations_reflected_in_conclusion": s6.get("limitations_reflected_in_conclusion", ""),
        "governance_recommendations":        s6.get("governance_recommendations", ""),
        "governance_claim_without_method":   s6.get("governance_claim_without_method", ""),
        "governance_gap_detail":             s6.get("governance_gap_detail", ""),
        "patient_safety_concerns":           s6.get("patient_safety_concerns", ""),
        "ethical_considerations":            s6.get("ethical_considerations", ""),
        "implementation_barriers":           s6.get("implementation_barriers", ""),
    }, model_cfg, pmid)
    if not s7:
        log.error(f"PMID {pmid}: Stage 7 failed")
        return None
    stages["s7"] = s7
    log.info(f"PMID {pmid}: Stage 7 ✓ — confidence={s7.get('appraisal_confidence','')}")

    # Compile final appraisal
    return {
        "pmid":    pmid,
        "title":   title,
        "authors": authors,
        "journal": journal,
        "publication_year": year,
        # Evidence grading
        "oxford_level":        s3.get("oxford_level", ""),
        "oxford_roman":        s3.get("oxford_roman", ""),
        "oxford_rationale":    s3.get("oxford_rationale", ""),
        "downgraded":          s3.get("downgraded", ""),
        "downgrade_reason":    s3.get("downgrade_reason", ""),
        "clinical_necessity":  s3.get("clinical_necessity", ""),
        # Signal
        "study_design":        s1.get("study_design", ""),
        "clinical_domain":     s1.get("clinical_domain", ""),
        "intervention":        s1.get("intervention", ""),
        "sample_size":         s1.get("sample_size", ""),
        "comparator":          s1.get("comparator", ""),
        "primary_outcome":     s1.get("primary_outcome", ""),
        "primary_result":      s1.get("primary_result", ""),
        "signal_present":      s1.get("signal_present", ""),
        # Methodology
        "randomization":               s2.get("randomization", ""),
        "blinding":                    s2.get("blinding", ""),
        "dropout_rate":                s2.get("dropout_rate", ""),
        "intention_to_treat":          s2.get("intention_to_treat", ""),
        "bias_risk_structured":        s2.get("bias_risk_structured", ""),
        "methodology_strength":        s2.get("primary_methodology_strength", ""),
        "methodology_weakness":        s2.get("primary_methodology_weakness", ""),
        # Context
        "population":                  s4.get("population", ""),
        "clinical_setting":            s4.get("clinical_setting", ""),
        "geographic_context":          s4.get("geographic_context", ""),
        "generalizability":            s4.get("generalizability", ""),
        # Dissonance
        "conclusion_claim":            s5.get("conclusion_claim", ""),
        "actual_primary_result":       s5.get("actual_primary_result", ""),
        "spin_detected":               s5.get("spin_detected", ""),
        "spin_detail":                 s5.get("spin_detail", ""),
        "statistical_significance":    s5.get("statistical_significance", ""),
        "clinical_significance":       s5.get("clinical_significance", ""),
        "implementation_result":       s5.get("implementation_result", ""),
        "clinician_role":              s5.get("clinician_role", ""),
        "effect_size_summary":         s5.get("effect_size_summary", ""),
        # Governance
        "governance_recommendations":        s6.get("governance_recommendations", ""),
        "governance_claim_without_method":   s6.get("governance_claim_without_method", ""),
        "governance_gap_detail":             s6.get("governance_gap_detail", ""),
        "patient_safety_concerns":           s6.get("patient_safety_concerns", ""),
        "ethical_considerations":            s6.get("ethical_considerations", ""),
        "implementation_barriers":           s6.get("implementation_barriers", ""),
        "future_research_stated":            s6.get("future_research_stated", ""),
        "internal_consistency":              s6.get("internal_consistency", ""),
        "limitations_stated":                s6.get("limitations_stated", ""),
        "limitations_content":               s6.get("limitations_content", ""),
        # GRADE inputs for Layer 3
        "grade_risk_of_bias":    s7.get("grade_risk_of_bias", ""),
        "grade_indirectness":    s7.get("grade_indirectness", ""),
        "grade_imprecision":     s7.get("grade_imprecision", ""),
        # Final synthesis
        "key_takeaway":              s7.get("key_takeaway", ""),
        "evidence_statement":        s7.get("evidence_statement", ""),
        "governance_synthesis":      s7.get("governance_synthesis", ""),
        "research_relevance":       s7.get("research_relevance", ""),
        "appraisal_confidence":      s7.get("appraisal_confidence", ""),
        "appraisal_confidence_rationale": s7.get("appraisal_confidence_rationale", ""),
        # Raw stage outputs
        "stage_outputs": stages,
    }


def _run_stage(stage_num: int, full_text: str, context: dict,
               model_cfg: dict, pmid: str) -> Optional[dict]:
    prompt_file = STAGES_DIR / f"stage{stage_num}_{STAGE_NAMES[stage_num]}.txt"
    try:
        template = prompt_file.read_text()
    except FileNotFoundError:
        log.error(f"Stage {stage_num} prompt not found: {prompt_file}")
        return None

    # Inject article text slice
    text_slice = STAGE_TEXT_SLICES.get(stage_num)
    if text_slice and full_text:
        start, end = text_slice
        chunk = full_text[start:end]
        if len(full_text) > end:
            chunk += "\n\n[Text continues beyond this excerpt]"
        context["full_text"] = chunk
    else:
        context["full_text"] = ""

    # Substitute all placeholders
    prompt = template
    for key, value in context.items():
        prompt = prompt.replace("{" + key + "}", str(value))

    raw = _call_ollama(prompt, model_cfg, pmid, stage_num)
    if not raw:
        return None
    return _parse_json(raw, pmid, stage_num)


def _call_ollama(prompt: str, model_cfg: dict, pmid: str, stage: int) -> Optional[str]:
    base_url   = model_cfg.get("base_url", "http://localhost:11434")
    model_name = model_cfg.get("layer2", "qwen2.5:14b")
    payload = {
        "model":  model_name,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 1500, "num_ctx": 8192},
    }
    try:
        resp = requests.post(f"{base_url}/api/generate", json=payload, timeout=300)
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except Exception as e:
        log.error(f"PMID {pmid} Stage {stage}: Ollama failed: {e}")
        return None


def _parse_json(raw: str, pmid: str, stage: int) -> Optional[dict]:
    cleaned = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        log.error(f"PMID {pmid} Stage {stage}: JSON parse error: {e}")
        log.debug(f"Raw (first 300): {raw[:300]}")
        return None
