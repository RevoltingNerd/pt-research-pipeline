"""
extract_cpg_evidence.py — CPG Gold Standard Extractor v3
PT Research Pipeline

Reads JOSPT/APTA CPG PDFs. Uses word-coordinate column splitting to
handle two-column layouts. Extracts study citations from evidence
appendix tables. Maps ref numbers to DOIs. Looks up PMIDs.
Outputs gold_standard_grades.csv for Kappa validation.

Usage:
    python3 extract_cpg_evidence.py              # all CPGs
    python3 extract_cpg_evidence.py --test       # first CPG only, verbose
    python3 extract_cpg_evidence.py --no-lookup  # skip PubMed lookups
"""

import re, os, sys, time, argparse, logging
import requests
import pandas as pd
from pathlib import Path

PIPELINE_ROOT = Path(__file__).parent.resolve()
CPG_DIR       = PIPELINE_ROOT / "CPGs"

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] — %(message)s")
log = logging.getLogger(__name__)

STUDY_TYPE_TO_OXFORD = {
    'systematic review of rcts':   '1a',
    'meta-analysis':               '1a',
    'systematic review':           '1a',
    'cluster rct':                 '1b',
    'cluster randomised':          '1b',
    'cluster randomized':          '1b',
    'rct':                         '1b',
    'randomized controlled':       '1b',
    'randomised controlled':       '1b',
    'prospective cohort':          '2b',
    'cohort':                      '2b',
    'retrospective cohort':        '2b',
    'case-control':                '3b',
    'cross-sectional':             '4',
    'case series':                 '4',
    'expert opinion':              '5',
    'narrative review':            '5',
}

OXFORD_TO_CPG = {
    '1a':'I','1b':'I','1c':'I',
    '2a':'II','2b':'II','2c':'II',
    '3a':'III','3b':'III',
    '4':'IV','5':'V',
}


def extract_doi(text):
    m = re.search(r'https?://doi\.org/(\S+)', text)
    if m: return m.group(1).rstrip('.,)')
    m = re.search(r'org/(10\.\S+)', text)
    if m: return m.group(1).rstrip('.,)')
    m = re.search(r'[a-z]/(10\.\d{4,}/\S+)', text)
    if m: return m.group(1).rstrip('.,)')
    m = re.search(r'\bdoi:\s*(10\.\S+)', text, re.IGNORECASE)
    if m: return m.group(1).rstrip('.,)')
    return None


def extract_year(text):
    m = re.search(r'[;.]\s*((?:19|20)\d{2})[;:,]', text)
    return m.group(1) if m else None


def extract_first_author(text):
    m = re.match(r'^\d+\.\s+([A-Z])\s*([a-z]+)', text)
    if m: return m.group(1) + m.group(2)
    m = re.match(r'^\d+\.\s+([A-Z][a-z]+)', text)
    if m: return m.group(1)
    return None


def doi_to_pmid(doi, delay=0.35):
    try:
        time.sleep(delay)
        resp = requests.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            params={"db":"pubmed","term":f"{doi}[doi]","retmax":"1","retmode":"json"},
            timeout=15
        )
        ids = resp.json().get("esearchresult",{}).get("idlist",[])
        return ids[0] if ids else None
    except: return None


def author_year_to_pmid(author, year, title_words, delay=0.35):
    if not author: return None
    try:
        time.sleep(delay)
        query = f"{author}[Author]"
        if year: query += f" AND {year}[pdat]"
        if title_words:
            query += f" AND ({' OR '.join(title_words[:3])})[Title]"
        resp = requests.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            params={"db":"pubmed","term":query,"retmax":"1","retmode":"json"},
            timeout=15
        )
        ids = resp.json().get("esearchresult",{}).get("idlist",[])
        return ids[0] if ids else None
    except: return None


