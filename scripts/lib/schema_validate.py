"""Offline JSON-LD validation — no external API calls.

Pipeline: extruct (extract JSON-LD from HTML) -> tiered checks against
Google's rich-result guidelines. Google has no public Rich Results Test API
(UI-only) and validator.schema.org is a web form only — this is the
practical CI-safe alternative.

Severity model (what CI is allowed to block on):
  error    Markup that is broken or ineligible: malformed JSON-LD, a node
           with no @type, or a **Google-required** property missing/empty.
  warning  A **Google-recommended** property missing/empty — valid markup,
           reduced eligibility. Never fails CI unless --strict.
  info     Advisory: types whose rich-result treatment Google retired
           (FAQ/HowTo, 2023) — valid markup, no visual yield expected.

Google's docs mark most Article properties (image, datePublished, author…)
as *recommended*, not required — labelling them errors (as this module once
did) blocks CI on markup Google itself accepts. Property presence is
checked as non-empty: `"image": ""` does not count.

Scope: JSON-LD only (the format Google recommends). Microdata/RDFa are out
of scope for this validator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

try:
    import extruct
except ImportError:
    extruct = None

GOOGLE_RICH_RESULTS: dict[str, dict[str, list[str]]] = {
    "Article": {"required": [],
                "recommended": ["headline", "image", "datePublished", "dateModified", "author"]},
    "NewsArticle": {"required": [],
                    "recommended": ["headline", "image", "datePublished", "dateModified", "author"]},
    "BlogPosting": {"required": [],
                    "recommended": ["headline", "image", "datePublished", "dateModified", "author"]},
    "Product": {"required": ["name"],
                "recommended": ["image", "description", "offers", "review", "aggregateRating"]},
    "Organization": {"required": ["name"],
                     "recommended": ["url", "logo"]},
    "FAQPage": {"required": ["mainEntity"], "recommended": []},
    "HowTo": {"required": ["name", "step"], "recommended": []},
    "BreadcrumbList": {"required": ["itemListElement"], "recommended": []},
    "LocalBusiness": {"required": ["name", "address"],
                      "recommended": ["telephone", "url", "openingHoursSpecification", "geo"]},
    "Recipe": {"required": ["name", "image"],
               "recommended": ["recipeIngredient", "recipeInstructions", "author",
                               "prepTime", "cookTime", "nutrition"]},
    "VideoObject": {"required": ["name", "thumbnailUrl", "uploadDate"],
                    "recommended": ["description", "duration", "contentUrl"]},
    "Person": {"required": ["name"], "recommended": []},
    "WebSite": {"required": ["name", "url"], "recommended": []},
}

RETIRED_RICH_RESULTS: dict[str, str] = {
    "FAQPage": ("Google retired FAQ rich results for most sites (Aug 2023) — "
                "the markup is valid but earns no visual treatment except for "
                "well-known health/government sites."),
    "HowTo": ("Google retired HowTo rich results (Sep 2023) — the markup is "
              "valid but earns no visual treatment."),
}


@dataclass
class ValidationIssue:
    node_type: str
    severity: str
    message: str


@dataclass
class ValidationResult:
    url: str
    node_count: int = 0
    types_found: list[str] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    def counts(self) -> dict[str, int]:
        out = {"error": 0, "warning": 0, "info": 0}
        for issue in self.issues:
            out[issue.severity] = out.get(issue.severity, 0) + 1
        return out


def extract_json_ld(html: str, base_url: str) -> list[dict[str, Any]]:
    """Returns a flat list of JSON-LD nodes (unwrapping @graph)."""
    if extruct is None:
        raise RuntimeError("extruct is required — python3 -m pip install -r requirements.txt")

    data = extruct.extract(html, base_url=base_url, syntaxes=["json-ld"])
    nodes: list[dict[str, Any]] = []
    for item in data.get("json-ld", []):
        if "@graph" in item:
            nodes.extend(n for n in item["@graph"] if isinstance(n, dict))
        else:
            nodes.append(item)
    return nodes


def _type_names(node: dict[str, Any]) -> list[str]:
    raw = node.get("@type", [])
    return raw if isinstance(raw, list) else [raw] if raw else []


def _is_empty(value: Any) -> bool:
    """Present-but-empty values don't satisfy a property requirement."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def validate_html(html: str, url: str) -> ValidationResult:
    result = ValidationResult(url=url)
    try:
        nodes = extract_json_ld(html, url)
    except Exception as exc:
        result.issues.append(ValidationIssue(
            "unknown", "error", f"JSON-LD extraction failed: {exc}"))
        return result

    result.node_count = len(nodes)
    for node in nodes:
        type_names = _type_names(node)
        if not type_names:
            result.issues.append(ValidationIssue(
                "unknown", "error", "JSON-LD node has no @type"))
            continue
        for type_name in type_names:
            result.types_found.append(type_name)
            spec = GOOGLE_RICH_RESULTS.get(type_name)
            if spec is None:
                continue

            missing_required = [p for p in spec["required"]
                                if p not in node or _is_empty(node.get(p))]
            if missing_required:
                result.issues.append(ValidationIssue(
                    type_name, "error",
                    f"{type_name} is missing (or has empty) Google-required "
                    f"propert{'y' if len(missing_required) == 1 else 'ies'}: "
                    f"{', '.join(missing_required)}",
                ))

            missing_recommended = [p for p in spec["recommended"]
                                   if p not in node or _is_empty(node.get(p))]
            if missing_recommended:
                result.issues.append(ValidationIssue(
                    type_name, "warning",
                    f"{type_name} is missing Google-recommended "
                    f"propert{'y' if len(missing_recommended) == 1 else 'ies'}: "
                    f"{', '.join(missing_recommended)} — valid markup, but "
                    "reduced rich-result eligibility",
                ))

            if type_name in RETIRED_RICH_RESULTS:
                result.issues.append(ValidationIssue(
                    type_name, "info", RETIRED_RICH_RESULTS[type_name]))
    return result
