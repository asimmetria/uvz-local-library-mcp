#!/usr/bin/env python3
"""Parse and validate curated project-context cards during index builds."""

import re
from pathlib import Path


SCHEMA_VERSION = 1
KINDS = {"application", "library", "library-suite", "support-module"}
CYRILLIC = re.compile(r"[А-Яа-яЁё]")
ABSOLUTE_PATH = re.compile(r"^(?:/|~[/\\]|[A-Za-z]:[/\\])")
LOCAL_PATH_IN_TEXT = re.compile(r"(?:/home/|/Users/|[A-Za-z]:[/\\])")
ALLOWED_FIELDS = {
    "schema_version", "kind", "name", "aliases", "modules", "purpose",
    "use_when", "do_not_use_when", "entrypoints", "dependency",
    "configuration", "examples", "evidence", "related", "unknowns",
    "components",
}
OBJECT_FIELDS = {
    "evidence": {"path", "proves", "url"},
    "examples": {"id", "path", "summary"},
    "configuration": {"key", "required", "description"},
    "components": {"module", "context"},
}
USAGE_HEADINGS = (
    "## Когда использовать",
    "## Зависимость",
    "## Минимальный пример",
    "## Обязательная конфигурация",
    "## Ожидаемый результат",
    "## Ограничения и типичные ошибки",
    "## Evidence",
)


def string_list(value):
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def validate_object_list(card, field, required_fields):
    errors = []
    value = card.get(field)
    if value is None:
        return errors
    if not isinstance(value, list):
        return ["%s must be a list" % field]
    for index, item in enumerate(value, 1):
        if not isinstance(item, dict):
            errors.append("%s[%d] must be an object" % (field, index))
            continue
        unknown = sorted(set(item) - OBJECT_FIELDS[field])
        if unknown:
            errors.append("%s[%d] has unknown fields: %s" % (field, index, ", ".join(unknown)))
        for required in required_fields:
            if not isinstance(item.get(required), str) or not item[required].strip():
                errors.append("%s[%d].%s must be a non-empty string" % (field, index, required))
    return errors


def referenced_paths(card):
    for field in ("examples", "evidence"):
        for item in card.get(field, []) if isinstance(card.get(field), list) else []:
            if isinstance(item, str):
                yield field, item
            elif isinstance(item, dict) and isinstance(item.get("path"), str):
                yield field, item["path"]
    for item in card.get("components", []) if isinstance(card.get("components"), list) else []:
        if isinstance(item, dict) and isinstance(item.get("context"), str):
            yield "components", item["context"]


def validate_usage_document(path, repository_root):
    errors = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exception:
        return ["usage document is unreadable: %s" % exception]
    if not re.search(r"^#\s+\S", text, re.MULTILINE):
        errors.append("usage document must have an H1 title")
    for heading in USAGE_HEADINGS:
        if not re.search(r"^%s\s*$" % re.escape(heading), text, re.MULTILINE):
            errors.append("usage document is missing heading: %s" % heading)
    if LOCAL_PATH_IN_TEXT.search(text):
        errors.append("usage document contains an absolute local path")
    if "## Evidence" in text:
        section = text.split("## Evidence", 1)[1]
        section = re.split(r"^##\s+", section, maxsplit=1, flags=re.MULTILINE)[0]
        paths = [value.strip() for value in re.findall(r"`([^`]+)`", section)]
        if not paths:
            errors.append("usage Evidence must contain a backticked repository-relative path")
        for value in paths:
            if value.startswith(("http://", "https://")) or ABSOLUTE_PATH.match(value):
                errors.append("usage Evidence path is not repository-relative: %s" % value)
                continue
            resolved = (repository_root / value).resolve()
            try:
                resolved.relative_to(repository_root.resolve())
            except ValueError:
                errors.append("usage Evidence path escapes the repository: %s" % value)
                continue
            if not resolved.is_file():
                errors.append("usage Evidence path does not exist: %s" % value)
    return errors


