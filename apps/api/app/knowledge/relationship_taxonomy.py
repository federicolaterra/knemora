"""Bounded application-owned vocabulary for explicit Wiki relationships."""

from __future__ import annotations

import re
from dataclasses import dataclass

RELATIONSHIP_TAXONOMY_VERSION = "1"


@dataclass(frozen=True)
class RelationshipType:
    name: str
    category: str
    description: str
    aliases: tuple[str, ...] = ()
    symmetric: bool = False
    durable: bool = False
    patterns: tuple[str, ...] = ()


RELATIONSHIP_TYPES: tuple[RelationshipType, ...] = (
    RelationshipType(
        "sibling_of",
        "family",
        "two people are siblings",
        aliases=("sibling", "siblings", "brother_of", "sister_of"),
        symmetric=True,
        durable=True,
        patterns=(
            r"{source}\s+and\s+{target}\s+(?:are|were)\s+(?:siblings|brothers|sisters)",
            r"{source}\s+(?:is|was)\s+(?:(?:a|the)\s+)?(?:sibling|brother|sister)\s+of\s+{target}",
        ),
    ),
    RelationshipType(
        "parent_of",
        "family",
        "a person is a parent of another person",
        aliases=("parent", "father_of", "mother_of"),
        durable=True,
        patterns=(
            r"{source}\s+(?:is|was)\s+(?:a\s+|the\s+)?(?:parent|father|mother)\s+of\s+{target}",
        ),
    ),
    RelationshipType(
        "child_of",
        "family",
        "a person is a child of another person",
        aliases=("child", "son_of", "daughter_of"),
        durable=True,
        patterns=(
            r"{source}\s+(?:is|was)\s+(?:a\s+|the\s+)?(?:child|son|daughter)\s+of\s+{target}",
        ),
    ),
    RelationshipType(
        "spouse_of",
        "family",
        "two people are spouses",
        aliases=("spouse", "married_to", "husband_of", "wife_of"),
        symmetric=True,
        patterns=(
            r"{source}\s+and\s+{target}\s+(?:are|were)\s+(?:married|spouses)",
            r"{source}\s+(?:is|was)\s+(?:the\s+)?(?:spouse|husband|wife)\s+of\s+{target}",
        ),
    ),
    RelationshipType(
        "grandparent_of",
        "family",
        "a person is a grandparent of another person",
        aliases=("grandfather_of", "grandmother_of"),
        durable=True,
        patterns=(
            r"{source}\s+(?:is|was)\s+(?:(?:a|the)\s+)?(?:grandparent|grandfather|grandmother)\s+of\s+{target}",
        ),
    ),
    RelationshipType(
        "grandchild_of",
        "family",
        "a person is a grandchild of another person",
        aliases=("grandson_of", "granddaughter_of"),
        durable=True,
        patterns=(
            r"{source}\s+(?:is|was)\s+(?:(?:a|the)\s+)?(?:grandchild|grandson|granddaughter)\s+of\s+{target}",
        ),
    ),
    RelationshipType(
        "cousin_of",
        "family",
        "two people are cousins",
        aliases=("cousin",),
        symmetric=True,
        durable=True,
        patterns=(
            r"{source}\s+and\s+{target}\s+(?:are|were)\s+cousins",
            r"{source}\s+(?:is|was)\s+(?:(?:a|the)\s+)?cousin\s+of\s+{target}",
        ),
    ),
    RelationshipType(
        "works_at",
        "professional",
        "a person currently works at an organization",
        aliases=("works_for",),
        patterns=(r"{source}\s+(?:currently\s+)?works\s+(?:at|for)\s+{target}",),
    ),
    RelationshipType(
        "employed_by",
        "professional",
        "a person is currently employed by an organization",
        patterns=(r"{source}\s+(?:is\s+)?(?:currently\s+)?employed\s+by\s+{target}",),
    ),
    RelationshipType(
        "colleague_of",
        "professional",
        "two people are or were colleagues",
        aliases=("colleague", "coworker_of", "co_worker_of"),
        symmetric=True,
        durable=True,
        patterns=(
            r"{source}\s+and\s+{target}\s+(?:are|were)\s+(?:former\s+)?(?:colleagues|coworkers|co-workers)",
            r"{source}\s+(?:is|was)\s+(?:a\s+)?(?:former\s+)?(?:colleague|coworker|co-worker)\s+of\s+{target}",
        ),
    ),
    RelationshipType(
        "founder_of",
        "professional",
        "a person founded an organization or project",
        aliases=("founded", "cofounder_of", "co_founder_of"),
        durable=True,
        patterns=(
            r"{source}\s+(?:is|was)\s+(?:a\s+|the\s+)?(?:founder|co-founder)\s+of\s+{target}",
            r"{source}\s+(?:founded|co-founded)\s+{target}",
        ),
    ),
    RelationshipType(
        "owner_of",
        "professional",
        "a person or organization owns another organization or project",
        aliases=("owns",),
        durable=True,
        patterns=(
            r"{source}\s+(?:is|was)\s+(?:an?\s+|the\s+)?owner\s+of\s+{target}",
            r"{source}\s+owns\s+{target}",
        ),
    ),
    RelationshipType(
        "studied_at",
        "education",
        "a person studied at an educational organization",
        durable=True,
        patterns=(r"{source}\s+studied\s+at\s+{target}",),
    ),
    RelationshipType(
        "graduated_from",
        "education",
        "a person graduated from an educational organization",
        durable=True,
        patterns=(r"{source}\s+graduated\s+from\s+{target}",),
    ),
    RelationshipType(
        "teaches_at",
        "education",
        "a person currently teaches at an educational organization",
        patterns=(r"{source}\s+(?:currently\s+)?teaches\s+at\s+{target}",),
    ),
    RelationshipType(
        "member_of",
        "organizations",
        "a person or organization is a member of an organization",
        patterns=(r"{source}\s+(?:is\s+)?(?:a\s+)?member\s+of\s+{target}",),
    ),
    RelationshipType(
        "affiliated_with",
        "organizations",
        "a subject is explicitly affiliated with an organization",
        patterns=(r"{source}\s+(?:is\s+)?affiliated\s+with\s+{target}",),
    ),
    RelationshipType(
        "created_by",
        "projects/technology",
        "a project or technology was created by a named subject",
        aliases=("developed_by", "built_by"),
        durable=True,
        patterns=(
            r"{source}\s+(?:is|was)\s+(?:created|developed|built)\s+by\s+{target}",
            r"{target}\s+(?:created|developed|built)\s+{source}",
        ),
    ),
    RelationshipType(
        "contributes_to",
        "projects/technology",
        "a person or organization contributes to a project",
        patterns=(r"{source}\s+(?:currently\s+)?contributes\s+to\s+{target}",),
    ),
    RelationshipType(
        "uses_technology",
        "projects/technology",
        "a subject explicitly uses a named technology",
        aliases=("technology_use",),
        patterns=(r"{source}\s+(?:currently\s+)?uses\s+{target}",),
    ),
    RelationshipType(
        "lives_in",
        "geography",
        "a person currently lives in a location",
        patterns=(r"{source}\s+(?:currently\s+)?lives\s+in\s+{target}",),
    ),
    RelationshipType(
        "based_in",
        "geography",
        "a subject is currently based in a location",
        patterns=(r"{source}\s+(?:is\s+)?(?:currently\s+)?based\s+in\s+{target}",),
    ),
    RelationshipType(
        "located_in",
        "geography",
        "a subject is located in a location",
        patterns=(r"{source}\s+(?:is\s+)?located\s+in\s+{target}",),
    ),
)

