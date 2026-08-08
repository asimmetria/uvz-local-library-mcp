#!/usr/bin/env python3
"""Build a local SQLite FTS5 knowledge pack from one or more source trees."""

import argparse
import hashlib
import html
import json
import os
import re
import sqlite3
import subprocess
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from dependency_graph import find_alias_usages, normalized, parse_version_catalog, resolve_owner
from knowledge_schema import SCHEMA_VERSION, create_schema, validate_schema
from project_context import catalog_item, load_card, validate_card

try:
    import yaml
except ImportError:  # The FTS index remains usable when dependencies are not installed yet.
    yaml = None

try:
    import tomllib as toml
except ImportError:
    try:
        import tomli as toml
    except ImportError:
        toml = None


SKIP_DIRS = {".git", ".gradle", ".idea", "build", "dist", "node_modules", "target", "generated", "__generated", "__pycache__"}
CODE_EXTENSIONS = {".java": "java", ".kt": "kotlin", ".kts": "kotlin", ".gradle": "groovy", ".ts": "typescript", ".tsx": "typescript", ".js": "javascript", ".jsx": "javascript", ".vue": "vue"}
TEXT_EXTENSIONS = {".md": "markdown", ".mdx": "markdown", ".html": "html", ".htm": "html", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml", ".properties": "properties"}
LIBRARY_SUFFIXES = ("-adapter", "-model-shared", "-facade")
LIBRARY_CONTAINER_SUFFIX = "-lib"
SECRET_NAME = r"(?:password|secret|token|private[-_]?key|credential|api[-_]?key)"
SECRET_PATH = r"(?:[A-Za-z0-9_.-]+[._-])?" + SECRET_NAME
SECRET_KEY = re.compile(r"(?im)^(\s*" + SECRET_PATH + r"\s*[:=]).*$")
SECRET_BLOCK_START = re.compile(r"(?i)^(\s*)" + SECRET_PATH + r"\s*:\s*[>|]")
HTML_TAG = re.compile(r"</?(?:a|article|aside|br|code|details|div|em|footer|h[1-6]|header|img|li|main|nav|ol|p|pre|section|script|span|strong|style|table|tbody|td|th|thead|tr|ul)\b[^>]*>", re.IGNORECASE)
CODE_BOUNDARY = re.compile(
    r"^(?:@|(?:public|protected|private|internal|abstract|final|open|sealed|data|static|suspend|async|export)\s+)*(?:class|interface|object|enum|record|fun|def|function)\b"
)


def args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", required=True, help="Knowledge pack id, e.g. jimmer")
    parser.add_argument("--source", action="append", type=Path, required=True, help="Repository or source root; repeatable")
    parser.add_argument("--db", type=Path, default=Path("knowledge.db"))
    parser.add_argument("--catalog", type=Path, default=Path("skills/library-knowledge-workflow/generated-catalog.md"))
    parser.add_argument("--audit", type=Path, default=Path("audit-summary.json"))
    parser.add_argument("--sync", action="store_true", help="Safely update clean Git roots before indexing")
    parser.add_argument("--configuration-root", action="append", type=Path, default=[], help="Central configuration repository; repeatable")
    parser.add_argument("--excluded-source", action="append", default=[], help="Repository omitted by workspace discovery; repeatable")
    return parser.parse_args()


def git(root, *command):
    result = subprocess.run(["git", "-C", str(root), *command], text=True, capture_output=True)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def default_branch(root):
    """Return the remote default branch, with safe common fallbacks."""
    code, value, _ = git(root, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if code == 0 and value.startswith("origin/"):
        candidate = value.removeprefix("origin/")
        code, _, _ = git(root, "rev-parse", "--verify", f"origin/{candidate}")
        if code == 0:
            return candidate
    for candidate in ("master", "main"):
        code, _, _ = git(root, "rev-parse", "--verify", f"origin/{candidate}")
        if code == 0:
            return candidate
    return None


def sync_source(root):
    code, status, _ = git(root, "status", "--porcelain")
    if code or status:
        return "sync_skipped_dirty"
    code, branch, _ = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if code:
        return "sync_skipped_not_git"
    if branch == "HEAD":
        return "sync_skipped_detached_head"
    code, _, _ = git(root, "fetch", "origin", "--prune")
    if code:
        return "sync_failed_fetch"
    target_branch = default_branch(root)
    if target_branch is None:
        return "sync_skipped_no_default_branch"
    remote_target = f"origin/{target_branch}"
    code, _, _ = git(root, "show-ref", "--verify", "--quiet", f"refs/heads/{target_branch}")
    target_exists_locally = code == 0
    # A clean feature branch can still contain valuable local commits. Do not
    # switch it away merely to refresh the knowledge pack.
    if branch != target_branch:
        base = target_branch if target_exists_locally else remote_target
        code, local_only, _ = git(root, "rev-list", f"{base}..HEAD")
        if code or local_only:
            return "sync_skipped_branch_ahead"
    if target_exists_locally:
        code, counts, _ = git(root, "rev-list", "--left-right", "--count", f"{target_branch}...{remote_target}")
        if code:
            return "sync_failed_remote_default_branch_check"
        local_ahead, _ = counts.split()
        if int(local_ahead):
            return "sync_skipped_default_branch_ahead"
        checkout = ("checkout", target_branch)
    else:
        checkout = ("checkout", "-b", target_branch, "--track", remote_target)
    for command in (checkout, ("pull", "--ff-only", "origin", target_branch)):
        code, _, _ = git(root, *command)
        if code:
            return "sync_failed"
    return "synced"


def commit(root):
    code, value, _ = git(root, "rev-parse", "HEAD")
    return value if code == 0 else "not-a-git-repository"


def clean_markup(text, language):
    if language == "markdown":
        text = re.sub(
            r"\A---\s*\n.*?\n---\s*\n",
            lambda match: "\n" * match.group(0).count("\n"),
            text,
            flags=re.DOTALL,
        )
        text = re.sub(r"^\s*(import|export)\s+.*$", "", text, flags=re.MULTILINE)
        text = HTML_TAG.sub("", text)
    elif language == "html":
        text = re.sub(
            r"(?is)<(script|style|nav|header|footer).*?</\1>",
            lambda match: "\n" * match.group(0).count("\n"),
            text,
        )
        text = HTML_TAG.sub(" ", text)
        text = html.unescape(text)
    return text


def redact(text, language):
    if language not in {"yaml", "toml", "properties"}:
        return text
    # YAML block scalars need line-aware handling: a regexp cannot know where
    # a nested key's indentation ends without also deleting neighbouring data.
    kept, skip_indent = [], None
    for line in text.splitlines(keepends=True):
        indentation = len(line) - len(line.lstrip(" \t"))
        if skip_indent is not None:
            if line.strip() and indentation > skip_indent:
                kept.append("\n" if line.endswith("\n") else "")
                continue
            skip_indent = None
        block = SECRET_BLOCK_START.match(line)
        if block:
            kept.append(line[:line.find(":") + 1] + " <redacted>\n")
            skip_indent = len(block.group(1))
        else:
            kept.append(line)
    return SECRET_KEY.sub(lambda match: match.group(1) + " <redacted>", "".join(kept))


def normalized_chunk(lines, start, end):
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    if start == end:
        return None
    return "".join(lines[start:end]).strip(), start + 1, end


def split_ranges(lines, start, end, max_chars):
    """Split a line range near paragraph or top-level symbol boundaries."""
    prefix = [0]
    for line in lines:
        prefix.append(prefix[-1] + len(line))
    cursor = start
    while cursor < end:
        hard_end = cursor
        while hard_end < end:
            next_size = prefix[hard_end + 1] - prefix[cursor]
            if hard_end > cursor and next_size > max_chars:
                break
            hard_end += 1
        if hard_end >= end:
            yield cursor, end
            return
        split = hard_end
        minimum_size = max_chars // 2
        for candidate in range(hard_end, cursor, -1):
            current_size = prefix[candidate] - prefix[cursor]
            paragraph = not lines[candidate - 1].strip()
            symbol = candidate < end and CODE_BOUNDARY.match(lines[candidate])
            if symbol or (current_size >= minimum_size and paragraph):
                split = candidate
                break
        yield cursor, split
        cursor = split


def chunks(text, language, max_chars=7000):
    """Yield chunk text and its 1-based inclusive line range."""
    lines = text.splitlines(keepends=True)
    if not lines:
        return []
    if language == "markdown":
        headings = [index for index, line in enumerate(lines) if re.match(r"^#{1,3}\s", line)]
        boundaries = sorted(set([0] + headings + [len(lines)]))
        result = []
        for start, end in zip(boundaries, boundaries[1:]):
            for chunk_start, chunk_end in split_ranges(lines, start, end, max_chars):
                chunk = normalized_chunk(lines, chunk_start, chunk_end)
                if chunk and len(chunk[0]) >= 80:
                    result.append(chunk)
        return result
    result = []
    for start, end in split_ranges(lines, 0, len(lines), max_chars):
        chunk = normalized_chunk(lines, start, end)
        if chunk:
            result.append(chunk)
    return result


def title_for(path, text):
    heading = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    symbol = re.search(r"^\s*(?:(?:public|private|protected|abstract|final|data|sealed|open)\s+)*(?:class|interface|object|enum|record)\s+([A-Za-z_]\w*)", text, re.MULTILINE)
    return (heading.group(1) if heading else symbol.group(1) if symbol else path.stem).strip()


def content_kind(path, relative, language):
    if path.name == "project-context.yaml":
        return "context"
    parts = Path(relative).parts
    if language == "markdown" and len(parts) >= 3 and parts[-3:-1] == ("docs", "usage"):
        return "usage"
    if "example" in relative.lower() or "test" in relative.lower():
        return "example"
    if language in {"yaml", "toml", "properties"}:
        return "configuration"
    if language in {"markdown", "html"}:
        return "docs"
    return "source"


def add_catalog(catalog, item):
    """Curated cards replace a naming heuristic for the same module."""
    curated = item.get("status") == "curated"
    if curated:
        item_sources = set(item.get("sources", []))
        for identifier, existing in list(catalog.items()):
            if existing.get("status") != "curated" and item_sources.intersection(existing.get("sources", [])):
                del catalog[identifier]
    key = item["id"] + "\0" + ",".join(item.get("sources", []))
    existing = catalog.get(key)
    if existing and existing.get("status") == "curated" and not curated:
        return
    catalog[key] = item


def owner_candidate(repository, module, names, priority=0):
    return {
        "repository": repository,
        "module": module,
        "terms": {normalized(name) for name in names if name},
        "priority": priority,
    }


def index_dependency_graph(con, *, pack, aliases, usages, owners, audit):
    by_accessor = {}
    seen_aliases = set()
    for record in aliases:
        identity = (record["catalog_repository"], record["catalog_path"], record["alias"])
        if identity in seen_aliases:
            continue
        seen_aliases.add(identity)
        owner_repository, owner_module = resolve_owner(record, owners)
        record["owner_repository"] = owner_repository
        record["owner_module"] = owner_module
        con.execute(
            "INSERT INTO dependency_aliases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                pack, record["catalog_repository"], record["catalog_path"],
                record["catalog_commit_sha"], record["alias"], record["accessor"],
                record["group_id"], record["artifact_id"], record["version_ref"],
                record["version_value"], owner_repository, owner_module,
            ),
        )
        by_accessor.setdefault(record["accessor"], []).append(record)
        audit["dependency_aliases_indexed"] += 1
        if owner_repository:
            audit["dependency_aliases_with_owner"] += 1
    seen_usages = set()
    for usage in usages:
        matches = by_accessor.get(usage["accessor"], [])
        if not matches:
            for suffix in (".get", ".orNull", ".getOrNull"):
                if usage["accessor"].endswith(suffix):
                    matches = by_accessor.get(usage["accessor"][:-len(suffix)], [])
                    if matches:
                        break
        if not matches:
            audit["dependency_usages_unresolved"] += 1
            continue
        if len(matches) > 1:
            audit["dependency_alias_collisions"] += 1
        for record in matches:
            identity = (
                record["catalog_repository"], record["catalog_path"], record["alias"],
                usage["consumer_repository"], usage["consumer_module"],
                usage["path"], usage["configuration"], usage["line"],
            )
            if identity in seen_usages:
                continue
            seen_usages.add(identity)
            con.execute(
                "INSERT INTO dependency_usages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    pack, record["catalog_repository"], record["catalog_path"],
                    record["alias"], record["accessor"], usage["consumer_repository"],
                    usage["consumer_module"], usage["path"],
                    usage["configuration"], usage["commit_sha"], usage["line"],
                ),
            )
            audit["dependency_usages_indexed"] += 1


