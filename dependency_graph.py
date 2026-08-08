#!/usr/bin/env python3
"""Parse Gradle version catalogs and find real alias use in build scripts."""

import re


SEPARATORS = re.compile(r"[-_.]+")
SCAN_TOKEN = re.compile(
    r"\blibs\.([A-Za-z0-9_.]+)|\b([A-Za-z][A-Za-z0-9_]*)\b|([()])"
)
KNOWN_CONFIGURATIONS = {
    "api", "implementation", "compileOnly", "runtimeOnly",
    "testImplementation", "testCompileOnly", "testRuntimeOnly",
    "annotationProcessor", "kapt", "ksp",
}
WRAPPERS = {"platform", "enforcedPlatform", "project", "files", "add"}


def accessor(alias):
    return ".".join(part for part in SEPARATORS.split(alias) if part)


def version_definitions(mapping, prefix=""):
    """Flatten dotted version aliases while preserving rich-version tables."""
    for key, value in mapping.items() if isinstance(mapping, dict) else []:
        name = str(key) if not prefix else prefix + "." + str(key)
        if isinstance(value, dict) and not any(
            field in value for field in ("require", "strictly", "prefer", "reject", "rejectAll")
        ):
            yield from version_definitions(value, name)
        else:
            yield name, value


def library_definitions(mapping, prefix=""):
    """Flatten dotted TOML aliases without flattening their inline tables."""
    for key, value in mapping.items() if isinstance(mapping, dict) else []:
        name = str(key) if not prefix else prefix + "." + str(key)
        if isinstance(value, dict) and not any(
            field in value for field in ("module", "group", "name", "version")
        ):
            yield from library_definitions(value, name)
        else:
            yield name, value


def version_details(definition, versions):
    reference = ""
    value = ""
    declared = definition.get("version") if isinstance(definition, dict) else None
    if isinstance(declared, dict):
        reference = str(declared.get("ref", ""))
        value = str(declared.get("require", "") or declared.get("strictly", ""))
    elif declared is not None:
        value = str(declared)
    if reference:
        resolved = versions.get(reference)
        if resolved is not None:
            if isinstance(resolved, dict):
                value = str(
                    resolved.get("require", "")
                    or resolved.get("strictly", "")
                    or resolved.get("prefer", "")
                )
            else:
                value = str(resolved)
    return reference, value


def parse_version_catalog(text, toml_module):
    if toml_module is None:
        raise ValueError("tomllib/tomli is required to parse Gradle version catalogs")
    try:
        document = toml_module.loads(text)
    except Exception as exception:
        raise ValueError("invalid TOML version catalog: %s" % exception)
    versions = dict(version_definitions(document.get("versions", {})))
    records = []
    for alias, definition in library_definitions(document.get("libraries", {})):
        group_id = artifact_id = version_ref = version_value = ""
        if isinstance(definition, str):
            parts = definition.split(":")
            if len(parts) >= 2:
                group_id, artifact_id = parts[:2]
                version_value = parts[2] if len(parts) >= 3 else ""
        elif isinstance(definition, dict):
            module = definition.get("module")
            if isinstance(module, str) and ":" in module:
                group_id, artifact_id = module.split(":", 1)
            else:
                group_id = str(definition.get("group", ""))
                artifact_id = str(definition.get("name", ""))
            version_ref, version_value = version_details(definition, versions)
        if group_id and artifact_id:
            records.append({
                "alias": alias,
                "accessor": accessor(alias),
                "group_id": group_id,
                "artifact_id": artifact_id,
                "version_ref": version_ref,
                "version_value": version_value,
            })
    return records


