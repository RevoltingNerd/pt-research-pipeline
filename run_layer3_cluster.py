"""
run_layer3_cluster.py — Layer 3 Step 1: Dynamic corpus clustering
PT Research Pipeline v2

Two-pass dynamic cluster discovery using the Layer 3 LLM:
  Pass 1: LLM reads all clinical domains and proposes natural clusters
          grounded in the actual corpus (no predetermined taxonomy)
  Pass 2: LLM assigns each article to a discovered cluster

Topic-neutral — cluster names and definitions are discovered from the
corpus, not hardcoded. Cluster count is set by pipeline.layer3_target_clusters
in config.yaml ("auto" or an integer).

Saves: layer3_clusters.json, layer3_clusters.csv
"""

import json, os, sys, yaml, logging, requests
from pathlib import Path
from datetime import datetime

PIPELINE_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PIPELINE_ROOT))
os.chdir(PIPELINE_ROOT)

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout),
              logging.FileHandler(
                  f"logs/layer3_cluster_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")])
log = logging.getLogger(__name__)


def call_ollama(prompt: str, cfg: dict) -> dict:
    try:
        resp = requests.post(
            f"{cfg['model']['base_url']}/api/generate",
            json={
                "model":  cfg["model"]["layer3"],
                "prompt": prompt,
                "format": "json",
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 3000, "num_ctx": 8192},
            },
            timeout=300,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "").strip()
        return json.loads(raw.lstrip("```json").lstrip("```").rstrip("```").strip())
    except Exception as e:
        log.error(f"Ollama call failed: {e}")
        return {}


def main():
    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)

    research_question = cfg.get("research_question", "").strip()
    target_clusters   = cfg.get("pipeline", {}).get("layer3_target_clusters", "auto")
    min_cluster_size  = cfg.get("pipeline", {}).get("layer3_min_cluster_size", 1)
    max_clusters      = cfg.get("pipeline", {}).get("layer3_max_clusters", 20)

    # Describe target for prompt
    if str(target_clusters).lower() == "auto":
        cluster_target_str = f"between 4 and {max_clusters} clusters (let the corpus decide)"
    else:
        cluster_target_str = str(target_clusters)

    # Load Layer 2 articles
    deep_dir = Path("summaries/deep")
    jsons = list(deep_dir.glob("*_layer2.json"))
    if not jsons:
        log.error("No Layer 2 JSON files found in summaries/deep/ — run Layer 2 first")
        sys.exit(1)
    log.info(f"Layer 2 articles to cluster: {len(jsons)}")

    # Collect article metadata
    articles = {}
    for f in jsons:
        d = json.loads(f.read_text())
        pmid   = d.get("pmid", "")
        domain = d.get("clinical_domain", "").strip()
        articles[pmid] = {
            "domain":              domain,
            "title":               d.get("title", ""),
            "oxford_roman":        d.get("oxford_roman", ""),
            "spin_detected":       d.get("spin_detected", ""),
            "governance_stated":   "yes" if (
                d.get("governance_recommendations", "none stated").lower() != "none stated"
                and len(d.get("governance_recommendations", "")) > 20
            ) else "no",
            "governance_claim_without_method": d.get("governance_claim_without_method", ""),
            "grade_risk_of_bias":   d.get("grade_risk_of_bias", ""),
            "grade_indirectness":   d.get("grade_indirectness", ""),
            "grade_imprecision":    d.get("grade_imprecision", ""),
            "key_takeaway":         d.get("key_takeaway", ""),
            "evidence_statement":   d.get("evidence_statement", ""),
            "governance_synthesis": d.get("governance_synthesis", ""),
            "implementation_result": d.get("implementation_result", ""),
        }

    # Build domain list for prompt (PMID -> domain string)
    domain_list = json.dumps(
        {pmid: info["domain"] for pmid, info in articles.items()}, indent=2)

    # Load and fill clustering prompt
    template = Path("prompts/layer3_clustering.txt").read_text()
    prompt = (template
        .replace("{research_question}", research_question)
        .replace("{domain_list}",       domain_list)
        .replace("{target_clusters}",   cluster_target_str)
        .replace("{min_cluster_size}",  str(min_cluster_size)))

    log.info(f"Running dynamic clustering ({len(articles)} articles)...")
    result = call_ollama(prompt, cfg)

    if not result:
        log.error("Clustering failed — no result returned from LLM")
        sys.exit(1)

    clusters_discovered = result.get("clusters_discovered", [])
    cluster_definitions = result.get("cluster_definitions", {})
    assignments         = result.get("assignments", {})

    if not clusters_discovered or not assignments:
        log.error(f"Clustering returned incomplete structure: {list(result.keys())}")
        sys.exit(1)

    log.info(f"Clusters discovered: {len(clusters_discovered)}")
    for c in clusters_discovered:
        defn = cluster_definitions.get(c, "")
        log.info(f"  {c}: {defn[:80]}")

    # Apply assignments, fall back to "general" for any unassigned
    fallback = "general_cross_cutting"
    if fallback not in clusters_discovered:
        clusters_discovered.append(fallback)

    results = []
    cluster_counts = {c: 0 for c in clusters_discovered}

    for pmid, info in articles.items():
        cluster = assignments.get(pmid, fallback)
        if cluster not in clusters_discovered:
            log.warning(f"PMID {pmid}: unknown cluster '{cluster}' — assigning to {fallback}")
            cluster = fallback
        cluster_counts[cluster] = cluster_counts.get(cluster, 0) + 1
        results.append({"pmid": pmid, "cluster": cluster, **info})

    # Save outputs
    Path("layer3_clusters.json").write_text(json.dumps(results, indent=2))
    Path("layer3_cluster_definitions.json").write_text(
        json.dumps({"clusters": clusters_discovered,
                    "definitions": cluster_definitions}, indent=2))

    import pandas as pd
    pd.DataFrame(results).to_csv("layer3_clusters.csv", index=False)

    log.info(f"\nClustering complete: {len(results)} articles across {len(clusters_discovered)} clusters")
    log.info("Cluster distribution:")
    for cluster, count in sorted(cluster_counts.items(), key=lambda x: -x[1]):
        if count > 0:
            log.info(f"  {cluster}: {count} articles")

    unassigned = sum(1 for r in results if r["cluster"] == fallback
                     and r["domain"] != "")
    if unassigned:
        log.warning(f"{unassigned} articles fell back to '{fallback}'")


if __name__ == "__main__":
    main()
