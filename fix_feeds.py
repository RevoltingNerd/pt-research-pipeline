"""
fix_feeds.py — one-shot fix: set correct esearch_params for feed_a/b/c
to the AI-in-PT search terms, replacing any stale (equine) values.

Run once: python3 fix_feeds.py
Then re-check with the verification one-liner.
"""

import yaml
from pathlib import Path

ESEARCH = {
    "feed_a": {
        "term": (
            '(artificial intelligence[MeSH Terms] OR machine learning[MeSH Terms] OR '
            'large language model*[Title/Abstract] OR LLM[Title/Abstract] OR deep '
            'learning[Title/Abstract]) AND (physical therapy[MeSH Terms] OR '
            'rehabilitation[MeSH Terms] OR physiotherapy[Title/Abstract]) AND '
            '(systematic review[Publication Type] OR meta-analysis[Publication Type] '
            'OR review[Publication Type]) AND free full text[Filter] AND '
            '("2021/01/01"[Date - Publication] : "3000"[Date - Publication])'
        ),
        "retmax": "100",
    },
    "feed_b": {
        "term": (
            '(artificial intelligence[MeSH Terms] OR machine learning[MeSH Terms] OR '
            'large language model*[Title/Abstract] OR LLM[Title/Abstract] OR deep '
            'learning[Title/Abstract] OR ChatGPT[Title/Abstract]) AND (physical '
            'therapy[MeSH Terms] OR rehabilitation[MeSH Terms] OR '
            'physiotherapy[Title/Abstract]) AND (randomized controlled '
            'trial[Publication Type] OR clinical trial[Publication Type] OR cohort '
            'study[Title/Abstract] OR cross-sectional[Title/Abstract] OR case '
            'series[Title/Abstract] OR "controlled trial"[Title/Abstract]) AND free '
            'full text[Filter] AND ("2021/01/01"[Date - Publication] : '
            '"3000"[Date - Publication])'
        ),
        "retmax": "100",
    },
    "feed_c": {
        "term": (
            '(artificial intelligence[Title/Abstract] OR machine learning[Title/Abstract] '
            'OR large language model*[Title/Abstract]) AND (governance[Title/Abstract] '
            'OR ethics[MeSH Terms] OR "responsible deployment"[Title/Abstract] OR '
            'regulation[Title/Abstract] OR oversight[Title/Abstract] OR "scope of '
            'practice"[Title/Abstract] OR accountability[Title/Abstract] OR '
            'framework[Title/Abstract]) AND (health care[MeSH Terms] OR '
            'rehabilitation[Title/Abstract] OR physical therapy[Title/Abstract] OR '
            'clinical[Title/Abstract]) AND free full text[Filter] AND '
            '("2021/01/01"[Date - Publication] : "3000"[Date - Publication])'
        ),
        "retmax": "100",
    },
}

cfg_path = Path("config.yaml")
cfg = yaml.safe_load(cfg_path.read_text())

for f in cfg.get("feeds", []):
    name = f.get("name")
    if name in ESEARCH:
        old_term = f.get("esearch_params", {}).get("term", "")
        f["esearch_params"] = ESEARCH[name]
        print(f"{name}: esearch_params set "
              f"({'replaced stale term' if old_term else 'added'})")
    else:
        print(f"{name}: no matching entry in ESEARCH — left as-is")

cfg_path.write_text(yaml.dump(cfg, allow_unicode=True, default_flow_style=False))
print("\nconfig.yaml written.")
