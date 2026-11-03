"""Versioned prompt files. Each .md file starts with front matter (version, purpose, ...)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROMPT_DIR = Path(__file__).parent


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    meta: dict[str, str]
    body: str


def load_prompt(name: str) -> Prompt:
    """Load prompts/<name>.md, splitting the front matter from the prompt text."""
    text = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
    _, front, body = text.split("---", 2)
    meta = {}
    for line in front.strip().splitlines():
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    return Prompt(name=name, version=meta["version"], meta=meta, body=body.strip())


def list_prompts() -> list[Prompt]:
    return [load_prompt(p.stem) for p in sorted(PROMPT_DIR.glob("*.md"))]
