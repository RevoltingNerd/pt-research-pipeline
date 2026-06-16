# PT Research Pipeline v2

An automated evidence synthesis pipeline for physical therapy clinical research. Pulls PubMed open-access literature, screens and appraises articles using local LLMs, applies the GRADE framework, and produces Excel workbooks and Word reports ready for clinical distribution.

Built by a physical therapist, for physical therapists. Runs entirely on local hardware. No cloud APIs, no patient data, no vendor contracts.

---

## What it does

Given a research question and three PubMed RSS feeds, the pipeline:

1. **Fetches** all articles from the feeds, deduplicates across feeds, and caches full text from PubMed Central
2. **Screens** every article — extracting Oxford OCEBM evidence level, relevance to the research question, and GRADE domain flags
3. **Appraises** relevant articles through a 7-stage framework: Signal extraction → Methodology audit → Evidence grading → External validity → Spin detection → Governance audit → Synthesis
4. **Backfills** article metadata (authors, journal, year) from PubMed E-utilities
5. **Clusters** articles dynamically — no predetermined taxonomy, the LLM discovers natural clusters from the corpus
6. **Synthesises** each cluster with GRADE certainty of evidence ratings and clinician-facing recommendations
7. **Exports** a multi-sheet Excel workbook (SharePoint-ready) and a markdown synthesis report