def without_comments_and_strings(text):
    """Blank comments and literals while preserving line positions."""
    output = list(text)
    index = 0
    state = "code"
    quote = ""
    block_depth = 0
    while index < len(text):
        pair = text[index:index + 2]
        triple = text[index:index + 3]
        if state == "code":
            if pair == "//":
                output[index:index + 2] = "  "
                index += 2
                state = "line-comment"
                continue
            if pair == "/*":
                output[index:index + 2] = "  "
                index += 2
                state = "block-comment"
                block_depth = 1
                continue
            if triple in {'"""', "'''"}:
                output[index:index + 3] = "   "
                index += 3
                state = "string"
                quote = triple
                continue
            if text[index] in {'"', "'"}:
                output[index] = " "
                quote = text[index]
                index += 1
                state = "string"
                continue
            index += 1
            continue
        if state == "line-comment":
            if text[index] == "\n":
                state = "code"
            else:
                output[index] = " "
            index += 1
            continue
        if state == "block-comment":
            if pair == "/*":
                output[index:index + 2] = "  "
                index += 2
                block_depth += 1
            elif pair == "*/":
                output[index:index + 2] = "  "
                index += 2
                block_depth -= 1
                if block_depth == 0:
                    state = "code"
            else:
                if text[index] != "\n":
                    output[index] = " "
                index += 1
            continue
        closing = text.startswith(quote, index)
        if closing:
            output[index:index + len(quote)] = " " * len(quote)
            index += len(quote)
            state = "code"
        elif text[index] == "\\" and len(quote) == 1 and index + 1 < len(text):
            output[index:index + 2] = "  "
            index += 2
        else:
            if text[index] != "\n":
                output[index] = " "
            index += 1
    return "".join(output)


def configuration_for_context(line, alias_start, open_calls, original, alias_position):
    for value, _ in open_calls:
        if value in KNOWN_CONFIGURATIONS:
            return value
    for value, open_position in reversed(open_calls):
        if value != "add":
            continue
        prefix = original[open_position + 1:alias_position]
        declaration = re.match(
            r"\s*(['\"])([A-Za-z][A-Za-z0-9_]*)\1\s*,", prefix, flags=re.DOTALL
        )
        if declaration:
            return declaration.group(2)
    # Groovy DSL commonly omits parentheses: `runtimeOnly libs.someAlias`.
    statement = re.split(r"[;{}]", line[:alias_start])[-1]
    declaration = re.match(r"\s*([A-Za-z][A-Za-z0-9_]*)\b", statement)
    if declaration and declaration.group(1) in KNOWN_CONFIGURATIONS:
        return declaration.group(1)
    for value, _ in reversed(open_calls):
        if value and value not in WRAPPERS:
            return value
    return "unknown"


def find_alias_usages(text):
    cleaned = without_comments_and_strings(text)
    result = []
    open_calls = []
    pending_identifier = None
    previous_end = 0
    line_number = 1
    for match in SCAN_TOKEN.finditer(cleaned):
        gap = cleaned[previous_end:match.start()]
        line_number += gap.count("\n")
        if gap.strip():
            pending_identifier = None
        found_accessor, identifier, parenthesis = match.groups()
        if found_accessor is not None:
            found_accessor = found_accessor.rstrip(".")
            if not found_accessor.startswith(("bundles.", "plugins.", "versions.")):
                line_start = cleaned.rfind("\n", 0, match.start()) + 1
                line_end = cleaned.find("\n", match.end())
                if line_end < 0:
                    line_end = len(cleaned)
                line = cleaned[line_start:line_end]
                result.append({
                    "accessor": found_accessor,
                    "configuration": configuration_for_context(
                        line,
                        match.start() - line_start,
                        open_calls,
                        text,
                        match.start(),
                    ),
                    "line": line_number,
                })
            pending_identifier = None
        elif identifier is not None:
            pending_identifier = identifier
        elif parenthesis == "(":
            open_calls.append((pending_identifier, match.start()))
            pending_identifier = None
        else:
            if open_calls:
                open_calls.pop()
            pending_identifier = None
        previous_end = match.end()
    return result


def normalized(value):
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def resolve_owner(record, candidates):
    target = normalized(record["artifact_id"])
    matches = [candidate for candidate in candidates if target in candidate["terms"]]
    if not matches:
        return "", ""
    matches.sort(key=lambda item: (-item.get("priority", 0), item["repository"], item["module"]))
    return matches[0]["repository"], matches[0]["module"]
