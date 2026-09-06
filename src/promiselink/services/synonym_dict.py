"""Controlled synonym dictionaries for W4 entity normalization.

The base edition starts with deterministic, synthetic-safe seed entries. A local
JSON file may override/extend them without a database migration. No user data
is embedded in the seed dictionaries.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

PERSON_SYNONYMS: dict[str, list[str]] = {
    "林晚秋": ["林总", "晚秋"],
    "沈书白": ["沈总", "书白"],
    "费晚棠": ["费总", "晚棠"],
    "顾清和": ["顾总", "清和"],
    "叶望舒": ["叶总", "望舒"],
}

COMPANY_SYNONYMS: dict[str, list[str]] = {
    "青梧科技": ["青梧", "Qingwu Technology"],
    "澄海生物": ["澄海", "Chenghai Bio"],
    "栖云数据": ["栖云", "Qiyun Data"],
}

SYNONYM_DICT_VERSION = "w4-v1"


def _merge_dicts(base: dict[str, list[str]], override: object) -> dict[str, list[str]]:
    """Merge JSON mapping values while preserving deterministic list order."""
    result = {key: list(values) for key, values in base.items()}
    if not isinstance(override, dict):
        return result
    for canonical, aliases in override.items():
        if not isinstance(canonical, str) or not isinstance(aliases, list):
            continue
        existing = result.setdefault(canonical, [])
        for alias in aliases:
            if isinstance(alias, str) and alias and alias not in existing:
                existing.append(alias)
    return result


def load_synonyms(path: str | Path | None = None) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Load controlled dictionaries from JSON, extending built-in seeds."""
    person = dict(PERSON_SYNONYMS)
    company = dict(COMPANY_SYNONYMS)
    if path is None:
        return person, company
    file_path = Path(path)
    if not file_path.exists():
        return person, company
    data = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return person, company
    return (
        _merge_dicts(person, data.get("person")),
        _merge_dicts(company, data.get("company")),
    )


def find_aliases(name: str, type_: Literal["person", "company"], dictionaries: tuple[dict[str, list[str]], dict[str, list[str]]] | None = None) -> list[str]:
    """Return canonical name plus aliases when ``name`` is a canonical or alias value."""
    person, company = dictionaries or (PERSON_SYNONYMS, COMPANY_SYNONYMS)
    dictionary = person if type_ == "person" else company
    if name in dictionary:
        return [name, *dictionary[name]]
    for canonical, aliases in dictionary.items():
        if name in aliases:
            return [canonical, *[alias for alias in aliases if alias != name]]
    return []