**Default model setup:** a single model, `qwen3.6:35b-a3b`, handles all three LLM layers (screening, appraisal, clustering/synthesis), reading the **full article text** at every stage instead of fixed-size slices — see [Requirements](#requirements) and [Configuration](#configuration). A legacy three-model staged setup (phi4 + qwen2.5 + llama-stable, 8K-char text slices) remains available, see `config.yaml.example`.

The entire run is one button click in the web UI, or one terminal command.

---

## Example outputs

Complete evidence syntheses produced with this pipeline:

| Topic | Model setup | Articles | Clusters | Runtime |
|-------|-------------|----------|----------|---------|
| Dry needling — scoping review | phi4 / qwen2.5 / llama-stable, 8K slices | 135 | 9 | ~14 hrs |
| Myofascial pain dry needling — focused review | phi4 / qwen2.5 / llama-stable, 8K slices | 53 | 7 | ~6 hrs |
| Equine dry needling (legacy stack) | phi4 / qwen2.5 / llama-stable, 8K slices | 4 | 3 | ~45 min |
| Equine dry needling (qwen3.6 validation, 2026-06-14) | qwen3.6:35b-a3b single model, full text, 40K ctx | 8 of 18 screened | 4 | **~XX min** *(fill in from logs)* |

The 2026-06-14 run validated the single-model qwen3.6 setup end-to-end on a fresh re-run of the equine corpus — see "Reliability" below.

---

## Requirements

- macOS or Linux (tested on macOS with Apple Silicon)
- Python 3.10+
- [Ollama](https://ollama.ai) running locally

**Default (recommended):** a single model handles all three layers —
  - `qwen3.6:35b-a3b` — Layer 0 screening, Layer 2 appraisal, Layer 3 clustering + GRADE synthesis. Sparse MoE (35B total / 3B active params), 262K native context. Only one model needs to be resident in memory at a time.

**Legacy alternative** (three separate models, 8K-char text slices at Layer 2):
  - `phi4:14b-q4_K_M` — Layer 0 screening (~9 GB)
  - `qwen2.5:14b` — Layer 2 appraisal (~9 GB)
  - `llama-stable:latest` (or any llama 70B variant) — Layer 3 synthesis (~42 GB)

- 16 GB RAM minimum, 32 GB recommended for running Layer 2 and Layer 3
- Internet access for PubMed RSS and E-utilities (article fetching only — all LLM inference is local)

---

## Installation

```bash
# Clone the repo
git clone https://github.com/your-username/pt-pipeline.git
cd pt-pipeline

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Pull the default model (single model for all three layers)
ollama pull qwen3.6:35b-a3b

# — OR, for the legacy three-model staged setup —
# ollama pull phi4:14b-q4_K_M
# ollama pull qwen2.5:14b
# ollama pull llama-stable:latest   # or whatever 70B variant you have
```

---

## Configuration

Copy the example config and fill in your values:

```bash
cp config.yaml.example config.yaml
```

The `config.yaml` has five sections:

- **`research_question`** — the master steering string shown to synthesis layers
- **`topic`** — four framing variables injected into every LLM prompt: `short_name`, `relevance_criterion`, `intervention_noun`, `governance_focus`
- **`feeds`** — three PubMed RSS feed URLs (generate in PubMed → Create RSS → 100 items)
- **`model`** — Ollama model names per layer, base URL, and per-layer inference options (`layer0_options`/`layer2_options`/`layer3_options` — temperature, num_predict, num_ctx, and `think` for qwen3.6+)
- **`paths`** / **`pipeline`** — output paths and tuning parameters

**To run a new topic: change `config.yaml` only.** No code changes required.

### Generating config fields automatically

Use `PROMPT_TEMPLATE.md` — paste the prompt into any AI assistant (Claude, ChatGPT, Copilot), answer 7 plain-language questions about your topic, and receive all config fields plus three PubMed search strings formatted and ready to paste.

---

## Running the pipeline

### Option 1 — Web UI (recommended)

```bash
source venv/bin/activate
python3 pipeline_ui.py
# Open http://localhost:5050
```

The UI provides:
- All config fields editable in-browser with live save to `config.yaml`
- Phase tracker with per-stage timing and ETA
- Real-time log stream
- Run / Stop controls

### Option 2 — Terminal

```bash
source venv/bin/activate
caffeinate -i python3 run_all.py
```

Resume after interruption:

```bash
python3 run_all.py --from-step 3   # resume from Layer 2
python3 run_all.py --skip-layer3   # stop after backfill (no clustering)
python3 run_all.py --reset         # clear checkpoint and start fresh
```

### Option 3 — Run steps individually

```bash
python3 run_ingest.py --all
python3 run_layer0.py --all
python3 run_layer2.py
python3 run_backfill.py
python3 run_layer3_cluster.py
python3 run_layer3_grade.py
python3 run_export.py
python3 run_report.py
python3 run_archive.py
```

---

## Pipeline architecture

Default model setup: `qwen3.6:35b-a3b` for all three LLM-driven layers, full
article text, 40K context, `think: false`. (Legacy three-model staged setup —
phi4 / qwen2.5 / llama-stable, 8K-char slices — remains available via
`config.yaml.example`; per-layer timings differ accordingly.)

```
PubMed RSS feeds (3)
        │
        ▼
┌─────────────────┐
│  run_ingest.py  │  Fetch, dedup, cache full text
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  run_layer0.py  │  qwen3.6:35b-a3b — relevance screen, Oxford level, GRADE flags
└────────┬────────┘  (~15 sec/article, full text, 40K ctx)
         │
         ▼
┌─────────────────┐
│  run_layer2.py  │  qwen3.6:35b-a3b — 7-stage deep appraisal, full text
└────────┬────────┘
         │
         ▼
┌──────────────────┐
│ run_backfill.py  │  PubMed E-utilities — authors, journal, year, DOI
└────────┬─────────┘
         │
         ▼
┌──────────────────────────┐
│ run_layer3_cluster.py    │  qwen3.6:35b-a3b — dynamic corpus clustering
└────────┬─────────────────┘  (no predetermined taxonomy)
         │
         ▼
┌──────────────────────────┐
│ run_layer3_grade.py      │  qwen3.6:35b-a3b — GRADE synthesis per cluster
└────────┬─────────────────┘
         │
         ▼
┌─────────────────┐  ┌──────────────────┐
│  run_export.py  │  │  run_report.py   │
│  Excel workbook │  │  Markdown report │
└────────┬────────┘  └────────┬─────────┘
         └──────────┬──────────┘
                     ▼
          ┌──────────────────────┐
          │  run_archive.py      │  Move outputs to archive/{topic}_{date}/,
          │  Archive & reset     │  reset cache/summaries/logs to empty
          └──────────────────────┘
```

### The 7-stage appraisal (Layer 2)

Each article passes through 7 sequential stages, each reading a targeted slice of the full text and passing structured JSON outputs to the next stage:

| Stage | Name | What it does |
|-------|------|-------------|
| 1 | Signal | Study design, N, intervention, comparator, primary outcome and result |
| 2 | Preparation | Randomization, blinding, allocation concealment, dropout, ITT, bias risk |
| 3 | Evidence Grade | Oxford OCEBM level with quality adjustment, clinical necessity |
| 4 | Context | Population, setting, geography, generalizability |
| 5 | Dissonance | Spin detection — does conclusion language overstate the numbers? |
| 6 | Governance Audit | Statistical honesty + governance claim without method |
| 7 | Synthesis | GRADE inputs, key takeaway, evidence statement, research relevance |

### Dynamic clustering (Layer 3)

Unlike fixed taxonomies, the pipeline discovers clusters from the actual corpus:

- **Pass 1** — LLM reads a sample of clinical domain strings and proposes natural cluster names and definitions grounded in what's actually there
- **Pass 2** — LLM assigns every article to a discovered cluster

Cluster names, boundaries, and definitions vary by corpus. The same pipeline run on vestibular rehab will produce completely different clusters than dry needling — because they should.

---

## Output files

| File | Description |
|------|-------------|
| `ledger.csv` | Master ingest ledger — all fetched articles |
| `layer0_ledger.csv` | All screened articles with Oxford level and relevance flag |
| `summaries/layer0/*.md` | Per-article Layer 0 markdown summaries |
| `summaries/deep/*_layer2.json` | Full 7-stage appraisal data per article |
| `summaries/deep/*_layer2.md` | Human-readable Layer 2 markdown summaries |
| `layer3_clusters.json` | Cluster assignments for all articles |
| `layer3_cluster_definitions.json` | Discovered cluster names and definitions |
| `summaries/layer3/MASTER_GRADE_SYNTHESIS.json` | Full GRADE synthesis per cluster |
| `{topic}_evidence_base_{date}.xlsx` | Excel workbook — 6 sheets, SharePoint-ready |
| `{topic}_synthesis_report_{date}.md` | Markdown synthesis report |

### Excel workbook sheets

| Sheet | Contents |
|-------|----------|
| Summary | One row per cluster — GRADE certainty, recommendation, governance finding |
| Articles_L2 | One row per appraised article — full appraisal fields, 39 columns |
| Articles_L0 | All screened articles including excluded, with relevance notes |
| Clusters | Discovered cluster definitions |
| Governance | All governance flags sorted by gap severity |
| Meta | Run metadata — topic, research question, models, date |

---

## Running multiple topics

Each topic run produces its own dated output files. **Archiving now happens automatically** as the final step of `run_all.py` (Step 9): every run-specific output is moved into `archive/{short_name}_{YYYYMMDD}/`, a copy of `config.yaml` is saved alongside it for provenance, and `cache/`, `summaries/`, and `logs/` are recreated empty — the working tree is back to a clean baseline, ready for the next topic.

```bash
python3 run_all.py              # full pipeline, archives automatically at the end
python3 run_all.py --no-archive # leave outputs in place for inspection
python3 run_archive.py          # run archiving manually (e.g. after running steps individually)
python3 run_archive.py --dry-run # preview what would be archived, change nothing
```

What gets archived: `ledger.csv`, `layer0_ledger.csv`, `layer3_clusters.*`, `layer3_cluster_definitions.json`, `.pipeline_checkpoint.json`, `cache/`, `summaries/`, `logs/`, the Excel workbook, and the markdown synthesis report. `config.yaml` itself is **copied** (not moved) — edit it for the new topic and run again. The repo accumulates a clean archive of every synthesis you've run.

---

## What the pipeline finds (and doesn't find)

**Finds well:**
- Spin in conclusion language (overstated claims vs reported numbers)
- Governance gaps (papers recommending an intervention without addressing training, safety, or regulatory frameworks)
- Oxford OCEBM evidence levels with quality adjustment
- Dynamic clinical clustering from corpus content
- GRADE certainty of evidence per cluster

**Does not find:**
- Information that isn't in the peer-reviewed PMC open-access corpus — regulatory documents, professional standards, licensing board opinions, and grey literature are not in PubMed
- Evidence quality better than what the literature contains — GRADE Low means the studies are methodologically limited, not that the pipeline is wrong
- Anything requiring subscription-journal full text — Layer 2 requires PMC full text; paywalled articles are screened at Layer 0 only

**On the governance gap finding:** When the pipeline reports "98% of articles make governance claims without method support," this does not mean governance frameworks don't exist. It means the academic literature is not citing or engaging with the regulatory and professional frameworks that practitioners already operate within. This is a finding about the literature, not about practice.

---

## Reliability

Intra-AI reliability (phi4 vs qwen2.5, Oxford OCEBM level agreement, dry needling validation corpus): **Kappa = 0.505 (Moderate agreement)**. All outputs are AI-generated and should be reviewed by a qualified clinician before informing clinical policy.

**Single-model qwen3.6:35b-a3b setup** was validated end-to-end on 2026-06-14 on a re-run of the equine dry needling corpus (8 relevant articles of 18 screened, 4 dynamically-discovered clusters). All 8 articles produced clean JSON across all 7 Layer 2 appraisal stages with no `<think>`-tag leakage (`think: false`); Layer 3 clustering and GRADE synthesis produced genuinely differentiated, internally-consistent reasoning per cluster (distinct starting certainties, downgrade rationales, and governance counts that sum correctly to each cluster's article count). No separate intra-AI reliability (Kappa) run has yet been performed for the qwen3.6 single-model setup — the Kappa figure above reflects the legacy phi4/qwen2.5 staged setup.

---

## Repository structure

```
pt-pipeline/
├── pipeline_ui.py              # Web UI (Flask) — http://localhost:5050
├── run_all.py                  # Full pipeline orchestrator
├── run_ingest.py               # Step 1: Feed ingestion
├── run_layer0.py               # Step 2: Screening (qwen3.6 default; phi4 legacy)
├── run_layer2.py               # Step 3: Deep appraisal (qwen3.6 default; qwen2.5 legacy)
├── run_backfill.py             # Step 4: Metadata backfill
├── run_layer3_cluster.py       # Step 5: Dynamic clustering (qwen3.6 default; llama legacy)
├── run_layer3_grade.py         # Step 6: GRADE synthesis (qwen3.6 default; llama legacy)
├── run_export.py               # Step 7: Excel export
├── run_report.py               # Step 8: Markdown report
├── run_archive.py              # Step 9: Archive run outputs and reset baseline
├── config.yaml.example         # Config template — copy to config.yaml
├── PROMPT_TEMPLATE.md          # AI prompt to generate config fields
├── requirements.txt
├── pipeline/                   # Core modules
│   ├── ingest.py               # RSS parsing, PMID extraction
│   ├── fetch.py                # PMC full-text fetching and caching
│   ├── dedup.py                # Ledger deduplication
│   └── appraise_staged.py      # 7-stage appraisal engine
├── prompts/                    # LLM prompt templates
│   ├── layer0_extraction.txt
│   ├── layer3_clustering.txt
│   ├── layer3_grade_synthesis.txt
│   └── stages/
│       ├── stage1_signal.txt
│       ├── stage2_preparation.txt
│       ├── stage3_evidence_grade.txt
│       ├── stage4_context.txt
│       ├── stage5_dissonance.txt
│       ├── stage6_governance_audit.txt
│       └── stage7_synthesis.txt
└── analysis/                   # Validation utilities (not part of main pipeline)
    ├── calculate_kappa.py
    └── dashboard.py
```

---

## License

MIT License — free to use, modify, and distribute. If you use this pipeline in a clinical or research context, attribution is appreciated but not required.

---

## Background

This pipeline was built to solve a real problem: physical therapy special interest groups reviewing one or two articles per monthly meeting, while the evidence base accumulates faster than any volunteer committee can read it. The 17-year gap between research publication and clinical practice in PT is well-documented. This is one approach to closing it.

The design principle is deliberate: every topic-specific element lives in `config.yaml`. The code and prompts are neutral scaffolding. Changing topics means editing one file.

Built on local hardware, on personal time, with open-access literature. No budget, no committee, no permission required.

*PT Research Pipeline v2 — automated evidence synthesis for physical therapy*