_RELATIONSHIP_BY_NAME = {item.name: item for item in RELATIONSHIP_TYPES}
_CANONICAL_BY_LABEL = {
    re.sub(r"[\s-]+", "_", label.casefold()).strip("_"): item.name
    for item in RELATIONSHIP_TYPES
    for label in (item.name, *item.aliases)
}
_PRESERVED_EQUIVALENT_LABELS = {
    # Keep legacy proposal output byte-compatible while avoiding a duplicate canonical edge.
    "uses": "uses_technology",
}


def relationship_type(label: str) -> RelationshipType | None:
    """Resolve a safelisted canonical label or documented alias."""

    normalized = re.sub(r"[\s-]+", "_", label.casefold()).strip("_")
    canonical = _CANONICAL_BY_LABEL.get(normalized)
    return _RELATIONSHIP_BY_NAME.get(canonical) if canonical is not None else None


def equivalent_relationship_name(label: str) -> str:
    """Return a canonical comparison key without rewriting preserved legacy labels."""

    normalized = re.sub(r"[\s-]+", "_", label.casefold()).strip("_")
    kind = relationship_type(label)
    if kind is not None:
        return kind.name
    return _PRESERVED_EQUIVALENT_LABELS.get(normalized, normalized)


def relationship_prompt_guidance() -> str:
    """Render concise versioned guidance for the existing proposal call."""

    categories: dict[str, list[str]] = {}
    for item in RELATIONSHIP_TYPES:
        categories.setdefault(item.category, []).append(item.name)
    vocabulary = "; ".join(
        f"{category}: {', '.join(names)}" for category, names in categories.items()
    )
    symmetric = ", ".join(item.name for item in RELATIONSHIP_TYPES if item.symmetric)
    return (
        f"Relationship taxonomy v{RELATIONSHIP_TAXONOMY_VERSION}: {vocabulary}. "
        f"Use these exact labels when applicable. {symmetric} are symmetric: propose one edge "
        "only. Keep direction exactly as named for other labels. Create a relationship only when "
        "the cited source span explicitly names both endpoints and states the relation as fact. "
        "Historical colleague statements use colleague_of; preserve their tense in the claim and "
        "evidence rather than asserting that the people are current colleagues. "
        "Do not infer one from co-occurrence, topics, filenames, labels, quotations, negation, "
        "hypotheticals, ambiguity, or former/current status that the label cannot represent."
    )
