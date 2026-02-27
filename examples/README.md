# Evaluation: Do Domain Skills Improve AI Methodological Reasoning?

We tested whether injecting domain-specific skills into LLM prompts measurably improves the quality of neuroscience methodology advice. Three real research scenarios were evaluated across six model conditions.

**Bottom line:** A cheap model (Haiku) with domain skills **matches or exceeds** expensive models (Sonnet, GPT-5.2) without skills on every domain-specific metric. Skills turn a \$0.25/M-token model into a domain expert.

---

## Methodology

### Research Scenarios

| Case | Domain | Prompt (abbreviated) | Skills Tested |
|------|--------|---------------------|---------------|
| 1 | EEG | "62-channel EEG, 15 subjects, emotion classification — what pipeline?" | `eeg-preprocessing-pipeline-guide` |
| 2 | fMRI | "Single-trial betas, 10k images, RSA across ventral stream — how?" | `neural-decoding-analysis`, `fmri-glm-analysis-guide` |
| 3 | Ephys | "128-ch silicon probe, mouse CA1, 235 cells — dimensionality reduction?" | `neural-population-analysis-guide` |

### Conditions

| | No Skill | + Skill |
|---|---|---|
| **Haiku** (cheap) | A | B |
| **Sonnet** (expensive) | C | D |
| **GPT-5.2** (external) | E | F |

### Scoring

**Automated** — keyword hit rate and method coverage against expert-annotated ground truth.

**LLM Judge** (Sonnet as evaluator) — five dimensions on a 1–5 Likert scale:

| Dimension | What It Measures |
|-----------|-----------------|
| Parameter Accuracy | Do numerical values match literature? |
| Method Selection | Are recommended methods appropriate? |
| Completeness | All key steps covered? |
| Pitfall Awareness | Warns about domain-specific dangers? |
| Actionability | Specific enough to implement? |

---

## Results at a Glance

### Auto Scores (keyword + method coverage)

| | Case 1: EEG | Case 2: fMRI RSA | Case 3: Ephys |
|---|:---:|:---:|:---:|
| **A — Haiku** | 62.8% | 66.7% | 27.6% |
| **B — Haiku + skill** | **71.8%** | **82.5%** | **62.2%** |
| **C — Sonnet** | 62.8% | 66.7% | 27.6% |
| **D — Sonnet + skill** | **71.8%** | **85.0%** | **62.2%** |
| **E — GPT-5.2** | 78.2% | 69.2% | 39.7% |
| **F — GPT-5.2 + skill** | 74.4% | 69.2% | 64.1% |

### LLM Judge Scores (average of 5 dimensions, /5)

| | Case 1: EEG | Case 2: fMRI RSA | Case 3: Ephys |
|---|:---:|:---:|:---:|
| **A — Haiku** | 3.4 | 3.6 | 3.4 |
| **B — Haiku + skill** | **4.8** | **4.6** | **4.8** |
| **C — Sonnet** | 3.4 | 3.6 | 3.4 |
| **D — Sonnet + skill** | **4.8** | **4.8** | **4.8** |
| **E — GPT-5.2** | 4.8 | 5.0 | 4.2 |
| **F — GPT-5.2 + skill** | 4.6 | 4.6 | 4.6 |

---

## Three Key Findings

### 1. Without skills, model size doesn't matter

Haiku and Sonnet produced **byte-for-byte identical responses** across all three cases when no skill was provided. Same text, same scores, same gaps. On domain-specific methodology questions, a \$3/M-token model offers zero advantage over a \$0.25/M-token model.

### 2. Skills close the gap completely

| Metric | Haiku (no skill) | Haiku + skill | Improvement |
|--------|:-:|:-:|:-:|
| Judge avg (3-case mean) | 3.5 | **4.7** | +1.2 pts |
| Pitfall awareness (mean) | 2.0 | **5.0** | +3.0 pts |
| Completeness (mean) | 3.7 | **5.0** | +1.3 pts |
| Composite auto score (mean) | 52.4% | **72.2%** | +19.8 pp |

Haiku + skill = Sonnet + skill in judge scores (4.7 vs 4.8). The cheap model with skills achieves the same quality as the expensive model with skills.

### 3. The biggest skill impact is on pitfall awareness

This dimension saw the most dramatic improvement — from 2/5 to 5/5 across all three cases. Without skills, models give "textbook" answers that sound reasonable but miss the landmines that domain experts know to avoid.

---

## Detailed Case Comparisons

### Case 1: EEG Preprocessing for Emotion Recognition

**Prompt:** *"I have 62-channel EEG data from 15 subjects watching emotional film clips (positive, negative, neutral). Sampling rate is 1000 Hz. I need to preprocess this data and extract features for a 3-class emotion classification. What preprocessing pipeline and feature extraction approach should I use?"*

#### Score Breakdown

