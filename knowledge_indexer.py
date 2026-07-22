#!/usr/bin/env python3
"""Build a local SQLite FTS5 knowledge pack from one or more source trees."""

import argparse
import hashlib
import html
import json
import re
import sqlite3
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:  # The FTS index remains usable when dependencies are not installed yet.
    yaml = None


SKIP_DIRS = {".git", ".gradle", ".idea", "build", "dist", "node_modules", "target", "generated", "__generated", "__pycache__"}
CODE_EXTENSIONS = {".java": "java", ".kt": "kotlin", ".kts": "kotlin", ".ts": "typescript", ".tsx": "typescript", ".js": "javascript", ".jsx": "javascript", ".vue": "vue"}
TEXT_EXTENSIONS = {".md": "markdown", ".mdx": "markdown", ".html": "html", ".htm": "html", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml", ".properties": "properties"}
LIBRARY_SUFFIXES = ("-adapter", "-model-shared", "-facade")
LIBRARY_CONTAINER_SUFFIX = "-lib"
SECRET_NAME = r"(?:password|secret|token|private[-_]?key|credential|api[-_]?key)"
SECRET_KEY = re.compile(r"(?im)^(\s*" + SECRET_NAME + r"\s*[:=]).*$")
SECRET_BLOCK_START = re.compile(r"(?i)^(\s*)" + SECRET_NAME + r"\s*:\s*[>|]")
HTML_TAG = re.compile(r"</?(?:a|article|aside|br|code|details|div|em|footer|h[1-6]|header|img|li|main|nav|ol|p|pre|section|script|span|strong|style|table|tbody|td|th|thead|tr|ul)\b[^>]*>", re.IGNORECASE)


def args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", required=True, help="Knowledge pack id, e.g. jimmer")
    parser.add_argument("--source", action="append", type=Path, required=True, help="Repository or source root; repeatable")
    parser.add_argument("--db", type=Path, default=Path("knowledge.db"))
    parser.add_argument("--catalog", type=Path, default=Path("skill/generated-catalog.md"))
    parser.add_argument("--audit", type=Path, default=Path("audit-summary.json"))
    parser.add_argument("--sync", action="store_true", help="Safely update clean Git roots before indexing")
    parser.add_argument("--configuration-root", action="append", type=Path, default=[], help="Central configuration repository; repeatable")
    return parser.parse_args()


def git(root, *command):
    result = subprocess.run(["git", "-C", str(root), *command], text=True, capture_output=True)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


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
    code, _, _ = git(root, "rev-parse", "--verify", "master")
    if code:
        return "sync_skipped_no_master"
    # A clean feature branch can still contain valuable local commits. Do not
    # switch it away merely to refresh the knowledge pack.
    if branch != "master":
        code, local_only, _ = git(root, "rev-list", "master..HEAD")
        if code or local_only:
            return "sync_skipped_branch_ahead"
    code, counts, _ = git(root, "rev-list", "--left-right", "--count", "master...origin/master")
    if code:
        return "sync_failed_remote_master_check"
    local_ahead, _ = counts.split()
    if int(local_ahead):
        return "sync_skipped_master_ahead"
    for command in (("checkout", "master"), ("pull", "--ff-only", "origin", "master")):
        code, _, _ = git(root, *command)
        if code:
            return "sync_failed"
    return "synced"


def commit(root):
    code, value, _ = git(root, "rev-parse", "HEAD")
    return value if code == 0 else "not-a-git-repository"


def clean_markup(text, language):
    if language == "markdown":
        text = re.sub(r"\A---\s*\n.*?\n---\s*\n", "", text, flags=re.DOTALL)
        text = re.sub(r"^\s*(import|export)\s+.*$", "", text, flags=re.MULTILINE)
        text = HTML_TAG.sub("", text)
    elif language == "html":
        text = re.sub(r"(?is)<(script|style|nav|header|footer).*?</\1>", "", text)
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
                continue
            skip_indent = None
        block = SECRET_BLOCK_START.match(line)
        if block:
            kept.append(line[:line.find(":") + 1] + " <redacted>\n")
            skip_indent = len(block.group(1))
        else:
            kept.append(line)
    return SECRET_KEY.sub(lambda match: match.group(1) + " <redacted>", "".join(kept))


def chunks(text, language, max_chars=7000):
    if language == "markdown":
        parts = re.split(r"(?=^#{1,3}\s)", text, flags=re.MULTILINE)
        return [part.strip() for part in parts if len(part.strip()) >= 80]
    if len(text) <= max_chars:
        return [text.strip()] if text.strip() else []
    lines, result, current = text.splitlines(keepends=True), [], ""
    for line in lines:
        if len(current) + len(line) > max_chars and current.strip():
            result.append(current.strip())
            current = ""
        current += line
    if current.strip():
        result.append(current.strip())
    return result


def title_for(path, text):
    heading = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    symbol = re.search(r"^\s*(?:(?:public|private|protected|abstract|final|data|sealed|open)\s+)*(?:class|interface|object|enum|record)\s+([A-Za-z_]\w*)", text, re.MULTILINE)
    return (heading.group(1) if heading else symbol.group(1) if symbol else path.stem).strip()


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
    con.execute("DROP TABLE IF EXISTS chunks")
    con.execute("DROP TABLE IF EXISTS configuration_values")
    con.execute("CREATE VIRTUAL TABLE chunks USING fts5(source_id UNINDEXED, pack_id UNINDEXED, repository UNINDEXED, module UNINDEXED, path UNINDEXED, kind UNINDEXED, language UNINDEXED, configuration_set UNINDEXED, commit_sha UNINDEXED, line_start UNINDEXED, line_end UNINDEXED, title, content, tokenize='unicode61')")
    con.execute("CREATE TABLE configuration_values (source_id TEXT NOT NULL, pack_id TEXT NOT NULL, repository TEXT NOT NULL, module TEXT NOT NULL, path TEXT NOT NULL, configuration_set TEXT NOT NULL, profile TEXT NOT NULL, layer TEXT NOT NULL, key_path TEXT NOT NULL, value_json TEXT NOT NULL)")
    con.execute("CREATE INDEX configuration_values_lookup ON configuration_values(repository, module, configuration_set, profile, key_path)")
    return con


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
    con, audit, catalog = init_db(options.db), Counter(), []
    configuration_roots = {path.resolve() for path in options.configuration_root}
    for root in options.source:
        root = root.resolve()
        if not root.is_dir():
            raise SystemExit("Source does not exist: %s" % root)
        audit["sources"] += 1
        audit[sync_source(root) if options.sync else "sync_not_requested"] += 1
        sha, repo, modules = commit(root), root.name, discover_modules(root)
        audit["gradle_modules_discovered"] += len(modules)
        if options.pack == "jimmer":
            catalog.append({"id": repo, "type": "library", "status": "ready", "aliases": [repo.replace("-", " ")], "sources": [repo + ":"], "capabilities": ["docs", "examples", "api"]})
        for module_path, module_id in modules.items():
            module_name = module_path.name
            if is_library_module(module_path, module_id, modules):
                catalog.append({"id": repo + module_id.replace(":", "-"), "type": "library", "status": "discovered", "aliases": [module_name.replace("-", " ")], "sources": [repo + module_id], "capabilities": ["api", "examples"]})
        for path, language in walk(root):
            audit["files_seen"] += 1
            try:
                raw = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                audit["files_unreadable"] += 1
                continue
            text = redact(clean_markup(raw, language), language).strip()
            if language in {"markdown", "html"} and HTML_TAG.search(text):
                audit["chunks_with_raw_html"] += 1
            rel, module = path.relative_to(root).as_posix(), module_for(path, modules)
            kind = "example" if "example" in rel.lower() or "test" in rel.lower() else "configuration" if language in {"yaml", "toml", "properties"} else "docs" if language in {"markdown", "html"} else "source"
            config_set = configuration_set(root, path, configuration_roots) if kind == "configuration" else ""
            source_base = "%s:%s" % (repo, rel)
            if kind == "configuration" and language == "yaml":
                count = index_configuration_values(con, text=text, source_id=source_base, pack=options.pack, repository=repo, module=module, path=Path(rel), config_set=config_set)
                audit["configuration_values_indexed"] += count
                if yaml is None:
                    audit["configuration_values_skipped_no_pyyaml"] += 1
            for position, chunk in enumerate(chunks(text, language), 1):
                if len(chunk) < 40:
                    audit["chunks_too_short"] += 1
                    continue
                source_id = "%s#%d" % (source_base, position)
                con.execute("INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (source_id, options.pack, repo, module, rel, kind, language, config_set, sha, 1, len(chunk.splitlines()), title_for(path, chunk), chunk))
                audit["chunks_indexed"] += 1
    con.commit()
    con.close()
    options.catalog.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Generated knowledge catalog", "", "Generated locally; do not edit manually.", ""]
    for item in sorted(catalog, key=lambda value: value["id"]):
        lines += ["## %s [%s, %s]" % (item["id"], item["type"], item["status"]), "- aliases: %s" % ", ".join(item["aliases"]), "- sources: %s" % ", ".join(item["sources"]), "- capabilities: %s" % ", ".join(item["capabilities"]), ""]
    options.catalog.write_text("\n".join(lines), encoding="utf-8")
    report = {"pack": options.pack, "built_at": datetime.now(timezone.utc).isoformat(), **audit, "database": str(options.db), "catalog": str(options.catalog)}
    options.audit.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
