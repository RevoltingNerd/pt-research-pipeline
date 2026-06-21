"""
run_new_topic.py — PT Research Pipeline v2 — New Topic Setup

Updates config.yaml with new topic fields and esearch_params in one command,
clears the checkpoint, and optionally launches the pipeline immediately.

Usage:
    python3 run_new_topic.py                     # interactive prompts
    python3 run_new_topic.py --from-config new.yaml  # merge from a topic yaml
    python3 run_new_topic.py --run               # update config and start pipeline

A topic YAML has this structure (all fields optional — only provided fields updated):

  research_question: "..."
  topic:
    short_name: "dry needling"
    relevance_criterion: "The article concerns..."
    intervention_noun: "dry needling intervention"
    governance_focus: "Scope of practice..."
  feeds:
    - name: feed_a
      url: "https://pubmed.ncbi.nlm.nih.gov/rss/search/..."
      description: "Systematic reviews..."
      esearch_params:
        term: "(dry needling[Title/Abstract]) AND..."
        retmax: "100"
    - name: feed_b
      ...
    - name: feed_c
      ...
  clinical_impact:
    enabled: true
    taxonomy_file: "condition_taxonomy_lbp.yaml"
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import yaml
from pathlib import Path

PIPELINE_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PIPELINE_ROOT))
os.chdir(PIPELINE_ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger(__name__)

CHECKPOINT_FILE = Path(".pipeline_checkpoint.json")


def merge_topic_config(cfg: dict, topic_yaml: dict) -> dict:
    """Merge topic_yaml fields into cfg. Only updates provided fields."""
    if "research_question" in topic_yaml:
        cfg["research_question"] = topic_yaml["research_question"]

    if "topic" in topic_yaml:
        if "topic" not in cfg:
            cfg["topic"] = {}
        cfg["topic"].update(topic_yaml["topic"])

    if "feeds" in topic_yaml:
        # Match by name, preserve any existing fields not in topic_yaml
        existing = {f["name"]: f for f in cfg.get("feeds", [])}
        new_feeds = []
        for f in topic_yaml["feeds"]:
            name = f.get("name")
            merged = dict(existing.get(name, {}))
            merged.update(f)
            new_feeds.append(merged)
        # Preserve any feeds not in topic_yaml
        for name, f in existing.items():
            if not any(nf.get("name") == name for nf in new_feeds):
                new_feeds.append(f)
        cfg["feeds"] = new_feeds

    if "clinical_impact" in topic_yaml:
        if "clinical_impact" not in cfg:
            cfg["clinical_impact"] = {}
        cfg["clinical_impact"].update(topic_yaml["clinical_impact"])

    return cfg


def interactive_update(cfg: dict) -> dict:
    """Prompt user for the minimum required fields to switch topics."""
    print("\n── PT Research Pipeline v2 — New Topic Setup ──\n")
    print("Press Enter to keep the current value. Paste new value to update.\n")

    def prompt(label, current):
        display = (current[:80] + "...") if len(str(current)) > 80 else current
        val = input(f"{label}\n  Current: {display!r}\n  New: ").strip()
        return val if val else current

    cfg["research_question"] = prompt(
        "Research Question", cfg.get("research_question", ""))

    if "topic" not in cfg:
        cfg["topic"] = {}

    cfg["topic"]["short_name"] = prompt(
        "Topic Short Name (used in filenames)",
        cfg["topic"].get("short_name", ""))

    cfg["topic"]["relevance_criterion"] = prompt(
        "Relevance Criterion (screening gate for Layer 0)",
        cfg["topic"].get("relevance_criterion", ""))

    cfg["topic"]["intervention_noun"] = prompt(
        "Intervention Noun",
        cfg["topic"].get("intervention_noun", ""))

    cfg["topic"]["governance_focus"] = prompt(
        "Governance Focus",
        cfg["topic"].get("governance_focus", ""))

    print("\n── Feed Configuration ──\n")
    for i, label in enumerate(["A (high evidence)", "B (trials)", "C (governance)"]):
        fname = f"feed_{chr(97+i)}"
        existing = next((f for f in cfg.get("feeds", []) if f.get("name") == fname), {})

        url = input(f"Feed {label} RSS URL\n  Current: {existing.get('url','')!r}\n  New: ").strip()
        desc = input(f"Feed {label} Description\n  Current: {existing.get('description','')!r}\n  New: ").strip()
        term = input(f"Feed {label} E-utilities search term (for fallback)\n  Current: {existing.get('esearch_params',{}).get('term','')[:60]!r}\n  New: ").strip()

        feeds = cfg.get("feeds", [])
        match = next((f for f in feeds if f.get("name") == fname), None)
        if match is None:
            match = {"name": fname}
            feeds.append(match)
        if url:
            match["url"] = url
        if desc:
            match["description"] = desc
        if term:
            if "esearch_params" not in match:
                match["esearch_params"] = {}
            match["esearch_params"]["term"] = term
            match["esearch_params"]["retmax"] = "100"
        cfg["feeds"] = feeds

    return cfg


def main():
    parser = argparse.ArgumentParser(
        description="Switch to a new topic and optionally start the pipeline")
    parser.add_argument("--from-config", default=None,
                        help="Path to a topic YAML file to merge into config.yaml")
    parser.add_argument("--run", action="store_true",
                        help="Launch run_all.py after updating config")
    parser.add_argument("--no-archive-check", action="store_true",
                        help="Skip check for leftover run artifacts")
    args = parser.parse_args()

    if not Path("config.yaml").exists():
        log.error("config.yaml not found. Copy config.yaml.example first.")
        sys.exit(1)

    cfg = yaml.safe_load(Path("config.yaml").read_text())

    # Warn if leftover artifacts exist
    if not args.no_archive_check:
        artifacts = [Path("ledger.csv"), Path("layer0_ledger.csv"),
                     Path("clinical_impact_ledger.csv")]
        found = [str(p) for p in artifacts if p.exists()]
        if found:
            log.warning(f"Leftover run artifacts found: {found}")
            log.warning("Run 'python3 run_archive.py' first to archive the previous run.")
            ans = input("Continue anyway? [y/N] ").strip().lower()
            if ans != "y":
                sys.exit(0)

    # Merge from topic YAML or interactive prompts
    if args.from_config:
        topic_path = Path(args.from_config)
        if not topic_path.exists():
            log.error(f"Topic config not found: {args.from_config}")
            sys.exit(1)
        topic_yaml = yaml.safe_load(topic_path.read_text())
        cfg = merge_topic_config(cfg, topic_yaml)
        log.info(f"Config merged from {args.from_config}")
    else:
        cfg = interactive_update(cfg)

    # Clear checkpoint
    if CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()
        log.info("Checkpoint cleared")

    # Write updated config
    Path("config.yaml").write_text(yaml.dump(cfg, allow_unicode=True,
                                              default_flow_style=False))
    log.info(f"config.yaml updated — topic: {cfg.get('topic',{}).get('short_name','')}")

    # Verify feeds
    for f in cfg.get("feeds", []):
        has_esearch = bool(f.get("esearch_params", {}).get("term"))
        log.info(f"  {f.get('name')}: url={'set' if f.get('url') else 'MISSING'} | "
                 f"esearch={'set' if has_esearch else 'MISSING (RSS fallback only)'}")

    if args.run:
        log.info("\nLaunching pipeline...")
        subprocess.run([sys.executable, "run_all.py"])


if __name__ == "__main__":
    main()
