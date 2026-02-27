#!/usr/bin/env python3
"""
Batch Knowledge Extraction Pipeline for Cognitive Science Skills.

5-stage architecture:
  Stage 1: Summarize & Segment (概括分段) — split large texts into logical chunks
  Stage 2: Suitability Review (适合性筛选) — filter chunks for actionable content
  Stage 3: Atomic Extraction (原子提取) — extract skills from suitable chunks
  Stage 4: Hierarchical Assembly (层级组装) — organize skills into hierarchy
  Stage 5: Hallucination Check (幻觉检查) — verify skills against source text

Usage:
    python extract.py --config config.yaml
    python extract.py --config config.yaml --dry-run
    python extract.py --config config.yaml --input ./papers --output ./skills
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import shutil
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = SCRIPT_DIR / "config.yaml"
EXTRACTION_PROMPT_PATH = SCRIPT_DIR / "prompts" / "extraction-prompt.md"
SKILL_GEN_PROMPT_PATH = SCRIPT_DIR / "prompts" / "skill-generation-prompt.md"
SEGMENTATION_PROMPT_PATH = SCRIPT_DIR / "prompts" / "segmentation-prompt.md"
SUITABILITY_PROMPT_PATH = SCRIPT_DIR / "prompts" / "suitability-prompt.md"
HALLUCINATION_CHECK_PROMPT_PATH = SCRIPT_DIR / "prompts" / "hallucination-check-prompt.md"

logger = logging.getLogger("pipeline")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class LLMConfig:
    provider: str = "anthropic"
    api_key: str = ""
    model: str = "claude-sonnet-4-20250514"
    base_url: str = ""
    max_tokens: int = 4096
    temperature: float = 0.2


@dataclass
class PathsConfig:
    input_dir: str = "./input"
    output_dir: str = "./skills"
    quarantine_dir: str = "./quarantine"


@dataclass
class BatchConfig:
    concurrency: int = 3
    max_retries: int = 3
    retry_base_delay: float = 2.0
    max_files: int = 0
    file_extensions: list[str] = field(default_factory=lambda: [".txt", ".md"])


@dataclass
class ExtractionConfig:
    min_file_length: int = 500
    max_chunk_size: int = 100_000
    skip_existing: bool = True


@dataclass
class SegmentationConfig:
    """Settings for Stage 1: Summarize & Segment."""
    enabled: bool = True
    # Character threshold: texts shorter than this skip segmentation
    char_threshold: int = 15_000
    # Max tokens for the segmentation LLM call (needs room for full text + output)
    max_tokens: int = 8192


@dataclass
class SuitabilityConfig:
    """Settings for Stage 2: Suitability Review."""
    enabled: bool = True
    # Strict mode: when True, borderline chunks are marked NOT suitable
    strict: bool = True
    max_tokens: int = 4096


@dataclass
class HallucinationCheckConfig:
    """Settings for Stage 5: Hallucination Check."""
    enabled: bool = True
    # Move failed skills to quarantine directory instead of deleting
    quarantine_on_fail: bool = True
    max_tokens: int = 4096


@dataclass
class LoggingConfig:
    level: str = "INFO"
    log_file: str = ""


@dataclass
class PipelineConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    batch: BatchConfig = field(default_factory=BatchConfig)
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)
    segmentation: SegmentationConfig = field(default_factory=SegmentationConfig)
    suitability: SuitabilityConfig = field(default_factory=SuitabilityConfig)
    hallucination_check: HallucinationCheckConfig = field(default_factory=HallucinationCheckConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


def load_config(path: Path, cli_overrides: dict[str, Any] | None = None) -> PipelineConfig:
    """Load YAML config file and apply CLI overrides."""
    cfg = PipelineConfig()
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}

        # LLM
        llm = raw.get("llm", {})
        for k in ("provider", "api_key", "model", "base_url", "max_tokens", "temperature"):
            if k in llm:
                setattr(cfg.llm, k, llm[k])

        # Paths
        paths = raw.get("paths", {})
        for k in ("input_dir", "output_dir", "quarantine_dir"):
            if k in paths:
                setattr(cfg.paths, k, paths[k])

        # Batch
        batch = raw.get("batch", {})
        for k in ("concurrency", "max_retries", "retry_base_delay", "max_files", "file_extensions"):
            if k in batch:
                setattr(cfg.batch, k, batch[k])

        # Extraction
        extraction = raw.get("extraction", {})
        for k in ("min_file_length", "max_chunk_size", "skip_existing"):
            if k in extraction:
                setattr(cfg.extraction, k, extraction[k])

        # Segmentation (Stage 1)
        seg = raw.get("segmentation", {})
        for k in ("enabled", "char_threshold", "max_tokens"):
            if k in seg:
                setattr(cfg.segmentation, k, seg[k])

        # Suitability (Stage 2)
        suit = raw.get("suitability", {})
        for k in ("enabled", "strict", "max_tokens"):
            if k in suit:
                setattr(cfg.suitability, k, suit[k])

        # Hallucination check (Stage 5)
        hal = raw.get("hallucination_check", {})
        for k in ("enabled", "quarantine_on_fail", "max_tokens"):
            if k in hal:
                setattr(cfg.hallucination_check, k, hal[k])

        # Logging
        log = raw.get("logging", {})
        for k in ("level", "log_file"):
            if k in log:
                setattr(cfg.logging, k, log[k])
    else:
        logger.warning("Config file %s not found — using defaults.", path)

    # Apply CLI overrides
    if cli_overrides:
        if cli_overrides.get("input"):
            cfg.paths.input_dir = cli_overrides["input"]
        if cli_overrides.get("output"):
            cfg.paths.output_dir = cli_overrides["output"]

    # Resolve API key from env if not set in config
    if not cfg.llm.api_key:
        env_var = "OPENAI_API_KEY" if cfg.llm.provider == "openai" else "ANTHROPIC_API_KEY"
        cfg.llm.api_key = os.environ.get(env_var, "")

    return cfg


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging(log_cfg: LoggingConfig) -> None:
    level = getattr(logging, log_cfg.level.upper(), logging.INFO)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_cfg.log_file:
        handlers.append(logging.FileHandler(log_cfg.log_file, encoding="utf-8"))
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------

def load_prompt(path: Path) -> str:
    """Read a prompt template from disk."""
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# LLM Clients
# ---------------------------------------------------------------------------

class LLMClient:
    """Unified interface for OpenAI and Anthropic APIs."""

    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        self._client: Any = None

    def _init_client(self) -> None:
        if self._client is not None:
            return

        if self.cfg.provider == "openai":
            try:
                from openai import OpenAI
            except ImportError:
                raise ImportError("openai package not installed. Run: pip install openai")
            kwargs: dict[str, Any] = {"api_key": self.cfg.api_key}
            if self.cfg.base_url:
                kwargs["base_url"] = self.cfg.base_url
            self._client = OpenAI(**kwargs)

        elif self.cfg.provider == "anthropic":
            try:
                import anthropic
            except ImportError:
                raise ImportError("anthropic package not installed. Run: pip install anthropic")
            kwargs = {"api_key": self.cfg.api_key}
            if self.cfg.base_url:
                kwargs["base_url"] = self.cfg.base_url
            self._client = anthropic.Anthropic(**kwargs)

        else:
            raise ValueError(f"Unsupported LLM provider: {self.cfg.provider}")

    def call(self, system_prompt: str, user_prompt: str, max_tokens: int | None = None) -> str:
        """Send a prompt to the configured LLM and return the response text."""
        self._init_client()
        tokens = max_tokens or self.cfg.max_tokens

        if self.cfg.provider == "openai":
            response = self._client.chat.completions.create(
                model=self.cfg.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=tokens,
                temperature=self.cfg.temperature,
            )
            return response.choices[0].message.content or ""

        elif self.cfg.provider == "anthropic":
            response = self._client.messages.create(
                model=self.cfg.model,
                max_tokens=tokens,
                temperature=self.cfg.temperature,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt},
                ],
            )
            return response.content[0].text if response.content else ""

        raise RuntimeError("Unreachable")


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def discover_source_files(cfg: PipelineConfig) -> list[Path]:
    """Find all source text files in the input directory."""
    input_dir = Path(cfg.paths.input_dir).resolve()
    if not input_dir.is_dir():
        logger.error("Input directory does not exist: %s", input_dir)
        return []

    extensions = set(cfg.batch.file_extensions)
    files: list[Path] = []
    for p in sorted(input_dir.iterdir()):
        if p.is_file() and p.suffix.lower() in extensions:
            files.append(p)

    if cfg.batch.max_files > 0:
        files = files[: cfg.batch.max_files]

    logger.info("Discovered %d source file(s) in %s", len(files), input_dir)
    return files


# ---------------------------------------------------------------------------
# Text chunking (legacy helper, used as fallback)
# ---------------------------------------------------------------------------

def chunk_text(text: str, max_size: int) -> list[str]:
    """Split text into chunks respecting paragraph boundaries."""
    if len(text) <= max_size:
        return [text]

    chunks: list[str] = []
    paragraphs = text.split("\n\n")
    current_chunk = ""

    for para in paragraphs:
        if len(current_chunk) + len(para) + 2 > max_size:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = para
        else:
            current_chunk = current_chunk + "\n\n" + para if current_chunk else para

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks if chunks else [text[:max_size]]


# ---------------------------------------------------------------------------
# JSON extraction from LLM response
# ---------------------------------------------------------------------------

def extract_json_from_response(response: str) -> dict[str, Any]:
    """Parse JSON from LLM response, handling markdown code fences."""
    text = response.strip()

    # Try to find JSON in code fences
    fence_pattern = r"```(?:json)?\s*\n?(.*?)\n?\s*```"
    matches = re.findall(fence_pattern, text, re.DOTALL)
    if matches:
        # Use the longest match (most likely the full JSON)
        text = max(matches, key=len)

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find a top-level JSON object
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
        try:
            return json.loads(text[brace_start : brace_end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse JSON from LLM response (first 200 chars): {response[:200]}")


# ---------------------------------------------------------------------------
# Utility: safe kebab-case name
# ---------------------------------------------------------------------------

def to_safe_name(name: str) -> str:
    """Convert a skill name to a filesystem-safe kebab-case string."""
    safe = re.sub(r"[^a-z0-9-]", "-", name.lower())
    safe = re.sub(r"-+", "-", safe).strip("-")
    return safe or "unnamed-skill"


# ---------------------------------------------------------------------------
# Stage 1: Summarize & Segment (概括分段)
# ---------------------------------------------------------------------------

def step_segment(
    client: LLMClient,
    source_text: str,
    segmentation_prompt_template: str,
    max_retries: int,
    retry_base_delay: float,
    max_tokens: int = 8192,
) -> list[dict[str, Any]]:
    """Stage 1: Split large text into logical chunks via LLM.

    Returns a list of chunk dicts, each with:
        chunk_id, summary, text, estimated_type
    """
    prompt = segmentation_prompt_template.replace("{source_text}", source_text)

    system = (
        "You are an expert cognitive scientist performing automated text segmentation. "
        "Return ONLY valid JSON — no commentary outside the JSON block."
    )

    for attempt in range(1, max_retries + 1):
        try:
            raw_response = client.call(system, prompt, max_tokens=max_tokens)
            result = extract_json_from_response(raw_response)
            chunks = result.get("chunks", [])
            if not chunks:
                logger.warning("Segmentation returned no chunks; treating entire text as one chunk.")
                return [{"chunk_id": "0", "summary": "Full text (single unit)", "text": source_text, "estimated_type": "experimental"}]
            logger.info("Stage 1 (Segment): identified %d chunk(s).", len(chunks))
            return chunks
        except (ValueError, json.JSONDecodeError) as exc:
            logger.warning("Segmentation attempt %d/%d — JSON parse error: %s", attempt, max_retries, exc)
            if attempt == max_retries:
                raise
        except Exception as exc:
            logger.warning("Segmentation attempt %d/%d — API error: %s", attempt, max_retries, exc)
            if attempt == max_retries:
                raise
            time.sleep(retry_base_delay * (2 ** (attempt - 1)))

    raise RuntimeError("Unreachable")


# ---------------------------------------------------------------------------
# Stage 2: Suitability Review (适合性筛选)
# ---------------------------------------------------------------------------

def step_suitability_filter(
    client: LLMClient,
    chunks: list[dict[str, Any]],
    suitability_prompt_template: str,
    max_retries: int,
    retry_base_delay: float,
    max_tokens: int = 4096,
) -> list[dict[str, Any]]:
    """Stage 2: Filter chunks for suitability. Returns only suitable chunks.

    Each returned chunk has an added 'skill_type_hint' field.
    """
    # Build a JSON summary of chunks (without full text, to save tokens in evaluation)
    chunks_for_eval = []
    for c in chunks:
        chunks_for_eval.append({
            "chunk_id": c.get("chunk_id", "?"),
            "summary": c.get("summary", ""),
            "estimated_type": c.get("estimated_type", "unknown"),
            "text_preview": c.get("text", "")[:2000],  # first 2000 chars for evaluation
            "text_length": len(c.get("text", "")),
        })

    chunks_json_str = json.dumps(chunks_for_eval, indent=2, ensure_ascii=False)
    prompt = suitability_prompt_template.replace("{chunks_json}", chunks_json_str)

    system = (
        "You are an expert cognitive scientist evaluating text chunks for skill extraction suitability. "
        "Return ONLY valid JSON — no commentary outside the JSON block."
    )

    for attempt in range(1, max_retries + 1):
        try:
            raw_response = client.call(system, prompt, max_tokens=max_tokens)
            result = extract_json_from_response(raw_response)
            evaluations = result.get("evaluations", [])

            # Build a lookup of suitable chunk_ids
            suitable_ids: dict[str, str | None] = {}
            for ev in evaluations:
                if ev.get("suitable"):
                    suitable_ids[str(ev["chunk_id"])] = ev.get("skill_type_hint")

            # Filter original chunks (keeping full text)
            suitable_chunks = []
            for c in chunks:
                cid = str(c.get("chunk_id", "?"))
                if cid in suitable_ids:
                    c["skill_type_hint"] = suitable_ids[cid]
                    suitable_chunks.append(c)

            logger.info(
                "Stage 2 (Suitability): %d/%d chunks passed filter.",
                len(suitable_chunks),
                len(chunks),
            )

            # Log reasons for rejected chunks
            for ev in evaluations:
                if not ev.get("suitable"):
                    logger.debug(
                        "  Chunk %s rejected: %s",
                        ev.get("chunk_id"),
                        ev.get("reason", "no reason"),
                    )

            return suitable_chunks
        except (ValueError, json.JSONDecodeError) as exc:
            logger.warning("Suitability attempt %d/%d — JSON parse error: %s", attempt, max_retries, exc)
            if attempt == max_retries:
                raise
        except Exception as exc:
            logger.warning("Suitability attempt %d/%d — API error: %s", attempt, max_retries, exc)
            if attempt == max_retries:
                raise
            time.sleep(retry_base_delay * (2 ** (attempt - 1)))

    raise RuntimeError("Unreachable")


# ---------------------------------------------------------------------------
# Stage 3: Atomic Extraction (原子提取) — existing step, updated signature
# ---------------------------------------------------------------------------

def step_extract(
    client: LLMClient,
    source_text: str,
    extraction_prompt_template: str,
    max_retries: int,
    retry_base_delay: float,
) -> dict[str, Any]:
    """Stage 3: Call LLM to extract skills from source text. Returns parsed JSON."""
    prompt = extraction_prompt_template.replace("{source_text}", source_text)

    system = (
        "You are an expert cognitive scientist performing automated knowledge extraction. "
        "Return ONLY valid JSON — no commentary outside the JSON block."
    )

    for attempt in range(1, max_retries + 1):
        try:
            raw_response = client.call(system, prompt)
            return extract_json_from_response(raw_response)
        except (ValueError, json.JSONDecodeError) as exc:
            logger.warning(
                "Extraction attempt %d/%d — JSON parse error: %s", attempt, max_retries, exc
            )
            if attempt == max_retries:
                raise
        except Exception as exc:
            logger.warning(
                "Extraction attempt %d/%d — API error: %s", attempt, max_retries, exc
            )
            if attempt == max_retries:
                raise
            time.sleep(retry_base_delay * (2 ** (attempt - 1)))

    raise RuntimeError("Unreachable")


def step_generate_skill(
    client: LLMClient,
    skill_json: dict[str, Any],
    generation_prompt_template: str,
    max_retries: int,
    retry_base_delay: float,
) -> str:
    """Call LLM to generate SKILL.md content from extracted JSON."""
    skill_json_str = json.dumps(skill_json, indent=2, ensure_ascii=False)
    prompt = generation_prompt_template.replace("{skill_json}", skill_json_str)

    system = (
        "You are an expert technical writer for cognitive science research methods. "
        "Generate a complete, valid SKILL.md file. Return ONLY the markdown content — "
        "start with the YAML frontmatter (---) and end with the last section. "
        "No commentary outside the markdown."
    )

    for attempt in range(1, max_retries + 1):
        try:
            response = client.call(system, prompt)
            # Strip any code fences that might wrap the markdown
            text = response.strip()
            if text.startswith("```"):
                # Remove opening fence
                first_newline = text.find("\n")
                text = text[first_newline + 1 :] if first_newline != -1 else text[3:]
                # Remove closing fence
                if text.rstrip().endswith("```"):
                    text = text.rstrip()[:-3].rstrip()
            return text
        except Exception as exc:
            logger.warning(
                "Skill generation attempt %d/%d — error: %s", attempt, max_retries, exc
            )
            if attempt == max_retries:
                raise
            time.sleep(retry_base_delay * (2 ** (attempt - 1)))

    raise RuntimeError("Unreachable")


# ---------------------------------------------------------------------------
# Stage 4: Hierarchical Assembly (层级组装)
# ---------------------------------------------------------------------------

def write_skill(output_dir: Path, skill_name: str, skill_md: str, sub_dir: str | None = None) -> Path:
    """Write SKILL.md to the correct directory structure.

    If sub_dir is provided, the skill is placed at:
        output_dir / sub_dir / skill_name / SKILL.md
    Otherwise:
        output_dir / skill_name / SKILL.md
    """
    safe_name = to_safe_name(skill_name)

    if sub_dir:
        skill_dir = output_dir / sub_dir / safe_name
    else:
        skill_dir = output_dir / safe_name
    skill_dir.mkdir(parents=True, exist_ok=True)

    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(skill_md, encoding="utf-8")

    # Count lines to check convention
    line_count = skill_md.count("\n") + 1
    if line_count > 500:
        logger.warning(
            "SKILL.md for '%s' is %d lines (exceeds 500-line limit). "
            "Consider moving supplementary content to references/.",
            safe_name,
            line_count,
        )

    return skill_path


def assemble_hierarchy(
    generated: list[tuple[dict[str, Any], str]],
    output_dir: Path,
    source_name: str,
) -> list[str]:
    """Stage 4: Organize generated skills into hierarchical directory structure.

    Args:
        generated: List of (skill_data_dict, skill_md_string) tuples.
        output_dir: Root output directory for skills.
        source_name: Name of the source file (used for parent skill naming).

    Returns:
        List of skill directory names that were written.
    """
    if not generated:
        return []

    written_names: list[str] = []

    # Single skill — no hierarchy needed, flat structure
    if len(generated) == 1:
        skill_data, skill_md = generated[0]
        skill_name = skill_data.get("skill_name", "unnamed-skill")
        path = write_skill(output_dir, skill_name, skill_md)
        written_names.append(str(path.parent.name))
        logger.info("Stage 4 (Assembly): single skill, flat structure -> %s", path)
        return written_names

    # Multiple skills — create parent with sub-skills
    # Derive parent name from common domain or source name
    parent_name = to_safe_name(source_name)

    # Collect sub-skill metadata for parent SKILL.md
    sub_skill_entries: list[dict[str, str]] = []

    for skill_data, skill_md in generated:
        skill_name = skill_data.get("skill_name", "unnamed-skill")
        safe_child = to_safe_name(skill_name)

        # Write to: output_dir / parent_name / sub-skills / safe_child / SKILL.md
        child_dir = output_dir / parent_name / "sub-skills" / safe_child
        child_dir.mkdir(parents=True, exist_ok=True)
        child_path = child_dir / "SKILL.md"
        child_path.write_text(skill_md, encoding="utf-8")

        sub_skill_entries.append({
            "name": skill_data.get("display_name", skill_name),
            "dir_name": safe_child,
            "description": skill_data.get("description", ""),
            "domain": skill_data.get("domain", ""),
        })

        written_names.append(f"{parent_name}/sub-skills/{safe_child}")
        logger.info("Stage 4 (Assembly): wrote sub-skill -> %s", child_path)

    # Generate parent SKILL.md (overview + navigation)
    parent_md = _generate_parent_skill_md(parent_name, sub_skill_entries, source_name)
    parent_dir = output_dir / parent_name
    parent_dir.mkdir(parents=True, exist_ok=True)
    parent_path = parent_dir / "SKILL.md"
    parent_path.write_text(parent_md, encoding="utf-8")
    written_names.insert(0, parent_name)
    logger.info("Stage 4 (Assembly): wrote parent skill -> %s", parent_path)

    return written_names


def _generate_parent_skill_md(
    parent_name: str,
    sub_skills: list[dict[str, str]],
    source_name: str,
) -> str:
    """Generate a parent SKILL.md that serves as overview + navigation."""
    lines = [
        "---",
        f'name: "{parent_name}"',
        f'description: "Parent skill collecting methods extracted from {source_name}"',
        f'domain: "{sub_skills[0]["domain"] if sub_skills else "cognitive-science"}"',
        'version: "1.0.0"',
        "---",
        "",
        f"# {parent_name}",
        "",
        "## Overview",
        "",
        f"This skill collects multiple related methods extracted from **{source_name}**.",
        "Each sub-skill below describes one independently usable method.",
        "",
        "## Sub-Skills",
        "",
    ]

    for entry in sub_skills:
        lines.append(f"### [{entry['name']}](sub-skills/{entry['dir_name']}/SKILL.md)")
        lines.append("")
        if entry["description"]:
            lines.append(f"{entry['description']}")
            lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Stage 5: Hallucination Check (幻觉检查)
# ---------------------------------------------------------------------------

def step_hallucination_check(
    client: LLMClient,
    skill_md: str,
    original_text: str,
    hallucination_prompt_template: str,
    max_retries: int,
    retry_base_delay: float,
    max_tokens: int = 4096,
) -> dict[str, Any]:
    """Stage 5: Verify generated skill against original source text.

    Returns a dict with keys: verified_count, flagged, pass, summary, etc.
    """
    prompt = hallucination_prompt_template.replace("{skill_md}", skill_md)
    prompt = prompt.replace("{source_text}", original_text)

    system = (
        "You are an expert fact-checker for cognitive science methodology. "
        "Verify every numerical claim in the SKILL.md against the original source text. "
        "Return ONLY valid JSON — no commentary outside the JSON block."
    )

    for attempt in range(1, max_retries + 1):
        try:
            raw_response = client.call(system, prompt, max_tokens=max_tokens)
            result = extract_json_from_response(raw_response)
            # Ensure expected fields
            result.setdefault("pass", True)
            result.setdefault("verified_count", 0)
            result.setdefault("flagged_count", len(result.get("flagged", [])))
            result.setdefault("flagged", [])
            result.setdefault("summary", "")
            return result
        except (ValueError, json.JSONDecodeError) as exc:
            logger.warning(
                "Hallucination check attempt %d/%d — JSON parse error: %s",
                attempt, max_retries, exc,
            )
            if attempt == max_retries:
                # On final failure, return a "could not verify" result
                logger.error("Hallucination check failed after %d attempts; marking as unverified.", max_retries)
                return {
                    "pass": False,
                    "verified_count": 0,
                    "flagged_count": 0,
                    "flagged": [],
                    "summary": f"Hallucination check could not be completed: {exc}",
                    "error": True,
                }
        except Exception as exc:
            logger.warning(
                "Hallucination check attempt %d/%d — API error: %s",
                attempt, max_retries, exc,
            )
            if attempt == max_retries:
                logger.error("Hallucination check failed after %d attempts; marking as unverified.", max_retries)
                return {
                    "pass": False,
                    "verified_count": 0,
                    "flagged_count": 0,
                    "flagged": [],
                    "summary": f"Hallucination check could not be completed: {exc}",
                    "error": True,
                }
            time.sleep(retry_base_delay * (2 ** (attempt - 1)))

    raise RuntimeError("Unreachable")


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

@dataclass
class ProcessingResult:
    source_file: str
    status: str  # "success", "skipped", "error"
    skills_generated: list[str] = field(default_factory=list)
    error_message: str = ""
    duration_seconds: float = 0.0
    # Stage 1 stats
    chunks_found: int = 0
    # Stage 2 stats
    chunks_suitable: int = 0
    # Stage 5 stats
    hallucination_check_results: list[dict[str, Any]] = field(default_factory=list)


def generate_report(results: list[ProcessingResult], output_path: Path | None = None) -> str:
    """Generate a summary report of the batch extraction run."""
    success = [r for r in results if r.status == "success"]
    skipped = [r for r in results if r.status == "skipped"]
    errors = [r for r in results if r.status == "error"]

    total_skills = sum(len(r.skills_generated) for r in success)
    total_time = sum(r.duration_seconds for r in results)

    lines = [
        "# Batch Extraction Report",
        "",
        f"**Date**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Files processed**: {len(results)}",
        f"**Successful**: {len(success)}",
        f"**Skipped**: {len(skipped)}",
        f"**Errors**: {len(errors)}",
        f"**Total skills generated**: {total_skills}",
        f"**Total processing time**: {total_time:.1f}s",
        "",
    ]

    # --- Segmentation stats ---
    files_with_chunks = [r for r in results if r.chunks_found > 0]
    if files_with_chunks:
        total_chunks = sum(r.chunks_found for r in files_with_chunks)
        lines.append("## Segmentation (Stage 1)")
        lines.append("")
        lines.append(f"**Total chunks identified**: {total_chunks} (across {len(files_with_chunks)} files)")
        lines.append("")
        for r in files_with_chunks:
            lines.append(f"- **{r.source_file}**: {r.chunks_found} chunk(s)")
        lines.append("")

    # --- Suitability stats ---
    files_with_suitability = [r for r in results if r.chunks_found > 0]
    if files_with_suitability:
        total_suitable = sum(r.chunks_suitable for r in files_with_suitability)
        total_evaluated = sum(r.chunks_found for r in files_with_suitability)
        pass_rate = (total_suitable / total_evaluated * 100) if total_evaluated > 0 else 0
        lines.append("## Suitability Filtering (Stage 2)")
        lines.append("")
        lines.append(f"**Chunks evaluated**: {total_evaluated}")
        lines.append(f"**Chunks passed**: {total_suitable}")
        lines.append(f"**Pass rate**: {pass_rate:.1f}%")
        lines.append("")

    # --- Hallucination check stats ---
    all_checks: list[dict[str, Any]] = []
    for r in results:
        all_checks.extend(r.hallucination_check_results)
    if all_checks:
        passed = sum(1 for c in all_checks if c.get("pass"))
        failed = sum(1 for c in all_checks if not c.get("pass"))
        check_rate = (passed / len(all_checks) * 100) if all_checks else 0
        lines.append("## Hallucination Check (Stage 5)")
        lines.append("")
        lines.append(f"**Skills checked**: {len(all_checks)}")
        lines.append(f"**Passed**: {passed}")
        lines.append(f"**Failed**: {failed}")
        lines.append(f"**Pass rate**: {check_rate:.1f}%")
        lines.append("")

        # Collect common issues
        all_flagged = []
        for c in all_checks:
            all_flagged.extend(c.get("flagged", []))
        if all_flagged:
            issue_counts: dict[str, int] = {}
            for f in all_flagged:
                issue_type = f.get("issue", "unknown")
                issue_counts[issue_type] = issue_counts.get(issue_type, 0) + 1
            lines.append("### Common Issues")
            lines.append("")
            for issue_type, count in sorted(issue_counts.items(), key=lambda x: -x[1]):
                lines.append(f"- **{issue_type}**: {count} occurrence(s)")
            lines.append("")

    # --- Successful extractions ---
    if success:
        lines.append("## Successful Extractions")
        lines.append("")
        for r in success:
            skills_str = ", ".join(r.skills_generated) if r.skills_generated else "(none)"
            lines.append(f"- **{r.source_file}** ({r.duration_seconds:.1f}s) -> {skills_str}")
        lines.append("")

    if skipped:
        lines.append("## Skipped Files")
        lines.append("")
        for r in skipped:
            lines.append(f"- **{r.source_file}**: {r.error_message}")
        lines.append("")

    if errors:
        lines.append("## Errors")
        lines.append("")
        for r in errors:
            lines.append(f"- **{r.source_file}**: {r.error_message}")
        lines.append("")

    report = "\n".join(lines)

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding="utf-8")
        logger.info("Report written to %s", output_path)

    return report


# ---------------------------------------------------------------------------
# Dry-run helpers
# ---------------------------------------------------------------------------

def dry_run_file(source_path: Path, cfg: PipelineConfig) -> ProcessingResult:
    """Simulate processing a single file without API calls."""
    text = source_path.read_text(encoding="utf-8", errors="replace")
    result = ProcessingResult(source_file=source_path.name)

    if len(text) < cfg.extraction.min_file_length:
        result.status = "skipped"
        result.error_message = f"Too short ({len(text)} chars < {cfg.extraction.min_file_length})"
        return result

    output_dir = Path(cfg.paths.output_dir).resolve()
    base_name = source_path.stem.lower()
    safe_name = re.sub(r"[^a-z0-9-]", "-", base_name)
    safe_name = re.sub(r"-+", "-", safe_name).strip("-")

    if cfg.extraction.skip_existing and (output_dir / safe_name / "SKILL.md").exists():
        result.status = "skipped"
        result.error_message = "Skill directory already exists"
        return result

    # Simulate 5-stage pipeline
    will_segment = cfg.segmentation.enabled and len(text) > cfg.segmentation.char_threshold
    text_chunks = chunk_text(text, cfg.extraction.max_chunk_size)

    result.status = "success"
    result.chunks_found = len(text_chunks) if will_segment else 1
    result.chunks_suitable = result.chunks_found  # optimistic in dry-run

    stage_info = []
    if will_segment:
        stage_info.append(f"Stage 1: would segment ({len(text)} chars > {cfg.segmentation.char_threshold} threshold)")
    else:
        stage_info.append("Stage 1: skip (text below threshold)")
    stage_info.append("Stage 2: would evaluate suitability")
    stage_info.append(f"Stage 3: would extract from {result.chunks_found} chunk(s)")
    stage_info.append("Stage 4: would assemble hierarchy")
    if cfg.hallucination_check.enabled:
        stage_info.append("Stage 5: would run hallucination check")
    else:
        stage_info.append("Stage 5: disabled")

    result.skills_generated = [f"(dry-run) {'; '.join(stage_info)}"]
    logger.info(
        "[DRY RUN] %s — %d chars, %d chunk(s)\n  %s",
        source_path.name,
        len(text),
        len(text_chunks),
        "\n  ".join(stage_info),
    )
    return result


# ---------------------------------------------------------------------------
# Process a single source file — 5-stage pipeline
# ---------------------------------------------------------------------------

def process_file(
    source_path: Path,
    client: LLMClient,
    prompts: dict[str, str],
    cfg: PipelineConfig,
) -> ProcessingResult:
    """Full 5-stage pipeline for one source file.

    Args:
        source_path: Path to the source text file.
        client: Configured LLM client.
        prompts: Dict with keys: extraction, generation, segmentation, suitability, hallucination_check.
        cfg: Pipeline configuration.
    """
    start_time = time.time()
    result = ProcessingResult(source_file=source_path.name)
    output_dir = Path(cfg.paths.output_dir).resolve()

    try:
        text = source_path.read_text(encoding="utf-8", errors="replace")
        original_text = text  # preserve for Stage 5

        # Check minimum length
        if len(text) < cfg.extraction.min_file_length:
            result.status = "skipped"
            result.error_message = (
                f"Too short ({len(text)} chars < {cfg.extraction.min_file_length})"
            )
            return result

        # ===================================================================
        # Stage 1: Summarize & Segment (概括分段)
        # ===================================================================
        if cfg.segmentation.enabled and len(text) > cfg.segmentation.char_threshold:
            logger.info(
                "Stage 1 (Segment): %s — %d chars (above %d threshold), segmenting...",
                source_path.name, len(text), cfg.segmentation.char_threshold,
            )
            chunks = step_segment(
                client,
                text,
                prompts["segmentation"],
                cfg.batch.max_retries,
                cfg.batch.retry_base_delay,
                max_tokens=cfg.segmentation.max_tokens,
            )
        else:
            logger.info(
                "Stage 1 (Segment): %s — %d chars (below %d threshold), treating as single chunk.",
                source_path.name, len(text), cfg.segmentation.char_threshold,
            )
            chunks = [{"chunk_id": "0", "summary": "Full text (single unit)", "text": text, "estimated_type": "experimental"}]

        result.chunks_found = len(chunks)

        # ===================================================================
        # Stage 2: Suitability Review (适合性筛选)
        # ===================================================================
        if cfg.suitability.enabled and len(chunks) > 0:
            logger.info(
                "Stage 2 (Suitability): evaluating %d chunk(s) from %s...",
                len(chunks), source_path.name,
            )
            suitable_chunks = step_suitability_filter(
                client,
                chunks,
                prompts["suitability"],
                cfg.batch.max_retries,
                cfg.batch.retry_base_delay,
                max_tokens=cfg.suitability.max_tokens,
            )
        else:
            # If suitability stage is disabled, pass all chunks through
            suitable_chunks = chunks
            logger.info("Stage 2 (Suitability): disabled, passing all %d chunk(s).", len(chunks))

        result.chunks_suitable = len(suitable_chunks)

        if not suitable_chunks:
            result.status = "success"
            result.error_message = "No chunks passed suitability review"
            logger.info("No suitable chunks found in %s after Stage 2.", source_path.name)
            return result

        # ===================================================================
        # Stage 3: Atomic Extraction (原子提取)
        # ===================================================================
        all_skills: list[dict[str, Any]] = []

        for i, chunk in enumerate(suitable_chunks):
            chunk_text_content = chunk.get("text", "")
            chunk_id = chunk.get("chunk_id", str(i))

            # If chunk text is very large, further split it for the extraction call
            sub_chunks = chunk_text(chunk_text_content, cfg.extraction.max_chunk_size)

            for j, sub in enumerate(sub_chunks):
                logger.info(
                    "Stage 3 (Extract): %s — chunk %s (sub %d/%d, %d chars)...",
                    source_path.name, chunk_id, j + 1, len(sub_chunks), len(sub),
                )
                extraction_result = step_extract(
                    client,
                    sub,
                    prompts["extraction"],
                    cfg.batch.max_retries,
                    cfg.batch.retry_base_delay,
                )
                extracted = extraction_result.get("extracted_skills", [])
                # Tag each skill with its source chunk_id
                for skill in extracted:
                    skill["_source_chunk_id"] = chunk_id
                all_skills.extend(extracted)

        if not all_skills:
            result.status = "success"
            result.error_message = "No extractable skills found in suitable chunks"
            logger.info("No skills extracted from %s after Stage 3.", source_path.name)
            return result

        # Check for existing skills before generation
        skills_to_generate = []
        for skill_data in all_skills:
            skill_name = skill_data.get("skill_name", "")
            safe_name = to_safe_name(skill_name)
            if cfg.extraction.skip_existing and (output_dir / safe_name / "SKILL.md").exists():
                logger.info("Skipping existing skill: %s", safe_name)
                continue
            skills_to_generate.append(skill_data)

        if not skills_to_generate:
            result.status = "success"
            result.error_message = "All extracted skills already exist"
            return result

        # ===================================================================
        # Stage 4: Generate + Hierarchical Assembly (层级组装)
        # ===================================================================
        generated: list[tuple[dict[str, Any], str]] = []

        for skill_data in skills_to_generate:
            skill_name = skill_data.get("skill_name", "unnamed-skill")
            logger.info("Stage 4 (Generate): generating SKILL.md for: %s", skill_name)

            skill_md = step_generate_skill(
                client,
                skill_data,
                prompts["generation"],
                cfg.batch.max_retries,
                cfg.batch.retry_base_delay,
            )
            generated.append((skill_data, skill_md))

        # Assemble hierarchy
        source_stem = source_path.stem
        written_names = assemble_hierarchy(generated, output_dir, source_stem)
        result.skills_generated = written_names

        # ===================================================================
        # Stage 5: Hallucination Check (幻觉检查)
        # ===================================================================
        if cfg.hallucination_check.enabled:
            quarantine_dir = Path(cfg.paths.quarantine_dir).resolve()

            for skill_data, skill_md in generated:
                skill_name = skill_data.get("skill_name", "unnamed-skill")
                logger.info("Stage 5 (Hallucination Check): verifying %s...", skill_name)

                check_result = step_hallucination_check(
                    client,
                    skill_md,
                    original_text,
                    prompts["hallucination_check"],
                    cfg.batch.max_retries,
                    cfg.batch.retry_base_delay,
                    max_tokens=cfg.hallucination_check.max_tokens,
                )
                check_result["skill_name"] = skill_name
                result.hallucination_check_results.append(check_result)

                if not check_result.get("pass", True):
                    flagged_count = check_result.get("flagged_count", len(check_result.get("flagged", [])))
                    logger.warning(
                        "Skill '%s' FAILED hallucination check: %d issue(s). %s",
                        skill_name,
                        flagged_count,
                        check_result.get("summary", ""),
                    )

                    # Optionally quarantine the failed skill
                    if cfg.hallucination_check.quarantine_on_fail:
                        safe_name = to_safe_name(skill_name)
                        skill_dir = output_dir / safe_name
                        if skill_dir.exists():
                            quarantine_dest = quarantine_dir / safe_name
                            quarantine_dest.parent.mkdir(parents=True, exist_ok=True)
                            if quarantine_dest.exists():
                                shutil.rmtree(quarantine_dest)
                            shutil.move(str(skill_dir), str(quarantine_dest))
                            logger.info(
                                "Quarantined failed skill: %s -> %s",
                                skill_dir, quarantine_dest,
                            )
                else:
                    verified = check_result.get("verified_count", "?")
                    logger.info(
                        "Skill '%s' PASSED hallucination check (%s claims verified).",
                        skill_name, verified,
                    )
        else:
            logger.info("Stage 5 (Hallucination Check): disabled.")

        result.status = "success"

    except Exception as exc:
        result.status = "error"
        result.error_message = f"{type(exc).__name__}: {exc}"
        logger.error("Error processing %s: %s", source_path.name, exc)
        logger.debug(traceback.format_exc())

    finally:
        result.duration_seconds = time.time() - start_time

    return result


# ---------------------------------------------------------------------------
# Async batch processing with concurrency control
# ---------------------------------------------------------------------------

async def process_file_async(
    semaphore: asyncio.Semaphore,
    source_path: Path,
    client: LLMClient,
    prompts: dict[str, str],
    cfg: PipelineConfig,
) -> ProcessingResult:
    """Process a single file with concurrency control."""
    async with semaphore:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            process_file,
            source_path,
            client,
            prompts,
            cfg,
        )


async def run_batch_async(
    files: list[Path],
    client: LLMClient,
    prompts: dict[str, str],
    cfg: PipelineConfig,
) -> list[ProcessingResult]:
    """Process all files with bounded concurrency."""
    semaphore = asyncio.Semaphore(cfg.batch.concurrency)
    tasks = [
        process_file_async(semaphore, f, client, prompts, cfg)
        for f in files
    ]
    return await asyncio.gather(*tasks)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="5-stage batch extraction pipeline for cognitive science skills.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python extract.py --config config.yaml\n"
            "  python extract.py --config config.yaml --dry-run\n"
            "  python extract.py --config config.yaml --input ./papers --output ./skills\n"
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Path to config.yaml (default: pipeline/config.yaml)",
    )
    parser.add_argument(
        "--input",
        type=str,
        default=None,
        help="Override input directory from config",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Override output directory from config",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan files and report what would be processed, without calling the LLM API",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Path to write the extraction report (default: print to stdout)",
    )
    args = parser.parse_args()

    # Load configuration
    overrides = {}
    if args.input:
        overrides["input"] = args.input
    if args.output:
        overrides["output"] = args.output

    cfg = load_config(args.config, cli_overrides=overrides)
    setup_logging(cfg.logging)

    logger.info("Pipeline starting (5-stage architecture).")
    logger.info("  Provider : %s", cfg.llm.provider)
    logger.info("  Model    : %s", cfg.llm.model)
    logger.info("  Input    : %s", Path(cfg.paths.input_dir).resolve())
    logger.info("  Output   : %s", Path(cfg.paths.output_dir).resolve())
    logger.info("  Dry-run  : %s", args.dry_run)
    logger.info("  Stages   : Segment(%s) -> Suitability(%s) -> Extract -> Assemble -> HallucinationCheck(%s)",
                "ON" if cfg.segmentation.enabled else "OFF",
                "ON" if cfg.suitability.enabled else "OFF",
                "ON" if cfg.hallucination_check.enabled else "OFF")

    # Discover source files
    files = discover_source_files(cfg)
    if not files:
        logger.warning("No source files found. Nothing to do.")
        return 0

    # Dry-run mode
    if args.dry_run:
        results = [dry_run_file(f, cfg) for f in files]
        report = generate_report(results, args.report)
        if not args.report:
            print(report)
        return 0

    # Validate API key
    if not cfg.llm.api_key:
        env_var = "OPENAI_API_KEY" if cfg.llm.provider == "openai" else "ANTHROPIC_API_KEY"
        logger.error(
            "No API key configured. Set it in config.yaml or via %s environment variable.",
            env_var,
        )
        return 1

    # Load all prompt templates
    try:
        prompts = {
            "extraction": load_prompt(EXTRACTION_PROMPT_PATH),
            "generation": load_prompt(SKILL_GEN_PROMPT_PATH),
            "segmentation": load_prompt(SEGMENTATION_PROMPT_PATH),
            "suitability": load_prompt(SUITABILITY_PROMPT_PATH),
            "hallucination_check": load_prompt(HALLUCINATION_CHECK_PROMPT_PATH),
        }
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 1

    # Create LLM client
    client = LLMClient(cfg.llm)

    # Ensure output directory exists
    Path(cfg.paths.output_dir).resolve().mkdir(parents=True, exist_ok=True)

    # Run batch processing
    logger.info("Processing %d file(s) with concurrency=%d ...", len(files), cfg.batch.concurrency)

    if cfg.batch.concurrency > 1:
        results = asyncio.run(
            run_batch_async(files, client, prompts, cfg)
        )
    else:
        # Sequential — simpler for debugging
        results = []
        for f in files:
            r = process_file(f, client, prompts, cfg)
            results.append(r)

    # Generate report
    report = generate_report(results, args.report)
    if not args.report:
        print(report)

    # Summary
    success_count = sum(1 for r in results if r.status == "success")
    error_count = sum(1 for r in results if r.status == "error")
    total_skills = sum(len(r.skills_generated) for r in results if r.status == "success")
    logger.info(
        "Pipeline complete: %d success, %d errors, %d skills generated.",
        success_count,
        error_count,
        total_skills,
    )

    return 1 if error_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
