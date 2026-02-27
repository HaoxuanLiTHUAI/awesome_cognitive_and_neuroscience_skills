# Batch Extraction Pipeline

Automated 5-stage pipeline for extracting domain-specific cognitive science skills from papers and textbook transcripts. It reads `.txt` or `.md` files from an input directory, runs each through five processing stages, and generates standard `SKILL.md` files in the project's skill directory format.

---

## Quick Start

```bash
# 1. Install dependencies
cd pipeline/
pip install -r requirements.txt

# 2. Create your config file
cp config.example.yaml config.yaml

# 3. Set your API key (edit config.yaml or export as environment variable)
export ANTHROPIC_API_KEY="sk-ant-..."
# or for OpenAI:
# export OPENAI_API_KEY="sk-..."

# 4. Prepare input directory with paper transcripts
mkdir -p input/
# Place .txt or .md files in input/

# 5. Dry-run to verify setup
python extract.py --config config.yaml --dry-run

# 6. Run the extraction
python extract.py --config config.yaml
```

---

## Prerequisites

- Python 3.10+
- An API key for one of the supported LLM providers:
  - **Anthropic** (recommended): Claude Sonnet 4 or Claude Opus 4
  - **OpenAI**: GPT-4o or GPT-4 Turbo

Install Python dependencies:

```bash
pip install -r requirements.txt
```

This installs:
- `openai` -- OpenAI API client
- `anthropic` -- Anthropic API client
- `pyyaml` -- YAML configuration parsing

---

## Configuration

Copy the example configuration and edit it:

```bash
cp config.example.yaml config.yaml
```

### Key settings

| Setting | Description | Default |
|---------|-------------|---------|
| `llm.provider` | LLM provider (`"openai"` or `"anthropic"`) | `"anthropic"` |
| `llm.api_key` | API key (or set via environment variable) | `""` |
| `llm.model` | Model identifier | `"claude-sonnet-4-20250514"` |
| `llm.max_tokens` | Max tokens per LLM response | `4096` |
| `llm.temperature` | Sampling temperature | `0.2` |
| `paths.input_dir` | Directory containing source text files | `"./input"` |
| `paths.output_dir` | Directory where skills will be generated | `"./skills"` |
| `paths.quarantine_dir` | Directory for skills that fail hallucination check | `"./quarantine"` |
| `batch.concurrency` | Number of parallel API calls | `3` |
| `batch.max_retries` | Retry count for transient API errors | `3` |
| `batch.max_files` | Limit number of files processed (0 = all) | `0` |
| `extraction.min_file_length` | Skip files shorter than this (chars) | `500` |
| `extraction.max_chunk_size` | Split files larger than this (chars) | `100000` |
| `extraction.skip_existing` | Skip if skill directory already exists | `true` |
| `segmentation.enabled` | Enable Stage 1 segmentation | `true` |
| `segmentation.char_threshold` | Text length triggering segmentation | `15000` |
| `suitability.enabled` | Enable Stage 2 suitability filtering | `true` |
| `suitability.strict` | Strict mode for borderline chunks | `true` |
| `hallucination_check.enabled` | Enable Stage 5 hallucination verification | `true` |
| `hallucination_check.quarantine_on_fail` | Move failed skills to quarantine | `true` |

### API key configuration

You can provide the API key either in `config.yaml` or via an environment variable:

```bash
# Anthropic
export ANTHROPIC_API_KEY="sk-ant-..."

# OpenAI
export OPENAI_API_KEY="sk-..."
```

Environment variables take precedence over the config file.

### Using a local or proxy LLM endpoint

Set `llm.base_url` to your local endpoint:

```yaml
llm:
  provider: "openai"  # Use OpenAI-compatible API format
  base_url: "http://localhost:8000/v1"
  model: "my-local-model"
  api_key: "not-needed"
```

---

## Usage

### Basic extraction

```bash
python extract.py --config config.yaml
```

### Dry-run (no API calls)

Test file discovery and validation without spending API credits:

```bash
python extract.py --config config.yaml --dry-run
```

### Override paths from the command line

```bash
python extract.py --config config.yaml --input ./my-papers --output ../skills
```

### Save the extraction report to a file

```bash
python extract.py --config config.yaml --report extraction-report.md
```

### Full options

