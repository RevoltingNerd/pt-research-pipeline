# PT Research Pipeline — Topic Configuration Prompt

Use this file to generate the configuration fields for a new pipeline run.
Copy the prompt below and paste it into any AI assistant (Claude, ChatGPT,
Copilot, Gemini, etc.). Answer its questions and it will generate the exact
text to paste into each field of the Pipeline UI at http://localhost:5050.

No coding knowledge required. The AI does the scoping work.

---

## How to use this

1. Open any AI chat interface
2. Copy everything inside the code block below
3. Paste it into the chat and press send
4. Answer the 7 questions the AI asks you
5. Copy the 8 generated fields into the Pipeline UI
6. Paste the 3 PubMed search strings into PubMed → Create RSS (100 items each)
7. Paste the 3 RSS URLs into the Feed A / B / C URL fields in the UI
8. Click Save Config → Run Full Pipeline

---

## The Prompt

```
You are helping a physical therapist configure an automated evidence synthesis
pipeline. The pipeline searches PubMed, screens articles with AI, performs
7-stage clinical appraisal, and produces GRADE-rated evidence syntheses with
Excel and Word report outputs.

I need you to generate the exact text for 8 configuration fields based on my
answers to your questions. Ask me the questions one at a time, then generate
all 8 fields at the end in a clearly labeled format I can copy directly into
the UI.

Ask me these questions in order:

1. CLINICAL TOPIC
   "What clinical topic, intervention, or clinical question do you want to
   review? Describe it in plain language — what the intervention is, what
   condition it treats, and what aspect of it you're most interested in
   (effectiveness, safety, technique, governance, dosage, comparison with
   other treatments, etc.)"

2. AUDIENCE AND PURPOSE
   "Who will read this synthesis and what decision are they trying to make?
   For example: a SIG of practicing PTs deciding whether to adopt a technique,
   a manager designing a training program, a clinician writing a practice
   guideline, a researcher identifying gaps for a grant proposal."

3. SCOPE
   "Should this be a broad scoping review (map the entire literature on this
   topic) or a focused review (answer a specific clinical question)? If
   focused, what is the specific question? For example: does intervention X
   outperform sham for condition Y in population Z?"

4. POPULATION
   "Who is the patient population? Be specific — age range, condition
   severity, chronicity, clinical setting, any important subgroups (athletes,
   post-surgical, pediatric, geriatric, etc.)"

5. GOVERNANCE ANGLE
   "What governance, safety, or scope-of-practice questions are relevant?
   For example: training requirements, adverse event protocols,
   contraindications, scope of practice for a specific license type,
   regulatory frameworks, competency standards."

6. DATE RANGE AND EVIDENCE TYPE
   "How far back should the search go? And are you most interested in
   systematic reviews and meta-analyses, RCTs, all study types, or a specific
   design? Any study designs to exclude?"

7. COMPARISON
   "For the focused research question (if applicable): what is the
   intervention being compared against? Sham, active control, standard care,
   no treatment, another technique, or not applicable?"

After I answer all 7 questions, generate exactly these 8 fields with clear
labels. Be specific, clinical, and precise. Do not use vague language.
Each field should be immediately usable without editing.

─────────────────────────────────────────────────────────────────────────────

FIELD 1 — RESEARCH QUESTION
A single well-formed clinical research question. For a scoping review use:
"What does the peer-reviewed literature report regarding [topic]..."
For a focused review use PICO format:
"In [population], does [intervention] compared to [comparator] produce
[outcome], and what [secondary question]?"

FIELD 2 — TOPIC SHORT NAME
2-4 words. Used in filenames and report titles. Lowercase with spaces.
Example: "dry needling", "vestibular rehabilitation", "pelvic floor PT"

FIELD 3 — RELEVANCE CRITERION
2-4 sentences. This is the exact screening gate used by the AI to decide
whether each article is in-scope or not. Be specific about the intervention,
the condition, the population, and what types of articles qualify
(RCTs only? all study designs? include reviews?).
Start with: "The article concerns..."

FIELD 4 — INTERVENTION NOUN
A short phrase naming the specific intervention being studied.
Used in appraisal prompts throughout the pipeline.
Example: "dry needling intervention", "vestibular rehabilitation program",
"pelvic floor muscle training"

FIELD 5 — GOVERNANCE FOCUS
2-4 sentences describing what "governance" means for this topic specifically.
This drives the governance audit at Stage 6 and the governance synthesis in
the final report. Name the specific regulatory bodies, license types,
training standards, or safety frameworks that are relevant.

FIELD 6 — FEED A DESCRIPTION
One sentence describing what Feed A should contain.
Feed A should be the highest-evidence literature:
systematic reviews, meta-analyses, Cochrane reviews.

FIELD 7 — FEED B DESCRIPTION
One sentence describing what Feed B should contain.
Feed B should be the primary clinical trial literature:
RCTs, controlled trials, cohort studies.

FIELD 8 — FEED C DESCRIPTION
One sentence describing what Feed C should contain.
Feed C should be the governance, safety, and implementation literature:
adverse events, scope of practice, training, guidelines, case reports.

─────────────────────────────────────────────────────────────────────────────

After generating the 8 fields, also generate the 3 PubMed search strings
I should paste into PubMed to create my RSS feeds. Label them clearly as
Feed A Search String, Feed B Search String, Feed C Search String.

For each search string:
- Use Title/Abstract field tags: [Title/Abstract]
- Use Publication Type tags where appropriate: [Publication Type]
- Include synonyms and alternative terminology in OR groups
- Feed A and B: always end with AND free full text[Filter]
- Feed C: omit the free full text filter (governance literature is often
  not open access)
- Keep each string under 500 characters where possible
- Do not use site: operators or quotes around multi-word phrases unless
  they are established MeSH terms

Format each search string as a plain text block ready to paste directly
into the PubMed search bar.
```