def classify(path):
    suffix = path.suffix.lower()
    return CODE_EXTENSIONS.get(suffix) or TEXT_EXTENSIONS.get(suffix)


def walk(root):
    for path in root.rglob("*"):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.parts):
            continue
        language = classify(path)
        if language:
            yield path, language


def localized_docusaurus_content(root, path):
    """Base docs are canonical; i18n trees are translated duplicates."""
    relative = path.relative_to(root)
    return (
        ((root / "docusaurus.config.js").exists() or (root / "docusaurus.config.ts").exists())
        and len(relative.parts) >= 2
        and relative.parts[0] == "i18n"
    )


def discover_modules(root):
    """Return Gradle module directory -> Gradle module id, including nested modules."""
    modules = {root: ":"}
    declared = []
    for settings in (root / "settings.gradle.kts", root / "settings.gradle"):
        if settings.exists():
            text = settings.read_text(encoding="utf-8", errors="replace")
            declared.extend(re.findall(r"[\"'](:[A-Za-z0-9_:-]+)[\"']", text))
    for module_id in set(declared):
        directory = root.joinpath(*module_id.lstrip(":").split(":"))
        if directory.is_dir():
            modules[directory] = module_id
    for build_file in root.rglob("build.gradle*"):
        if any(part in SKIP_DIRS for part in build_file.parts):
            continue
        directory = build_file.parent
        relative = directory.relative_to(root)
        modules.setdefault(directory, ":" + ":".join(relative.parts) if relative.parts else ":")
    return modules