```
usage: extract.py [-h] [--config CONFIG] [--input INPUT] [--output OUTPUT]
                  [--dry-run] [--report REPORT]

  --config CONFIG   Path to config.yaml (default: pipeline/config.yaml)
  --input INPUT     Override input directory from config
  --output OUTPUT   Override output directory from config
  --dry-run         Scan files without calling the LLM API
  --report REPORT   Path to write the extraction report
```

---

## How It Works: 5-Stage Architecture

The pipeline processes each source file through five stages:

```
Source Text -> Stage 1 -> Stage 2 -> Stage 3 -> Stage 4 -> Stage 5 -> Output
              Segment   Suitability  Extract    Assemble   Hallucination
                         Filter                             Check
```

### Stage 1: Summarize & Segment (概括分段)

**Purpose**: For large texts (longer than `segmentation.char_threshold`), identify logical units and split into candidate chunks.

**How it works**:
1. If the text exceeds the character threshold (default: 15,000 chars), send it to the LLM with the segmentation prompt.
2. The LLM identifies logical boundaries: section breaks, topic shifts, new experiments, methodological transitions.
3. Each chunk becomes a self-contained unit representing one experiment, one method, or one paradigm.
4. Short texts (single paper length) skip this stage and pass through as a single chunk.

**Output**: JSON array of chunks, each with `chunk_id`, `summary`, `text`, and `estimated_type` (experimental/methods/modeling/review/narrative).

**Prompt**: `prompts/segmentation-prompt.md`

### Stage 2: Suitability Review (适合性筛选)

**Purpose**: Filter chunks to keep only those containing actionable, reproducible methodological content.

**How it works**:
1. Each chunk is evaluated against strict suitability criteria.
2. **Suitable**: experimental paradigm/design, data processing pipeline, analysis method with steps, specific parameters/settings, stimulus construction norms.
3. **Not suitable**: storytelling/narrative, knowledge overview/definitions, theoretical debate, background introduction, terminology explanation.
4. Strict mode (default): borderline chunks are marked NOT suitable.

**Output**: Filtered list of suitable chunks with `skill_type_hint` labels.

**Prompt**: `prompts/suitability-prompt.md`

### Stage 3: Atomic Extraction (原子提取)

**Purpose**: Extract structured skill data from each suitable chunk.

**How it works**:
1. Each suitable chunk is sent to the LLM with the extraction prompt.
2. The LLM returns structured JSON with all extractable research skills, organized by category:
   - **Paradigm Design** -- trial structure, timing, conditions, counterbalancing
   - **Data Acquisition** -- EEG, fMRI, eye-tracking, behavioral parameters
   - **Processing Pipeline** -- preprocessing steps with exact parameters
   - **Analysis Methods** -- statistical tests, corrections, effect sizes
   - **Stimulus Materials** -- materials, controlled variables, presentation parameters
   - **Computational Models** -- equations, parameters, fitting methods
   - **Methodological Recommendations** -- best practices, decision trees, meta-analytic benchmarks
3. Every extracted parameter includes a `source_location` field pointing to the specific location in the original text (section, paragraph, table, figure) for downstream verification.

**Prompt**: `prompts/extraction-prompt.md`

### Stage 4: Hierarchical Assembly (层级组装)

**Purpose**: Organize extracted skills into a hierarchical directory structure.

**How it works**:
1. After all atomic skills are extracted from a source, generate SKILL.md for each.
2. If only 1 skill is extracted: flat structure (`skills/<skill-name>/SKILL.md`).
3. If multiple skills are extracted from the same source: create a parent skill with sub-skills:
   ```
   skills/
     parent-skill/
       SKILL.md           # Overview + links to sub-skills
       sub-skills/
         atomic-skill-1/
           SKILL.md
         atomic-skill-2/
           SKILL.md
   ```
4. The parent SKILL.md serves as an overview and navigation hub.

### Stage 5: Hallucination Check (幻觉检查)

**Purpose**: Verify that every generated SKILL.md accurately reflects the original source text.

**How it works**:
1. For each generated skill, the LLM reads both the SKILL.md and the original source text.
2. Every numerical parameter, citation, and factual claim is verified against the source.
3. The check classifies issues by type: `not_found`, `value_mismatch`, `location_wrong`, `context_distortion`, `unit_error`, `incomplete`.
4. A skill passes if it has ZERO high-severity flags.
5. Failed skills can be automatically quarantined (moved to `quarantine_dir`).

**Key assumption**: The source text is treated as ground truth. The check verifies the SKILL correctly reflects the source, not whether the source itself is correct.

