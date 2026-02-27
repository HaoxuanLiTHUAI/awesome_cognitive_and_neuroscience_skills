# Segmentation Prompt — Stage 1: Summarize & Segment (概括分段)

You are an expert cognitive scientist performing **automated text segmentation** of academic source material. Your goal is to divide the provided text into logical, self-contained units — each representing ONE cohesive methodological topic.

---

## Your Task

Read the FULL text provided below, identify logical boundaries, and split it into **candidate chunks**. Each chunk should represent exactly ONE of the following:

- One experiment or study
- One method or technique
- One paradigm or protocol
- One data processing pipeline
- One computational model
- One coherent set of methodological recommendations

---

## How to Identify Boundaries

Look for these signals that indicate a new logical unit begins:

1. **Section headings** — "Experiment 1", "Experiment 2", "Method A", "Study 2", "General Discussion"
2. **Topic shifts** — The text transitions from one method/paradigm to a qualitatively different one
3. **New experiment introductions** — Phrases like "In a second experiment...", "We next examined...", "Study 2 tested..."
4. **Methodological transitions** — Shift from describing data acquisition to describing a distinct analysis technique
5. **Chapter/section breaks** — Explicit numbering or formatting changes

---

## Rules

1. **ONE cohesive unit per chunk** — Do NOT lump unrelated experiments or methods into one chunk. A chunk should be independently understandable as a single methodological unit.
2. **Preserve full context** — Each chunk must include enough context to be understood on its own. Include relevant setup/introduction text that is necessary to understand the method described.
3. **Do not split mid-method** — If a method description spans multiple paragraphs, keep them together. Never split in the middle of a parameter list, processing pipeline, or experimental procedure.
4. **Include shared methods once** — If multiple experiments share a common methods section, include the shared methods text in the first chunk and add a note in subsequent chunks referencing it.
5. **Keep text verbatim** — The `text` field must contain the EXACT original text, not a paraphrase.

---

## Estimated Types

Classify each chunk as one of:

| Type | Description |
|------|-------------|
| `experimental` | Reports an original experiment with participants and data |
| `methods` | Introduces, validates, or describes an analysis technique, pipeline, or tool |
| `modeling` | Constructs, fits, or compares computational/mathematical models |
| `review` | Synthesizes literature, discusses theoretical frameworks, meta-analysis |
| `narrative` | Storytelling, historical context, general introduction, or motivation |

---

## Output Format

Return a JSON object with the following structure:

```json
{
  "total_chunks": 3,
  "chunks": [
    {
      "chunk_id": "0",
      "summary": "One-sentence summary of what this chunk covers methodologically",
      "text": "The full verbatim text of this chunk...",
      "estimated_type": "experimental|methods|modeling|review|narrative",
      "start_indicator": "The heading or first sentence that marks the beginning of this unit",
      "end_indicator": "The heading or last sentence that marks the end of this unit"
    }
  ]
}
```

**Rules for output**:
- `chunk_id` is a zero-indexed string ("0", "1", "2", ...).
- `summary` must be a single sentence describing the methodological content, NOT just a section title.
- `text` must be the EXACT verbatim text from the source. Do not paraphrase or summarize.
- If the entire text is one cohesive unit (single experiment, single method), return it as a single chunk.

---

## Source Text

{source_text}