def validate_card(card, repository_root):
    errors = []
    if not isinstance(card, dict):
        return ["document must be a YAML object"]
    unknown_fields = sorted(set(card) - ALLOWED_FIELDS)
    if unknown_fields:
        errors.append("unknown fields: " + ", ".join(unknown_fields))
    if card.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version must be %d" % SCHEMA_VERSION)
    if card.get("kind") not in KINDS:
        errors.append("kind must be one of: " + ", ".join(sorted(KINDS)))
    for field in ("name", "purpose"):
        if not isinstance(card.get(field), str) or not card[field].strip():
            errors.append("%s must be a non-empty string" % field)
    use_when = string_list(card.get("use_when"))
    if not use_when:
        errors.append("use_when must contain at least one concrete caller need")
    evidence = card.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        errors.append("evidence must contain at least one repository-relative source")
    errors.extend(validate_object_list(card, "evidence", ("path", "proves")))
    errors.extend(validate_object_list(card, "examples", ("id", "path", "summary")))
    errors.extend(validate_object_list(card, "configuration", ("key", "description")))
    for index, item in enumerate(card.get("configuration", []) if isinstance(card.get("configuration"), list) else [], 1):
        if isinstance(item, dict) and "required" in item and not isinstance(item["required"], bool):
            errors.append("configuration[%d].required must be true or false" % index)
    for index, item in enumerate(card.get("evidence", []) if isinstance(card.get("evidence"), list) else [], 1):
        if isinstance(item, dict) and "url" in item:
            if not isinstance(item["url"], str) or not item["url"].startswith(("http://", "https://")):
                errors.append("evidence[%d].url must be an HTTP(S) permalink" % index)
    if card.get("kind") == "library-suite":
        if not card.get("components"):
            errors.append("library-suite must declare independently consumable components")
        errors.extend(validate_object_list(card, "components", ("module", "context")))
        combined_fields = [field for field in ("entrypoints", "dependency", "configuration", "examples") if card.get(field)]
        if combined_fields:
            errors.append("library-suite must keep component details in child cards: " + ", ".join(combined_fields))
    elif card.get("components"):
        errors.append("components is only valid for library-suite")
    for field in ("aliases", "modules", "use_when", "do_not_use_when", "entrypoints", "related", "unknowns"):
        value = card.get(field)
        if field in card and (not isinstance(value, list) or len(string_list(value)) != len(value)):
            errors.append("%s must contain only non-empty strings" % field)
    dependency = card.get("dependency")
    if dependency is not None:
        if not isinstance(dependency, dict):
            errors.append("dependency must be an object")
        elif dependency.get("ecosystem") not in {"gradle", "maven", "npm"}:
            errors.append("dependency.ecosystem must be gradle, maven or npm")
        elif not isinstance(dependency.get("declaration"), str) or not dependency["declaration"].strip():
            errors.append("dependency.declaration must be a non-empty string")
        elif dependency["ecosystem"] == "gradle":
            alias = dependency.get("alias")
            if not isinstance(alias, str) or not alias.startswith("libs.") or alias not in dependency["declaration"]:
                errors.append("Gradle dependency must use the same confirmed libs.* alias in alias and declaration")
        elif dependency["ecosystem"] == "maven" and not (
            isinstance(dependency.get("coordinates"), str) and dependency["coordinates"].strip()
        ):
            errors.append("Maven dependency must contain confirmed coordinates")
        elif dependency["ecosystem"] == "npm" and not (
            isinstance(dependency.get("package"), str) and dependency["package"].strip()
        ):
            errors.append("npm dependency must contain a confirmed package")
        if isinstance(dependency, dict):
            allowed = {
                "gradle": {"ecosystem", "alias", "declaration"},
                "maven": {"ecosystem", "coordinates", "declaration"},
                "npm": {"ecosystem", "package", "declaration"},
            }.get(dependency.get("ecosystem"), {"ecosystem", "declaration"})
            unknown = sorted(set(dependency) - allowed)
            if unknown:
                errors.append("dependency has unknown fields: " + ", ".join(unknown))
    russian_values = [("purpose", card.get("purpose", ""))]
    for field in ("use_when", "do_not_use_when", "unknowns"):
        russian_values.extend((field, value) for value in string_list(card.get(field)))
    for field in ("evidence", "examples", "configuration"):
        text_field = {"evidence": "proves", "examples": "summary", "configuration": "description"}[field]
        for item in card.get(field, []) if isinstance(card.get(field), list) else []:
            if isinstance(item, dict) and isinstance(item.get(text_field), str):
                russian_values.append(("%s.%s" % (field, text_field), item[text_field]))
    for field, value in russian_values:
        if value.strip() and not CYRILLIC.search(value):
            errors.append("%s must contain Russian explanatory text" % field)
    repository_root = repository_root.resolve()
    validated_usage = set()
    for field, value in referenced_paths(card):
        value = value.strip()
        if value.startswith(("http://", "https://")):
            errors.append("%s must use a repository-relative path, not only a URL: %s" % (field, value))
            continue
        if ABSOLUTE_PATH.match(value):
            errors.append("%s contains an absolute local path: %s" % (field, value))
            continue
        resolved = (repository_root / value).resolve()
        try:
            resolved.relative_to(repository_root)
        except ValueError:
            errors.append("%s escapes the repository: %s" % (field, value))
            continue
        if not resolved.is_file():
            errors.append("%s path does not exist: %s" % (field, value))
        if field == "examples" and not re.search(r"(?:^|/)docs/usage/[^/]+\.md$", value):
            errors.append("examples must point to docs/usage/*.md: %s" % value)
        elif field == "examples" and resolved.is_file() and resolved not in validated_usage:
            validated_usage.add(resolved)
            errors.extend("examples %s: %s" % (value, error) for error in validate_usage_document(resolved, repository_root))
        if field == "components" and Path(value).name != "project-context.yaml":
            errors.append("components must point to project-context.yaml: %s" % value)
    return errors


def load_card(text, yaml_module):
    if yaml_module is None:
        raise ValueError("PyYAML is required to parse project-context.yaml")
    try:
        card = yaml_module.safe_load(text)
    except yaml_module.YAMLError as exception:
        raise ValueError("invalid YAML: %s" % exception)
    return card


def item_paths(value):
    result = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict) and isinstance(item.get("path"), str):
            result.append(item["path"])
    return result


def catalog_item(card, repository, module):
    aliases = [card["name"]] + string_list(card.get("aliases"))
    capabilities = ["context"]
    if card.get("examples"):
        capabilities.append("usage")
    if card.get("entrypoints"):
        capabilities.append("api")
    if card.get("configuration"):
        capabilities.append("configuration")
    return {
        "id": card["name"],
        "type": card["kind"],
        "status": "curated",
        "aliases": list(dict.fromkeys(aliases)),
        "sources": [repository + module],
        "capabilities": capabilities,
        "purpose": card["purpose"],
        "use_when": string_list(card.get("use_when")),
        "examples": item_paths(card.get("examples")),
    }
