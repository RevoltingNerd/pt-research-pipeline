"""
run_qwen_irr_full.py — Run qwen2.5:14b Layer 0 on all 103 relevant articles
for intra-AI Kappa comparison against phi4:14b outputs.
Skips the 30 already done in summaries/layer0_qwen_irr/
Saves to summaries/layer0_qwen_irr/
Then calculates full Kappa (n=103).
"""

import json, os, sys, yaml, logging, requests, numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

PIPELINE_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PIPELINE_ROOT))
os.chdir(PIPELINE_ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(f"logs/qwen_irr_full_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    ]
)
log = logging.getLogger(__name__)

COLLAPSE = {
    '1a':'I','1b':'I','1c':'I',
    '2a':'II','2b':'II','2c':'II',
    '3a':'III','3b':'III',
    '4':'IV','5':'V','other':'V',
}

def call_qwen(prompt):
    try:
        resp = requests.post('http://localhost:11434/api/generate',
            json={'model': 'qwen2.5:14b', 'prompt': prompt,
                  'format': 'json', 'stream': False,
                  'options': {'temperature': 0.1, 'num_predict': 800, 'num_ctx': 4096}},
            timeout=120)
        resp.raise_for_status()
        raw = resp.json().get('response','').strip()
        cleaned = raw.lstrip('```json').lstrip('```').rstrip('```').strip()
        return json.loads(cleaned)
    except Exception as e:
        log.error(f"qwen call failed: {e}")
        return {}

def calculate_kappa(labels_a, labels_b):
    n = len(labels_a)
    if n == 0: return 0, 0, 0
    agree = sum(a==b for a,b in zip(labels_a, labels_b))
    po = agree / n
    cats = sorted(set(labels_a + labels_b))
    pe = sum((labels_a.count(c)/n)*(labels_b.count(c)/n) for c in cats)
    kappa = (po - pe) / (1 - pe) if (1 - pe) != 0 else 0
    se = np.sqrt((po*(1-po)) / (n*(1-pe)**2)) if (1-pe) != 0 else 0
    return kappa, se, po

def main():
    with open('config.yaml') as f:
        cfg = yaml.safe_load(f)
    for key, val in cfg['paths'].items():
        if not os.path.isabs(val):
            cfg['paths'][key] = str(PIPELINE_ROOT / val)

    from pipeline.fetch import fetch_full_text
    from pipeline.ingest import fetch_pubmed_metadata, fetch_abstract_and_mesh

    # Load relevant articles from Layer 0 ledger
    l0 = pd.read_csv('layer0_ledger.csv', dtype=str)
    relevant = l0[l0['relevant_to_primary_question'].str.lower() == 'yes']
    log.info(f"Relevant articles: {len(relevant)}")

    phi4_dir = Path('summaries/layer0')
    qwen_dir = Path('summaries/layer0_qwen_irr')
    qwen_dir.mkdir(parents=True, exist_ok=True)

    prompt_template = Path('prompts/layer0_extraction.txt').read_text()

    completed = skipped = failed = 0

    for _, row in relevant.iterrows():
        pmid = str(row['pmid']).strip()
        out_path = qwen_dir / f'{pmid}_layer0_qwen.json'

        if out_path.exists():
            skipped += 1
            continue

        log.info(f"PMID {pmid}: running qwen2.5...")

        article = row.to_dict()
        article['pmid'] = pmid

        if not article.get('title') or article.get('title') == 'nan':
            meta = fetch_pubmed_metadata([pmid], cfg['pubmed_api'])
            if pmid in meta: article.update(meta[pmid])

        if not article.get('abstract'):
            abst = fetch_abstract_and_mesh(pmid, cfg['pubmed_api'])
            article.update(abst)

        article = fetch_full_text(article, cfg['paths'], cfg['pubmed_api'])

        if not article.get('full_text_available'):
            log.warning(f"PMID {pmid}: no full text")
            failed += 1
            continue

        full_text = article.get('full_text_content','')[:8000]
        prompt = prompt_template.replace('{full_text}', full_text)
        result = call_qwen(prompt)

        if result:
            result['pmid'] = pmid
            result['model_used'] = 'qwen2.5:14b'
            result['title'] = article.get('title','')
            out_path.write_text(json.dumps(result, indent=2))
            log.info(f"PMID {pmid}: Oxford {result.get('oxford_level','?')} | "
                     f"relevant={result.get('relevant_to_primary_question','?')}")
            completed += 1
        else:
            log.error(f"PMID {pmid}: extraction failed")
            failed += 1

    log.info(f"\nExtraction complete: {completed} new | {skipped} skipped | {failed} failed")

    # ── Calculate full Kappa ──────────────────────────────────────────────────
    log.info("\nCalculating intra-AI Kappa (phi4 vs qwen2.5) across all relevant articles...")

    phi4_levels, qwen_levels = [], []
    results = []

    for _, row in relevant.iterrows():
        pmid = str(row['pmid']).strip()
        phi4_f = phi4_dir / f'{pmid}_layer0.json'
        qwen_f = qwen_dir / f'{pmid}_layer0_qwen.json'

        if not phi4_f.exists() or not qwen_f.exists():
            log.warning(f"PMID {pmid}: missing file — skipping from Kappa")
            continue

        phi4_d = json.loads(phi4_f.read_text())
        qwen_d = json.loads(qwen_f.read_text())

        phi4_ox = COLLAPSE.get(phi4_d.get('oxford_level','').lower(), 'V')
        qwen_ox = COLLAPSE.get(qwen_d.get('oxford_level','').lower(), 'V')

        # Handle ? from qwen
        if qwen_ox == '?': qwen_ox = 'V'
        if phi4_ox == '?': phi4_ox = 'V'

        phi4_levels.append(phi4_ox)
        qwen_levels.append(qwen_ox)

        results.append({
            'pmid': pmid,
            'title': phi4_d.get('title','')[:70],
            'study_design': phi4_d.get('study_design',''),
            'phi4_oxford': phi4_ox,
            'qwen_oxford': qwen_ox,
            'agree': phi4_ox == qwen_ox,
            'phi4_relevant': phi4_d.get('relevant_to_primary_question',''),
            'qwen_relevant': qwen_d.get('relevant_to_primary_question',''),
            'phi4_bias': phi4_d.get('grade_risk_of_bias',''),
            'qwen_bias': qwen_d.get('grade_risk_of_bias',''),
        })

    n = len(results)
    kappa, se, po = calculate_kappa(phi4_levels, qwen_levels)
    ci_lo = kappa - 1.96 * se
    ci_hi = kappa + 1.96 * se
    interp = ('Slight' if kappa<.2 else 'Fair' if kappa<.4 else
              'Moderate' if kappa<.6 else 'Substantial' if kappa<.8 else 'Almost perfect')

    log.info("=" * 60)
    log.info("INTRA-AI KAPPA — phi4:14b vs qwen2.5:14b")
    log.info(f"  n = {n} articles")
    log.info(f"  Observed agreement: {po*100:.1f}%  ({sum(r['agree'] for r in results)}/{n})")
    log.info(f"  Kappa: {kappa:.3f} ({interp})")
    log.info(f"  95% CI: {ci_lo:.3f} – {ci_hi:.3f}")
    log.info("=" * 60)

    # Oxford distribution comparison
    log.info("\nOxford distribution comparison:")
    from collections import Counter
    phi4_dist = Counter(phi4_levels)
    qwen_dist  = Counter(qwen_levels)
    for level in ['I','II','III','IV','V']:
        log.info(f"  Level {level}: phi4={phi4_dist.get(level,0)} | qwen={qwen_dist.get(level,0)}")

    # Disagreements
    disagree = [r for r in results if not r['agree']]
    log.info(f"\nDisagreements: {len(disagree)}/{n}")
    for r in disagree:
        log.info(f"  {r['pmid']}: phi4={r['phi4_oxford']} qwen={r['qwen_oxford']} | "
                 f"{r['study_design']} | {r['title'][:50]}")

    # Save comparison CSV
    df = pd.DataFrame(results)
    df.to_csv('irr_model_comparison_full.csv', index=False)
    log.info(f"\nSaved: irr_model_comparison_full.csv ({n} articles)")

    # Save Kappa summary
    summary = {
        'comparison': 'phi4:14b vs qwen2.5:14b',
        'n': n,
        'observed_agreement_pct': round(po*100, 1),
        'kappa': round(kappa, 3),
        'kappa_se': round(se, 3),
        'ci_lower': round(ci_lo, 3),
        'ci_upper': round(ci_hi, 3),
        'interpretation': interp,
        'agree_count': sum(r['agree'] for r in results),
        'disagree_count': len(disagree),
    }
    Path('irr_intraai_kappa.json').write_text(json.dumps(summary, indent=2))
    log.info("Saved: irr_intraai_kappa.json")

if __name__ == '__main__':
    main()