---

## Example output (dry needling scoping review)

To give you a sense of what the AI will produce, here is the output from
a dry needling scoping review configuration session:

**FIELD 1 — RESEARCH QUESTION**
What does the peer-reviewed literature report regarding the clinical
effectiveness, safety, and implementation of dry needling in physical
therapy and rehabilitation — including trigger point identification,
needling technique and dosage, functional outcomes, impact on rehabilitation
course, adverse events and contraindications, and scope-of-practice and
governance frameworks for its responsible application by physical therapists?

**FIELD 2 — TOPIC SHORT NAME**
dry needling

**FIELD 3 — RELEVANCE CRITERION**
The article concerns dry needling, trigger point dry needling, intramuscular
stimulation, percutaneous needling, or trigger point needling as an
intervention in physical therapy, rehabilitation, or musculoskeletal care —
including effectiveness, technique, dosage, safety, adverse events, or
governance.

**FIELD 4 — INTERVENTION NOUN**
dry needling intervention

**FIELD 5 — GOVERNANCE FOCUS**
Scope of practice for physical therapists performing dry needling, training
and competency requirements, adverse event reporting and patient safety,
contraindications and precautions, and regulatory or professional oversight
frameworks.

**FIELD 6 — FEED A DESCRIPTION**
Systematic reviews and meta-analyses examining the effectiveness of dry
needling for musculoskeletal pain and rehabilitation outcomes.

**FIELD 7 — FEED B DESCRIPTION**
Randomized controlled trials and clinical trials examining dry needling
technique, dosage, and functional outcomes compared to active or sham
comparators.

**FIELD 8 — FEED C DESCRIPTION**
Safety, adverse events, scope of practice, training requirements, and
governance frameworks for dry needling by physical therapists.

---

## Notes on feed design

**Feed A** (systematic reviews) — always apply the free full text filter.
Cochrane and high-quality SRs are almost always open access.

**Feed B** (clinical trials) — apply the free full text filter. Most PMC-
indexed RCTs from the last 5 years are open access.

**Feed C** (governance/safety) — do NOT apply the free full text filter.
Adverse event case reports, scope-of-practice commentaries, and regulatory
guidance documents are often paywalled or published in specialty journals
without PMC indexing. Layer 0 will still screen them; Layer 2 will skip
those without cached full text.

**Overlap between feeds is expected and handled automatically.** The dedup
step removes duplicates across feeds before any processing begins. Cast a
wide net — it's better to pull 300 articles and dedup to 200 than to miss
a relevant cluster.

**Date range** — the pipeline does not filter by date at the search level.
If you want to limit to the last 5 or 10 years, add a date filter in PubMed
before creating the RSS: Filters → Publication dates.

**RSS item limit** — always set to 100 when creating the RSS feed in PubMed.
This is the maximum PubMed allows per feed. If your search returns more than
100 articles, consider splitting into two feeds by date range or study design.

---

## Quick reference: UI field locations

| Field | Location in UI |
|-------|---------------|
| Research Question | Left panel, top textarea |
| Topic Short Name | Left panel, below research question |
| Relevance Criterion | Left panel, middle textarea |
| Intervention Noun | Left panel, single-line input |
| Governance Focus | Left panel, bottom textarea |
| Feed A URL + Description | Left panel, Feed A card |
| Feed B URL + Description | Left panel, Feed B card |
| Feed C URL + Description | Left panel, Feed C card |

Click **Save Config** after filling all fields, then **Run Full Pipeline**.

---

*PT Research Pipeline v2 — github.com/[your-repo] — MIT License*