def extract_references(pdf_path):
    """
    Extract numbered reference list using word-coordinate column splitting.
    Handles two-column JOSPT/APTA layouts correctly.
    Returns dict: ref_number_str -> full_text_str
    """
    import pdfplumber

    all_ref_chunks = {}
    in_refs = False

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text(layout=True) or ''
            if re.search(r'^\s*REFERENCES?\s*$', text, re.MULTILINE):
                in_refs = True
            if not in_refs:
                continue

            width = page.width
            midpoint = width / 2
            words = page.extract_words()

            left_words  = [w for w in words if float(w['x0']) < midpoint]
            right_words = [w for w in words if float(w['x0']) >= midpoint]

            def words_to_lines(word_list):
                if not word_list: return []
                lines = {}
                for w in word_list:
                    y = round(float(w['top']) / 3) * 3
                    if y not in lines: lines[y] = []
                    lines[y].append(w['text'])
                return [' '.join(lines[y]) for y in sorted(lines.keys())]

            for col_lines in [words_to_lines(left_words), words_to_lines(right_words)]:
                current_num = None
                current_parts = []
                for line in col_lines:
                    stripped = line.strip()
                    if not stripped: continue
                    m = re.match(r'^(\d+)\.\s+', stripped)
                    # Filter out spurious page numbers (>500)
                    if m and int(m.group(1)) < 500:
                        if current_num and current_parts:
                            if current_num not in all_ref_chunks:
                                all_ref_chunks[current_num] = []
                            all_ref_chunks[current_num].extend(current_parts)
                        current_num = m.group(1)
                        current_parts = [stripped]
                    elif current_num:
                        current_parts.append(stripped)
                if current_num and current_parts:
                    if current_num not in all_ref_chunks:
                        all_ref_chunks[current_num] = []
                    all_ref_chunks[current_num].extend(current_parts)

    return {num: ' '.join(parts) for num, parts in all_ref_chunks.items()}


def extract_evidence_appendix(pdf_path):
    """
    Extract study citations from evidence appendix tables.
    Pattern: 'Author et al## StudyType ...'
    """
    import pdfplumber

    rows = []
    study_type_pattern = (
        r'(Cohort|Cluster RCT|Cluster randomized|Cluster randomised|'
        r'RCT|Randomized controlled|Randomised controlled|'
        r'Meta-analysis|Systematic review|Case series|Cross-sectional|'
        r'Prospective cohort|Retrospective cohort)'
    )

    with pdfplumber.open(pdf_path) as pdf:
        in_appendix = False
        for page in pdf.pages:
            text = page.extract_text(layout=True) or ''
            if re.search(r'APPENDIX', text, re.IGNORECASE):
                in_appendix = True
            if not in_appendix:
                continue
            for line in text.split('\n'):
                stripped = line.strip()
                m = re.match(
                    r'([A-Z][a-z]+(?:\s+et\s+al)?)\s*(\d+)\s+' + study_type_pattern,
                    stripped, re.IGNORECASE
                )
                if m:
                    study_type = m.group(3)
                    oxford = None
                    for key, ox in STUDY_TYPE_TO_OXFORD.items():
                        if key in study_type.lower():
                            oxford = ox
                            break
                    rows.append({
                        'author':     m.group(1),
                        'ref_num':    m.group(2),
                        'study_type': study_type,
                        'oxford_cpg': oxford,
                    })

    # Deduplicate by ref_num
    seen = {}
    for r in rows:
        if r['ref_num'] not in seen:
            seen[r['ref_num']] = r
    return list(seen.values())


def process_cpg(pdf_path, lookup=True, verbose=False):
    cpg_name = pdf_path.stem
    log.info(f"Processing: {cpg_name}")

    try:
        refs = extract_references(pdf_path)
        rows = extract_evidence_appendix(pdf_path)
    except Exception as e:
        log.error(f"  Failed: {e}")
        return []

    log.info(f"  {len(refs)} references | {len(rows)} evidence table entries")

    results = []
    for row in rows:
        ref_num  = row['ref_num']
        ref_text = refs.get(ref_num, '')
        doi      = extract_doi(ref_text)
        year     = extract_year(ref_text)
        author   = extract_first_author(ref_text)
        pmid     = None
        pmid_method = 'none'

        if lookup:
            if doi:
                pmid = doi_to_pmid(doi)
                if pmid: pmid_method = 'doi'
            if not pmid and author:
                stop = {'sports','study','patients','clinical','effects',
                        'treatment','randomized','anterior','posterior',
                        'injury','injuries','ligament','exercise'}
                title_words = [w for w in re.findall(r'[a-zA-Z]{5,}', ref_text)
                               if w.lower() not in stop][:4]
                pmid = author_year_to_pmid(author, year, title_words)
                if pmid: pmid_method = 'author_year'

        result = {
            'cpg_name':    cpg_name,
            'ref_num':     ref_num,
            'author':      row['author'],
            'study_type':  row['study_type'],
            'oxford_cpg':  row['oxford_cpg'],
            'doi':         doi,
            'year':        year,
            'pmid':        pmid,
            'pmid_method': pmid_method,
        }
        results.append(result)

        if verbose:
            log.info(f"  Ref {ref_num}: {row['author']} | {row['study_type']} | "
                     f"Oxford {row['oxford_cpg']} | PMID: {pmid} ({pmid_method})")

    found = sum(1 for r in results if r['pmid'])
    log.info(f"  PMIDs found: {found}/{len(results)}")
    return results


