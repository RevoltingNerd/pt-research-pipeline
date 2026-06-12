"""
run_layer0.py — Layer 0 fast metadata extraction
PT Research Pipeline v2

Uses phi4:14b for speed. Extracts Oxford level, GRADE domain flags,
relevance binary, clinical domain, and implementation result.
Saves structured JSON and markdown summary per article.
Saves aggregate to layer0_ledger.csv for validation and Kappa.

Usage:
    python3 run_layer0.py                  # test — first 10 articles
    python3 run_layer0.py --limit 4        # first 4 articles
    python3 run_layer0.py --all            # full corpus
    python3 run_layer0.py --pmid 12345 678 # specific PMIDs
"""

import json
import logging
import os
import sys
import yaml
import pandas as pd
import requests
import time
from datetime import datetime
from pathlib import Path

PIPELINE_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PIPELINE_ROOT))

from pipeline.fetch import fetch_full_text
from pipeline.ingest import fetch_pubmed_metadata, fetch_abstract_and_mesh

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            f"logs/layer0_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        )
    ]
)
log = logging.getLogger(__name__)

LAYER0_MODEL = None  # populated from config.yaml (model.layer0) in main()

# GRADE domain label maps for markdown display
BIAS_LABELS   = {'low': '🟢 Low', 'moderate': '🟡 Moderate',
                 'high': '🔴 High', 'unclear': '⚪ Unclear'}
DIR_LABELS    = {'direct': '🟢 Direct', 'partially_direct': '🟡 Partially direct',
                 'indirect': '🔴 Indirect', 'unclear': '⚪ Unclear'}
PREC_LABELS   = {'precise': '🟢 Precise', 'imprecise': '🟡 Imprecise',
                 'unclear': '⚪ Unclear'}
OXFORD_LABELS = {
    '1a': 'SR of RCTs', '1b': 'Individual RCT', '1c': 'All-or-none',
    '2a': 'SR of cohorts', '2b': 'Cohort / low-quality RCT', '2c': 'Outcomes research',
    '3a': 'SR of case-control', '3b': 'Case-control', '4': 'Case series', '5': 'Expert opinion / review'
}


def call_ollama(prompt: str, base_url: str) -> dict:
    payload = {
        "model":  LAYER0_MODEL,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 800, "num_ctx": 4096},
    }
    try:
        resp = requests.post(f"{base_url}/api/generate", json=payload, timeout=120)
        resp.raise_for_status()
        raw = resp.json().get("response", "").strip()
        cleaned = raw.lstrip("```json").lstrip("```").rstrip("```").strip()
        return json.loads(cleaned)
    except Exception as e:
        log.error(f"Ollama call failed: {e}")
        return {}


def build_markdown(article: dict, result: dict) -> str:
    """Build Layer 0 markdown summary from extraction result."""
    pmid    = article.get("pmid", "")
    title   = article.get("title", "Unknown title")
    authors = article.get("authors", "")
    journal = article.get("journal", "")
    year    = article.get("publication_year", "")
    doi     = article.get("doi", "Not available")
    feed    = article.get("feed_source", "")
    today   = datetime.now().strftime("%Y-%m-%d")

    oxford      = result.get("oxford_level", "?")
    oxford_desc = OXFORD_LABELS.get(oxford, "")
    ox_rationale = result.get("oxford_rationale", "")
    relevant    = result.get("relevant_to_primary_question", "?").upper()
    domain      = result.get("clinical_domain", "")
    intervention_type = result.get("intervention_type", "")
    relevance_note    = result.get("relevance_note", "")
    sample      = result.get("sample_size", "not reported")
    outcome     = result.get("primary_outcome", "not reported")
    impl        = result.get("implementation_result", "")

    bias      = result.get("grade_risk_of_bias", "unclear")
    bias_r    = result.get("grade_risk_rationale", "")
    direct    = result.get("grade_directness", "unclear")
    direct_r  = result.get("grade_directness_rationale", "")
    precision = result.get("grade_precision", "unclear")
    prec_r    = result.get("grade_precision_rationale", "")

    study_design = result.get("study_design", "")

    rel_flag = "✅ YES" if relevant == "YES" else "❌ NO"

    return f"""# {title}

**PMID:** {pmid}
**Authors:** {authors}
**Journal:** {journal} ({year})
**DOI:** {doi}
**Feed source:** {feed}
**Layer 0 extraction:** {today} · **Model:** {LAYER0_MODEL}

---

## Evidence snapshot

| Field | Value |
|-------|-------|
| Oxford OCEBM level | **{oxford}** — {oxford_desc} |
| Oxford rationale | {ox_rationale} |
| Relevant to primary question | {rel_flag} |
| Study design | {study_design} |
| Clinical domain | {domain} |
| Intervention type | {intervention_type} |
| Sample size | {sample} |
| Primary outcome | {outcome} |
| Implementation result | {impl} |
| Relevance note | {relevance_note} |

---

## GRADE domain flags

| Domain | Rating | Rationale |
|--------|--------|-----------|
| Risk of bias | {BIAS_LABELS.get(bias, bias)} | {bias_r} |
| Directness | {DIR_LABELS.get(direct, direct)} | {direct_r} |
| Precision | {PREC_LABELS.get(precision, precision)} | {prec_r} |

*Note: Consistency assessed at Layer 3 synthesis across article clusters. McDermott/GRADE certainty rating assigned at Layer 3 per clinical question, not per article.*

---

*Generated by PT Research Pipeline Layer 0 — {LAYER0_MODEL} via Ollama. Oxford level and GRADE flags are AI-generated and should be verified before clinical application.*
"""