def module_for(path, modules):
    candidates = [directory for directory in modules if directory in path.parents or directory == path.parent]
    directory = max(candidates, key=lambda value: len(value.parts))
    return modules[directory]


def is_library_module(module_path, module_id, modules):
    """Recognize direct library modules and every child of a *-lib suite."""
    if module_id != ":" and module_path.name.endswith(LIBRARY_SUFFIXES):
        return True
    parent = module_path.parent
    while parent in modules:
        if parent.name.endswith(LIBRARY_CONTAINER_SUFFIX):
            return True
        parent = parent.parent
    return False


def configuration_set(root, path, configuration_roots):
    if root not in configuration_roots:
        return ""
    relative = path.relative_to(root)
    return relative.parts[0] if len(relative.parts) > 1 else root.name


def init_db(db):
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    create_schema(con)
    return con


def temporary_path(target):
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        prefix=target.name + ".", suffix=".tmp", dir=str(target.parent), delete=False
    )
    handle.close()
    return Path(handle.name)


def stage_text(target, value):
    staged = temporary_path(target)
    staged.write_text(value, encoding="utf-8")
    return staged


def value_profiles(document, path):
    """Profiles declared in YAML take priority over the application-<profile> filename."""
    if not isinstance(document, dict):
        return [filename_profile(path)]
    spring = document.get("spring")
    declared = None
    if isinstance(spring, dict):
        config = spring.get("config")
        activate = config.get("activate") if isinstance(config, dict) else None
        declared = activate.get("on-profile") if isinstance(activate, dict) else spring.get("profiles")
    if declared is None:
        return [filename_profile(path)]
    if isinstance(declared, str):
        return [item.strip() for item in declared.split(",") if item.strip()] or [""]
    if isinstance(declared, list):
        return [str(item) for item in declared] or [""]
    return [""]


