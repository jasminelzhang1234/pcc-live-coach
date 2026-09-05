# Copyright 2026 项目作者. Licensed under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Persona .md loader.

Reads `personas/<id>-client.md`, parses YAML frontmatter + body sections.
Returns a dict with: id, line (线), difficulty (难度), version (版本),
opening (开场白 逐字), surface_topic (表层议题), sections (full body as dict).

The 5 "硬约束" lines are extracted as `hard_rules` for system-prompt injection.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)
_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def _parse_frontmatter(block: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip()
    return out


def _parse_sections(body: str) -> Dict[str, str]:
    """Split body by `## ` headings into a dict."""
    matches = list(_SECTION_RE.finditer(body))
    if not matches:
        return {"_raw": body.strip()}
    out: Dict[str, str] = {}
    if matches[0].start() > 0:
        preamble = body[: matches[0].start()].strip()
        if preamble:
            out["_title"] = preamble
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        content = body[start:end].strip()
        out[title] = content
    return out


def _extract_hard_rules(sections: Dict[str, str]) -> List[str]:
    """Pull the bullet lines from `不可越界（硬约束）` section."""
    raw = sections.get("不可越界（硬约束）", "") or sections.get("不可越界(硬约束)", "")
    rules: List[str] = []
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("- "):
            rules.append(s[2:])
    return rules


def load(persona_id: str, personas_dir: str = "personas") -> Dict[str, object]:
    """Load a persona by short ID (e.g. 'vec-01').

    Files searched: <personas_dir>/<id>-client.md (preferred), <id>.md (fallback).
    """
    root = Path(personas_dir)
    if not root.is_absolute():
        root = Path.cwd() / root

    client_path = root / f"{persona_id}-client.md"
    coach_path = root / f"{persona_id}.md"
    chosen: Optional[Path] = None
    if client_path.is_file():
        chosen = client_path
    elif coach_path.is_file():
        chosen = coach_path
    if chosen is None:
        raise FileNotFoundError(
            f"persona not found: {persona_id} (looked in {root})"
        )

    text = chosen.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError(f"missing frontmatter in {chosen}")
    front, body = m.group(1), m.group(2)

    fm = _parse_frontmatter(front)
    sections = _parse_sections(body)
    hard_rules = _extract_hard_rules(sections)

    # Strip 《...》 markers from opening (if any) — keep raw otherwise.
    opening = sections.get("开场白（逐字照说）") or sections.get("开场白(逐字照说)") or ""

    return {
        "id": fm.get("id", persona_id),
        "line": fm.get("线", ""),
        "difficulty": int(fm.get("难度", "0") or 0),
        "version": fm.get("版本", ""),
        "file": str(chosen),
        "opening": opening.strip(),
        "surface_topic": (sections.get("表层议题") or "").strip(),
        "sections": sections,
        "hard_rules": hard_rules,
    }


def list_ids(personas_dir: str = "personas") -> List[str]:
    """Return short IDs for every *-client.md in the persona dir (sorted)."""
    root = Path(personas_dir)
    if not root.is_absolute():
        root = Path.cwd() / root
    if not root.is_dir():
        return []
    ids: List[str] = []
    for p in sorted(root.glob("*-client.md")):
        stem = p.stem  # e.g. 'vec-01-client'
        if stem.endswith("-client"):
            ids.append(stem[: -len("-client")])
    return ids