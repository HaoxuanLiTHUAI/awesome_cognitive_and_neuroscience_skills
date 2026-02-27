# Skill Generation Prompt — JSON to SKILL.md

You are an expert technical writer for cognitive science research methods. Your task is to transform a structured JSON extraction into a valid SKILL.md file that conforms to the project's conventions.

---

## Input

You will receive a JSON object describing one extracted skill with fields such as:
- `skill_name`, `display_name`, `description`, `domain`
- `paradigm_design`, `data_acquisition`, `processing_pipeline`, `analysis_methods`, `stimulus_materials`, `computational_models`, `methodological_recommendations`
- `key_parameters` (each with name, value, citation, rationale)
- `missing_information`, `deviations_from_convention`
- `papers`

---

## Output Requirements

Generate a complete SKILL.md file that adheres to these conventions:

### 1. YAML Frontmatter (required)

```yaml
---
name: "<display_name from JSON>"
description: "<description from JSON>"
domain: "<domain from JSON>"
version: "1.0.0"
papers:
  - "<paper citation 1>"
  - "<paper citation 2>"
---
```

### 2. Markdown Body Structure

Follow this structure (include only sections that have content):

```markdown
# <Display Name>

## Purpose

<1-2 paragraphs: What domain knowledge this skill encodes and when a researcher would use it.>

## When to Use This Skill

<Bullet list of concrete use cases.>

## <Main Content Sections>

<Organize by the categories present in the JSON. Use the natural section names below.>
```

**Section mapping from JSON categories**:

| JSON field | Section heading |
|---|---|
| `paradigm_design` | Paradigm Design |
| `data_acquisition` | Data Acquisition Parameters |
| `processing_pipeline` | Processing Pipeline |
| `analysis_methods` | Analysis Methods |
| `stimulus_materials` | Stimulus Materials |
| `computational_models` | Computational Model |
| `methodological_recommendations` | Methodological Recommendations |

### 3. Parameter Presentation

Every numerical parameter MUST include its citation. Use this format:

```markdown
- **Parameter name**: value (Citation, Year, page/table)
```

For parameter tables:

```markdown
| Parameter | Value | Source |
|-----------|-------|--------|
| High-pass filter | **0.1 Hz** | Luck, 2014, Ch. 5 |
```

When a rationale is available, include it inline:

```markdown
- **Epoch time window**: -200 to 800 ms (Author, Year) — chosen to capture the full N400 component while avoiding overlap with subsequent trials
```

### 4. Missing Information Section

If `missing_information` is non-empty, include:

```markdown
## Missing Information

The source text does not report the following standard parameters:

- <item 1>
- <item 2>

These must be determined empirically or sourced from supplementary materials.
```

### 5. Deviations from Convention

If `deviations_from_convention` is non-empty, include:

```markdown
## Deviations from Convention

- <deviation description and authors' justification>
```

### 6. Quality Constraints

- **Line limit**: The SKILL.md must be under 500 lines. If content exceeds this, note which sections should be moved to `references/` files and add explicit cross-references (e.g., "See `references/parameter-table.yaml` for the full list").
- **Domain specificity**: Every item must pass the litmus test: "Would a competent programmer who has never taken a cognitive science course get this wrong?" Remove anything that fails.
- **No generic advice**: Do not include general programming tips, obvious research methodology, or tool-specific tutorials without domain judgment.
- **Exact numbers**: Never round or approximate. Use exact figures from the JSON.

---

## Extracted Skill JSON

{skill_json}