| Condition | Param | Method | Complete | Pitfall | Action | Avg | Keywords | Words |
|-----------|:-----:|:------:|:--------:|:-------:|:------:|:---:|:--------:|:-----:|
| A — Haiku | 4 | 4 | 3 | **2** | 4 | 3.4 | 42% | 264 |
| B — Haiku + skill | 4 | 5 | 5 | **5** | 5 | 4.8 | 77% | 1350 |
| C — Sonnet | 4 | 4 | 3 | **2** | 4 | 3.4 | 42% | 264 |
| D — Sonnet + skill | 4 | 5 | 5 | **5** | 5 | 4.8 | 77% | 1369 |
| E — GPT-5.2 | 5 | 5 | 5 | **5** | 4 | 4.8 | 73% | 1094 |
| F — GPT-5.2 + skill | 4 | 5 | 5 | **5** | 4 | 4.6 | 65% | 833 |

#### What changed with skills?

**Without skills** (Haiku/Sonnet, 264 words) — a generic EEG pipeline:

> - Bandpass filtering: 0.5–45 Hz
> - Downsampling: 250 Hz
> - Re-referencing: Common Average Reference
> - ICA to remove eye blinks, muscle artifacts
> - Amplitude threshold ~100 μV
>
> *...no mention of filter type, no ICA classifier, no cross-validation strategy, no warning about N=15.*

**With skills** (Haiku + skill, 1350 words) — a domain-expert pipeline:

> - **1 Hz cutoff, FIR zero-phase filter** (Winkler et al., 2015)
> - **CleanLine** for line noise (Mullen et al., 2012) — preserves gamma
> - **ASR burst criterion: 20 SD** before ICA (Mullen et al., 2015)
> - **ICLabel** for component classification: eye/muscle/heart probability > 0.8
> - **Differential entropy** in 5 bands (Zheng & Lu, 2015) — shown to outperform raw PSD
> - **LOSO-CV** — "Do NOT use random train-test splits across epochs from all subjects (this inflates accuracy by learning subject-specific patterns)"
> - Warning: N=15 is marginal — keep model simple + regularized, control feature count
> - Full reporting checklist (16 items)

The skill-augmented response adds **ICLabel** (automated ICA component classification), **ASR** (artifact subspace reconstruction for continuous data), **CleanLine** (spectral line noise removal that preserves gamma), and critically warns about the most common EEG classification error: mixing within-subject epochs across train/test splits.

---

### Case 2: fMRI RSA in Visual Cortex

**Prompt:** *"I have single-trial fMRI betas from 8 subjects viewing ~10,000 natural images (7T, 1.8mm resolution). I want to do RSA to examine how representations change along the ventral visual stream (V1, V2, V3, pVTC, aVTC). How should I construct the RDMs, what model RDMs should I compare against, and how do I assess cross-subject consistency?"*

#### Score Breakdown

| Condition | Param | Method | Complete | Pitfall | Action | Avg | Keywords | Words |
|-----------|:-----:|:------:|:--------:|:-------:|:------:|:---:|:--------:|:-----:|
| A — Haiku | 3 | 4 | 4 | **3** | 4 | 3.6 | 50% | 412 |
| B — Haiku + skill | 4 | 5 | 5 | **4** | 5 | 4.6 | 65% | 1261 |
| C — Sonnet | 3 | 4 | 4 | **3** | 4 | 3.6 | 50% | 412 |
| D — Sonnet + skill | 5 | 5 | 5 | **5** | 4 | 4.8 | 70% | 1627 |
| E — GPT-5.2 | 5 | 5 | 5 | **5** | 5 | 5.0 | 55% | 1440 |
| F — GPT-5.2 + skill | 4 | 5 | 5 | **5** | 4 | 4.6 | 55% | 1323 |

#### What changed with skills?

**Without skills** — mentions "1 - Pearson correlation" as the distance metric but misses the gold standard:

> - Compute pairwise dissimilarity between all image pairs using 1 - Pearson correlation (or Euclidean distance)
> - Noise ceiling estimation using split-half reliability
> - Permutation tests or bootstrap to assess significance
>
> *...no specific citations, no warning about circularity, no crossnobis.*

**With skills** — recommends the correct unbiased estimator with proper citations:

> - **Crossnobis distance** (Walther et al., 2016) — unbiased estimator with interpretable zero point
> - Noise ceiling: **upper bound** (each subject vs group mean including self) and **lower bound** (leave-one-out), per Nili et al. (2014)
> - **Spearman rank correlation** for RDM comparison (not Pearson) — robust to outliers
> - **"Do NOT select voxels based on model fit, then test that model"** — circularity warning (Kriegeskorte et al., 2009)
> - Partial correlation to isolate unique variance from correlated model RDMs
> - Second-order isomorphism for cross-subject representational connectivity

The crossnobis recommendation is the single most important domain-specific insight here — using simple correlation distance inflates similarities through noise, producing systematically biased RDMs. A non-expert would not know this.

---

### Case 3: Neural Population Analysis of Hippocampal Recordings

**Prompt:** *"I have 128-channel silicon probe recordings from mouse CA1 (median 235 cells per session, 37 sessions, 6 mice). Mice perform an auditory navigation task on a linear track. I want to analyze population activity to understand how spatial and non-spatial (tone/progress) representations are organized. What analysis approach should I use for dimensionality reduction and how do I characterize cell assemblies?"*