def build_gold_standard(all_results):
    df = pd.DataFrame(all_results)
    df_pmid = df[df['pmid'].notna() & (df['pmid'] != '')].copy()
    level_rank = {'1a':1,'1b':2,'1c':3,'2a':4,'2b':5,'2c':6,
                  '3a':7,'3b':8,'4':9,'5':10}
    df_pmid['rank'] = df_pmid['oxford_cpg'].map(level_rank).fillna(11)
    df_dedup = df_pmid.sort_values('rank').drop_duplicates('pmid', keep='first')
    log.info(f"Gold standard: {len(df_dedup)} unique PMIDs")
    for ox in ['1a','1b','2a','2b','3a','3b','4','5']:
        n = len(df_dedup[df_dedup['oxford_cpg'] == ox])
        if n: log.info(f"  Oxford {ox}: {n}")
    return df_dedup


def cross_reference(gold, ledger_path):
    if not ledger_path.exists():
        log.warning("ledger.csv not found")
        return pd.DataFrame()
    ledger = pd.read_csv(ledger_path, dtype=str)
    ledger['pmid'] = ledger['pmid'].astype(str).str.strip()
    gold = gold.copy()
    gold['pmid'] = gold['pmid'].astype(str).str.strip()
    merged = gold.merge(ledger[['pmid','oxford_level','title']], on='pmid', how='inner')
    if len(merged):
        merged['ai_oxford_collapsed'] = merged['oxford_level'].map(OXFORD_TO_CPG).fillna('?')
        agree = (merged['oxford_cpg'].map(lambda x: OXFORD_TO_CPG.get(x,x)) ==
                 merged['ai_oxford_collapsed']).sum()
        log.info(f"Overlap: {len(merged)} articles in both corpora")
        log.info(f"Agreement: {agree}/{len(merged)} ({100*agree//max(len(merged),1)}%)")
    return merged


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--test',      action='store_true')
    parser.add_argument('--no-lookup', action='store_true')
    parser.add_argument('--cpg',       type=str)
    args = parser.parse_args()

    os.chdir(PIPELINE_ROOT)
    pdfs = sorted(CPG_DIR.glob('*.pdf'))
    if args.cpg:
        pdfs = [p for p in pdfs if args.cpg.lower() in p.stem.lower()]
    if args.test:
        pdfs = pdfs[:1]

    log.info(f"Processing {len(pdfs)} CPGs")
    all_results = []

    for pdf in pdfs:
        results = process_cpg(pdf, lookup=not args.no_lookup, verbose=args.test)
        all_results.extend(results)

    if not all_results:
        log.warning("No results extracted")
        return

    raw_df = pd.DataFrame(all_results)
    raw_df.to_csv('cpg_citations_raw.csv', index=False)
    log.info(f"Raw saved: cpg_citations_raw.csv ({len(raw_df)} rows)")

    if not args.test:
        gold = build_gold_standard(all_results)
        gold.to_csv('gold_standard_grades.csv', index=False)
        log.info(f"Gold standard saved: gold_standard_grades.csv ({len(gold)} PMIDs)")

        overlap = cross_reference(gold, PIPELINE_ROOT / 'ledger.csv')
        if len(overlap):
            overlap.to_csv('cpg_pipeline_overlap.csv', index=False)
            log.info(f"Overlap saved: cpg_pipeline_overlap.csv ({len(overlap)} articles)")
            print("\n" + "="*60)
            print("OVERLAP — CPG Oxford vs AI Oxford level")
            print("="*60)
            for _, row in overlap.iterrows():
                cpg_col = OXFORD_TO_CPG.get(row['oxford_cpg'], row['oxford_cpg'])
                match = "✓" if cpg_col == row['ai_oxford_collapsed'] else "✗"
                print(f"{match} PMID {row['pmid']}: CPG={row['oxford_cpg']} "
                      f"AI={row['oxford_level']} | {str(row.get('title',''))[:55]}")


if __name__ == '__main__':
    main()