def run_layer0_on_article(article: dict, cfg: dict) -> dict:
    pmid      = article["pmid"]
    full_text = article.get("full_text_content", "")[:8000]

    prompt_path = PIPELINE_ROOT / "prompts" / "layer0_extraction.txt"
    template    = prompt_path.read_text()

    # Inject topic framing from config
    relevance_criterion = cfg.get("topic", {}).get(
        "relevance_criterion", "The article concerns the intervention under study.")
    prompt = template.replace("{relevance_criterion}", relevance_criterion)
    prompt = prompt.replace("{full_text}", full_text)

    log.info(f"PMID {pmid}: running Layer 0 with {LAYER0_MODEL}")
    result = call_ollama(prompt, cfg["model"]["base_url"])

    if not result:
        log.error(f"PMID {pmid}: extraction failed")
        return {}

    result["pmid"]        = pmid
    result["title"]       = article.get("title", "")
    result["authors"]     = article.get("authors", "")
    result["journal"]     = article.get("journal", "")
    result["year"]        = article.get("publication_year", "")
    result["doi"]         = article.get("doi", "")
    result["feed_source"] = article.get("feed_source", "")
    result["model_used"]  = LAYER0_MODEL
    result["run_date"]    = datetime.now().strftime("%Y-%m-%d")

    log.info(
        f"PMID {pmid}: Oxford {result.get('oxford_level','?')} | "
        f"Relevant: {result.get('relevant_to_primary_question','?')} | "
        f"Bias: {result.get('grade_risk_of_bias','?')} | "
        f"Direct: {result.get('grade_directness','?')} | "
        f"Precision: {result.get('grade_precision','?')}"
    )
    return result


def main(limit=None, pmids=None, process_all=False):
    global LAYER0_MODEL
    os.chdir(PIPELINE_ROOT)

    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)

    LAYER0_MODEL = cfg["model"]["layer0"]

    for key, val in cfg["paths"].items():
        if not os.path.isabs(val):
            cfg["paths"][key] = str(PIPELINE_ROOT / val)

    layer0_dir = PIPELINE_ROOT / "summaries" / "layer0"
    layer0_dir.mkdir(parents=True, exist_ok=True)

    # Load targets
    if pmids:
        # Specific PMIDs passed — build minimal dataframe
        targets = pd.DataFrame([{"pmid": p, "feed_source": "manual",
                                  "appraisal_complete": True} for p in pmids])
    else:
        df = pd.read_csv("ledger.csv")
        targets = df[df["appraisal_complete"] == True]
        if not process_all and limit:
            targets = targets.head(limit)
        elif not process_all:
            targets = targets.head(10)  # default test

    log.info(f"Layer 0 targets: {len(targets)} articles")
    log.info(f"Model: {LAYER0_MODEL}")

    results    = []
    completed  = 0
    failed     = 0

    for _, row in targets.iterrows():
        pmid     = str(row["pmid"]).strip()
        json_out = layer0_dir / f"{pmid}_layer0.json"
        md_out   = layer0_dir / f"{pmid}_layer0.md"

        if json_out.exists() and md_out.exists():
            log.info(f"PMID {pmid}: already done — skipping")
            results.append(json.loads(json_out.read_text()))
            completed += 1
            continue

        article = row.to_dict() if not pmids else {"pmid": pmid, "feed_source": "manual"}
        article["pmid"] = pmid

        # Fetch metadata if needed
        if not article.get("title"):
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

        result = run_layer0_on_article(article, cfg)

        if result:
            # Save JSON
            json_out.write_text(json.dumps(result, indent=2))
            # Save markdown
            md_out.write_text(build_markdown(article, result))
            results.append(result)
            completed += 1
        else:
            failed += 1

    # Save layer0 ledger
    if results:
        ledger_df = pd.DataFrame(results)
        ledger_df.to_csv("layer0_ledger.csv", index=False)
        log.info(f"Layer 0 ledger saved: {len(ledger_df)} articles")

        relevant = ledger_df[ledger_df.get("relevant_to_primary_question", pd.Series()).str.lower() == "yes"] if "relevant_to_primary_question" in ledger_df.columns else pd.DataFrame()
        log.info(f"Relevant to PQ: {len(relevant)}/{len(ledger_df)}")

        if "oxford_level" in ledger_df.columns:
            log.info(f"Oxford distribution:\n{ledger_df['oxford_level'].value_counts().to_string()}")

        if "grade_risk_of_bias" in ledger_df.columns:
            log.info(f"Risk of bias:\n{ledger_df['grade_risk_of_bias'].value_counts().to_string()}")

    log.info(f"Complete: {completed} | Failed: {failed}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit",  type=int, default=10)
    parser.add_argument("--pmid",   nargs="+")
    parser.add_argument("--all",    action="store_true")
    args = parser.parse_args()

    main(
        limit=args.limit,
        pmids=args.pmid,
        process_all=args.all
    )