def filename_profile(path):
    match = re.match(r"(?:application|bootstrap)-(.+)\.ya?ml$", path.name, re.IGNORECASE)
    return match.group(1) if match else ""


def flatten_yaml(value, prefix=""):
    if isinstance(value, dict):
        for key, nested in value.items():
            key_path = str(key) if not prefix else prefix + "." + str(key)
            yield from flatten_yaml(nested, key_path)
    else:
        # Lists deliberately remain one value: their item order often changes semantics.
        yield prefix, value


def json_value(value):
    """Keep YAML timestamps and other scalar extensions representable in SQLite."""
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else str(value)


def index_configuration_values(con, *, text, source_id, pack, repository, module, path, config_set):
    if yaml is None:
        return 0
    inserted = 0
    try:
        documents = list(yaml.safe_load_all(text))
    except yaml.YAMLError:
        return 0
    layer = "central" if config_set else "module"
    for document in documents:
        if document is None:
            continue
        for profile in value_profiles(document, path):
            for key_path, value in flatten_yaml(document):
                if not key_path:
                    continue
                con.execute(
                    "INSERT INTO configuration_values VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (source_id, pack, repository, module, path.as_posix(), config_set, profile, layer, key_path, json.dumps(value, ensure_ascii=False, sort_keys=True, default=json_value)),
                )
                inserted += 1
    return inserted