**Output**: JSON with `verified_count`, `flagged` list, `pass` boolean, and `summary`.

**Prompt**: `prompts/hallucination-check-prompt.md`

### Reporting

After all files are processed, the pipeline generates a summary report with:
- Total files processed, succeeded, skipped, and failed
- **Segmentation stats**: chunks found per file
- **Suitability filtering stats**: pass rate across all chunks
- **Hallucination check stats**: pass rate, common issue types
- List of generated skills per source file
- Error details for any failures
- Total processing time

---

## Input Format

Place your source text files in the input directory. Supported formats:
- `.txt` -- Plain text transcripts
- `.md` -- Markdown-formatted transcripts

Each file should contain the full text of a single paper or textbook chapter. The pipeline works best with:
- Complete methods sections
- Full paper text (abstract through references)
- Textbook chapters covering specific methodologies

Files shorter than `min_file_length` (default: 500 characters) are automatically skipped.

---

## Output Structure

Generated skills follow the project's directory convention:

### Single skill per source (flat):

```
skills/
  <skill-name>/
    SKILL.md            # Core skill content (<500 lines)
```

### Multiple skills per source (hierarchical):

```
skills/
  <source-name>/
    SKILL.md            # Parent: overview + navigation
    sub-skills/
      <skill-1>/
        SKILL.md
      <skill-2>/
        SKILL.md
```

### Quarantined skills (failed hallucination check):

```
quarantine/
  <skill-name>/
    SKILL.md            # Failed verification — needs manual review
```

Skill directory names use kebab-case and are descriptive of the specific method (not the paper title). For example:
- `eeg-mismatch-negativity-paradigm/`
- `drift-diffusion-model-fitting/`
- `fmri-glm-analysis/`

---

## Error Handling

The pipeline is designed for robustness in batch processing:

- **API rate limits**: Automatic exponential backoff with configurable retry count.
- **Malformed JSON responses**: Multiple JSON extraction strategies (code fences, brace matching).
- **Partial failures**: Individual file errors do not stop the batch. Errors are logged and included in the report.
- **Large files**: Automatic chunking at paragraph boundaries when files exceed `max_chunk_size`.
- **Existing skills**: Set `skip_existing: true` to avoid regenerating skills that already exist.
- **Concurrency control**: Bounded parallelism via `batch.concurrency` to stay within API rate limits.
- **Hallucination failures**: Failed skills are quarantined, not deleted. Manual review is possible.

---

## Customizing Prompts

The pipeline uses five prompt templates stored as editable markdown files:

| Prompt File | Stage | Placeholder |
|---|---|---|
| `prompts/segmentation-prompt.md` | Stage 1: Segment | `{source_text}` |
| `prompts/suitability-prompt.md` | Stage 2: Suitability | `{chunks_json}` |
| `prompts/extraction-prompt.md` | Stage 3: Extract | `{source_text}` |
| `prompts/skill-generation-prompt.md` | Stage 3/4: Generate | `{skill_json}` |
| `prompts/hallucination-check-prompt.md` | Stage 5: Verify | `{skill_md}`, `{source_text}` |

You can edit these prompts to:
- Adjust extraction priorities for your specific use case
- Add or remove extraction categories
- Change the output format or style of generated skills
- Tune suitability criteria strictness
- Adjust hallucination check severity levels

---

## Troubleshooting

**"No API key configured"**
Set your API key in `config.yaml` or export the corresponding environment variable.

**"Input directory does not exist"**
Create the input directory and add source files, or use `--input` to point to an existing directory.

**"No source files found"**
Check that your input directory contains files with extensions listed in `batch.file_extensions` (default: `.txt`, `.md`).

**"Could not parse JSON from LLM response"**
The LLM returned invalid JSON. This is more common with smaller models. Try a larger model or lower temperature.

**"No chunks passed suitability review"**
All text chunks were deemed not suitable for skill extraction. This can happen with purely theoretical or narrative texts. Check the debug logs for specific rejection reasons or disable suitability filtering with `suitability.enabled: false`.

**"Skill failed hallucination check"**
The generated skill contained claims that could not be verified against the source. Check the quarantine directory for the flagged skill and the report for specific issues. Common causes: LLM hallucinated a parameter value, wrong source location reference, or truncated context.

**Skill exceeds 500 lines**
The pipeline will log a warning. Edit the generated SKILL.md to move supplementary content to a `references/` subdirectory.