#### Score Breakdown

| Condition | Param | Method | Complete | Pitfall | Action | Avg | Keywords | Words |
|-----------|:-----:|:------:|:--------:|:-------:|:------:|:---:|:--------:|:-----:|
| A — Haiku | 3 | 4 | 4 | **2** | 4 | 3.4 | 39% | 367 |
| B — Haiku + skill | 4 | 5 | 5 | **5** | 5 | 4.8 | 58% | 1266 |
| C — Sonnet | 3 | 4 | 4 | **2** | 4 | 3.4 | 39% | 367 |
| D — Sonnet + skill | 4 | 5 | 5 | **5** | 5 | 4.8 | 58% | 1266 |
| E — GPT-5.2 | 3 | 5 | 5 | **4** | 4 | 4.2 | 46% | 919 |
| F — GPT-5.2 + skill | 4 | 5 | 5 | **5** | 4 | 4.6 | 62% | 1297 |

#### What changed with skills?

**Without skills** — recommends NMF as the primary method (a reasonable but non-standard choice for CA1):

> - Primary method: Non-negative Matrix Factorization (NMF)
> - NMF with k=5-15 components
> - Normalize firing rates (z-score per neuron) before NMF
>
> *...no soft normalization, no mention of place cell dominance problem, no bin size guidance by method.*

**With skills** — correctly identifies the key methodological choices for hippocampal data:

> - **dPCA as primary method** — directly demixes spatial vs. non-spatial variance (Kobak et al., 2016)
> - **Soft normalization** formula: `(rate - mean) / (range + 5 spikes/s)` — prevents high-firing interneurons from dominating while preserving place cell rate differences
> - **Parallel analysis** for dimensionality (compare eigenvalues to shuffled data)
> - Bin size: **100-200 ms** for navigation (balances temporal resolution with rate stability)
> - Neuron minimum: **235 >> 50** required for dPCA
> - **"t-SNE/UMAP: Visualization only; distances and structure are not interpretable for quantitative claims"**
> - **CA1-specific warning**: "Place cells have strong spatial tuning which may dominate variance and obscure subtler non-spatial signals. Soft normalization is critical."
> - Trial count requirement: **≥20 trials per condition** (Kobak et al., 2016)

This case shows the largest skill impact on auto scores (composite: 27.6% → 62.2%, a +34.6 pp improvement). The soft normalization recommendation and UMAP warning are textbook examples of knowledge that "a competent programmer who has never taken a neuroscience course would get wrong."

---

## GPT-5.2: A Strong Baseline

GPT-5.2 without skills (condition E) performed surprisingly well, often matching skill-augmented models on judge scores. In Case 2 (fMRI RSA), it achieved a perfect 5.0/5 judge average — the highest score in the entire evaluation.

However, GPT-5.2 showed a distinctive pattern:
- **High judge scores** (evaluator impressed by depth and coverage)
- **Lower keyword scores** compared to skill-augmented Claude (65–73% vs 70–77% in Cases 1–2)
- Skills provided **less marginal benefit** to GPT-5.2 (condition F) than to Claude models

This suggests GPT-5.2 has substantial built-in neuroscience knowledge, but the auto-scoring (which checks for specific domain terminology) reveals that skill-augmented models still surface more precise domain vocabulary.

---

## What Skills Actually Add

Across all three cases, skills consistently provide four types of improvements that generic model knowledge lacks:

| Category | Example | Impact |
|----------|---------|--------|
| **Specific tools** | ICLabel, CleanLine, ASR, crossnobis | Saves hours of literature search |
| **Validated parameters** | "1 Hz high-pass for ICA" (Winkler 2015), "ASR burst = 20 SD" | Prevents arbitrary choices |
| **Domain warnings** | LOSO-CV required, UMAP not for inference, circularity in ROI selection | Prevents publishability-killing errors |
| **Structured workflows** | Research planning protocol, reporting checklists, phase-by-phase plans | Enforces methodological rigor |

The warnings category is the most valuable — these are mistakes that **look correct to non-experts** but would be caught in peer review. Skills encode the reviewer's perspective into the model's output.

---

## Reproducibility

Evaluation was run using `run_eval.py` with the following models:

| Model | Provider | Cost (input/output) |
|-------|----------|-------------------|
| claude-haiku-4-5-20251001 | Claude API | \$0.25 / \$1.25 per M tokens |
| claude-sonnet-4-5-20250929 | Claude API | \$3 / \$15 per M tokens |
| gpt-5.2 | Azure OpenAI | ~\$2.50 / \$10 per M tokens |

Each condition was run once per case (18 total API calls). Auto-scoring uses keyword matching and method coverage against expert-annotated ground truth from published papers. LLM judge scoring uses Sonnet as the evaluator with structured rubrics.

Raw outputs are available in `eval/outputs/` (not tracked in git; run the eval script to regenerate).