def main():
    options = args()
    staged_db = temporary_path(options.db)
    con, audit, catalog = None, Counter(), {}
    audit["project_contexts_invalid"] = 0
    project_context_errors = []
    dependency_graph_errors = []
    dependency_aliases = []
    dependency_usages = []
    owner_candidates = []
    audit["dependency_aliases_indexed"] = 0
    audit["dependency_usages_indexed"] = 0
    staged_catalog = None
    staged_audit = None
    source_revisions = []
    configuration_roots = {path.resolve() for path in options.configuration_root}
    total_sources = len(options.source)
    try:
        con = init_db(staged_db)
        for source_number, root in enumerate(options.source, 1):
            root = root.resolve()
            if not root.is_dir():
                raise SystemExit("Source does not exist: %s" % root)
            audit["sources"] += 1
            sync_status = sync_source(root) if options.sync else "sync_not_requested"
            audit[sync_status] += 1
            sha, repo, modules = commit(root), root.name, discover_modules(root)
            files_before = audit["files_seen"]
            chunks_before = audit["chunks_indexed"]
            values_before = audit["configuration_values_indexed"]
            print("[%d/%d] %s: %s" % (source_number, total_sources, repo, sync_status), flush=True)
            audit["gradle_modules_discovered"] += len(modules)
            owner_candidates.append(owner_candidate(repo, ":", (repo,), priority=2))
            for module_path, module_id in modules.items():
                if module_id != ":":
                    owner_candidates.append(
                        owner_candidate(repo, module_id, (module_path.name,), priority=3)
                    )
            if options.pack == "jimmer":
                add_catalog(catalog, {"id": repo, "type": "library", "status": "ready", "aliases": [repo.replace("-", " ")], "sources": [repo + ":"], "capabilities": ["docs", "examples", "api"]})
            for module_path, module_id in modules.items():
                module_name = module_path.name
                if is_library_module(module_path, module_id, modules):
                    add_catalog(catalog, {"id": repo + module_id.replace(":", "-"), "type": "library", "status": "discovered", "aliases": [module_name.replace("-", " ")], "sources": [repo + module_id], "capabilities": ["api", "examples"]})
            for path, language in walk(root):
                if localized_docusaurus_content(root, path):
                    audit["files_skipped_localized_docusaurus_docs"] += 1
                    continue
                audit["files_seen"] += 1
                try:
                    raw = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    audit["files_unreadable"] += 1
                    continue
                text = redact(clean_markup(raw, language), language).rstrip()
                if language in {"markdown", "html"} and HTML_TAG.search(text):
                    audit["chunks_with_raw_html"] += 1
                rel, module = path.relative_to(root).as_posix(), module_for(path, modules)
                kind = content_kind(path, rel, language)
                config_set = configuration_set(root, path, configuration_roots) if kind == "configuration" else ""
                source_base = "%s:%s" % (repo, rel)
                context_card = None
                if kind == "context":
                    try:
                        context_card = load_card(text, yaml)
                        errors = validate_card(context_card, root)
                    except ValueError as exception:
                        errors = [str(exception)]
                    if errors:
                        audit["project_contexts_invalid"] += 1
                        project_context_errors.append({"source": source_base, "errors": errors})
                        continue
                    audit["project_contexts_indexed"] += 1
                    add_catalog(catalog, catalog_item(context_card, repo, module))
                    owner_candidates.append(owner_candidate(
                        repo,
                        module,
                        [context_card["name"]] + context_card.get("aliases", []),
                        priority=10,
                    ))
                elif kind == "usage":
                    audit["usage_documents_indexed"] += 1
                if repo == "uvz-platform" and path.name == "libs.versions.toml":
                    audit["dependency_catalogs_seen"] += 1
                    try:
                        records = parse_version_catalog(raw, toml)
                    except ValueError as exception:
                        dependency_graph_errors.append("%s: %s" % (source_base, exception))
                    else:
                        for record in records:
                            record.update({
                                "catalog_repository": repo,
                                "catalog_path": rel,
                                "catalog_commit_sha": sha,
                            })
                            dependency_aliases.append(record)
                        audit["dependency_catalog_entries_seen"] += len(records)
                if path.name in {"build.gradle", "build.gradle.kts"}:
                    for usage in find_alias_usages(raw):
                        usage.update({
                            "consumer_repository": repo,
                            "consumer_module": module,
                            "path": rel,
                            "commit_sha": sha,
                        })
                        dependency_usages.append(usage)
                if kind == "configuration" and language == "yaml":
                    count = index_configuration_values(con, text=text, source_id=source_base, pack=options.pack, repository=repo, module=module, path=Path(rel), config_set=config_set)
                    audit["configuration_values_indexed"] += count
                    if yaml is None:
                        audit["configuration_values_skipped_no_pyyaml"] += 1
                for position, (chunk, line_start, line_end) in enumerate(chunks(text, language), 1):
                    if len(chunk) < 40:
                        audit["chunks_too_short"] += 1
                        continue
                    source_id = "%s#%d" % (source_base, position)
                    content_hash = hashlib.sha256(chunk.encode("utf-8")).hexdigest()
                    title = context_card["name"] if context_card else title_for(path, chunk)
                    con.execute("INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (source_id, options.pack, repo, module, rel, kind, language, config_set, sha, line_start, line_end, title, chunk, content_hash))
                    audit["chunks_indexed"] += 1
            source_revisions.append({
                "repository": repo,
                "commit": sha,
                "sync_status": sync_status,
                "files": audit["files_seen"] - files_before,
                "chunks": audit["chunks_indexed"] - chunks_before,
                "configuration_values": audit["configuration_values_indexed"] - values_before,
            })
            print("[%d/%d] %s: done — %d files, %d chunks, %d YAML values" % (
                source_number, total_sources, repo,
                audit["files_seen"] - files_before,
                audit["chunks_indexed"] - chunks_before,
                audit["configuration_values_indexed"] - values_before,
            ), flush=True)
        if project_context_errors:
            details = "\n".join(
                "- %s: %s" % (item["source"], "; ".join(item["errors"]))
                for item in project_context_errors[:50]
            )
            raise SystemExit("Invalid project-context.yaml files:\n" + details)
        if dependency_graph_errors:
            raise SystemExit("Invalid dependency catalogs:\n- " + "\n- ".join(dependency_graph_errors[:50]))
        index_dependency_graph(
            con,
            pack=options.pack,
            aliases=dependency_aliases,
            usages=dependency_usages,
            owners=owner_candidates,
            audit=audit,
        )
        built_at = datetime.now(timezone.utc).isoformat()
        con.execute("INSERT INTO knowledge_metadata VALUES (?, ?)", ("schema_version", str(SCHEMA_VERSION)))
        con.execute("INSERT INTO knowledge_metadata VALUES (?, ?)", ("pack", options.pack))
        con.execute("INSERT INTO knowledge_metadata VALUES (?, ?)", ("built_at", built_at))
        con.commit()
        validate_schema(con)
        duplicate_groups = con.execute(
            "SELECT count(*) FROM (SELECT content_hash FROM chunks GROUP BY content_hash HAVING count(*) > 1)"
        ).fetchone()[0]
        duplicate_chunks = con.execute(
            "SELECT coalesce(sum(amount - 1), 0) FROM (SELECT count(*) AS amount FROM chunks GROUP BY content_hash HAVING count(*) > 1)"
        ).fetchone()[0]
        con.close()
        con = None
        database_sha256 = hashlib.sha256(staged_db.read_bytes()).hexdigest()
        lines = ["# Generated knowledge catalog", "", "Generated locally; do not edit manually.", ""]
        for item in sorted(catalog.values(), key=lambda value: value["id"]):
            lines += [
                "## %s [%s, %s]" % (item["id"], item["type"], item["status"]),
                "- aliases: %s" % ", ".join(item["aliases"]),
                "- sources: %s" % ", ".join(item["sources"]),
                "- capabilities: %s" % ", ".join(item["capabilities"]),
            ]
            if item.get("purpose"):
                lines.append("- purpose: %s" % item["purpose"])
            if item.get("use_when"):
                lines.append("- use when: %s" % "; ".join(item["use_when"]))
            if item.get("examples"):
                lines.append("- examples: %s" % ", ".join(item["examples"]))
            lines.append("")
        report = {
            "pack": options.pack,
            "schema_version": SCHEMA_VERSION,
            "built_at": built_at,
            **audit,
            "source_revisions": source_revisions,
            "duplicate_content_groups": duplicate_groups,
            "duplicate_chunks_beyond_canonical": duplicate_chunks,
            "sources_excluded": options.excluded_source,
            "database": str(options.db),
            "database_sha256": database_sha256,
            "catalog": str(options.catalog),
        }
        staged_catalog = stage_text(options.catalog, "\n".join(lines))
        staged_audit = stage_text(options.audit, json.dumps(report, ensure_ascii=False, indent=2))
        os.replace(str(staged_catalog), str(options.catalog))
        staged_catalog = None
        os.replace(str(staged_audit), str(options.audit))
        staged_audit = None
        os.replace(str(staged_db), str(options.db))
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        if con is not None:
            con.close()
        for path in (staged_db, staged_catalog, staged_audit):
            if path is not None and path.exists():
                path.unlink()


if __name__ == "__main__":
    main()
