#!/usr/bin/env python3
"""Parse Gradle version catalogs and find real alias use in build scripts."""

import re


SEPARATORS = re.compile(r"[-_.]+")
ALIAS_USE = re.compile(r"\blibs\.([A-Za-z0-9_.]+)")
FUNCTION_CALL = re.compile(r"\b([A-Za-z][A-Za-z0-9_]*)\s*\(")
KNOWN_CONFIGURATIONS = {
    "api", "implementation", "compileOnly", "runtimeOnly",
    "testImplementation", "testCompileOnly", "testRuntimeOnly",
    "annotationProcessor", "kapt", "ksp",
}
WRAPPERS = {"platform", "enforcedPlatform", "project", "files"}


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


def configuration_for_line(line, alias_start):
    calls = [match.group(1) for match in FUNCTION_CALL.finditer(line[:alias_start])]
    for value in calls:
        if value in KNOWN_CONFIGURATIONS:
            return value
    identifiers = re.findall(r"\b[A-Za-z][A-Za-z0-9_]*\b", line[:alias_start])
    for value in identifiers:
        if value in KNOWN_CONFIGURATIONS:
            return value
    for value in reversed(calls):
        if value not in WRAPPERS:
            return value
    return "unknown"


def find_alias_usages(text):
    cleaned = without_comments_and_strings(text)
    result = []
    for line_number, line in enumerate(cleaned.splitlines(), 1):
        for match in ALIAS_USE.finditer(line):
            found_accessor = match.group(1).rstrip(".")
            if found_accessor.startswith(("bundles.", "plugins.", "versions.")):
                continue
            result.append({
                "accessor": found_accessor,
                "configuration": configuration_for_line(line, match.start()),
                "line": line_number,
            })
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
