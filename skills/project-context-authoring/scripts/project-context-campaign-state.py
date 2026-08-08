#!/usr/bin/env python3
"""Atomic state controller for a one-agent project-context campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
MAX_ATTEMPTS = 2


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve())


def load_state(path: Path) -> dict[str, Any]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"Campaign state does not exist: {path}")
    except json.JSONDecodeError as error:
        raise SystemExit(f"Campaign state is not valid JSON: {path}: {error}")
    if state.get("schema_version") != SCHEMA_VERSION:
        raise SystemExit(f"Unsupported campaign state schema: {state.get('schema_version')}")
    return state


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = utc_now()
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def read_excludes(path: Path | None) -> set[str]:
    if path is None or not path.is_file():
        return set()
    result: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        name = raw_line.split("#", 1)[0].strip()
        if name:
            result.add(name)
    return result


def discover_repositories(workspace: Path, excluded: set[str]) -> list[Path]:
    repositories: list[Path] = []
    for current, directories, files in os.walk(workspace, followlinks=False):
        if ".git" in directories or ".git" in files:
            root = Path(current).resolve()
            if root.name not in excluded:
                repositories.append(root)
            if ".git" in directories:
                directories.remove(".git")
        directories[:] = sorted(
            name for name in directories
            if name not in {".gradle", ".idea", "build", "dist", "node_modules", "target"}
        )
    return sorted(set(repositories), key=lambda item: str(item).casefold())


def repository_record(path: Path) -> dict[str, Any]:
    return {
        "name": path.name,
        "path": str(path),
        "status": "pending",
        "attempts": 0,
        "started_at": None,
        "completed_at": None,
        "last_message": "",
        "changed_outside_scope": [],
    }


def is_authoring_path(relative_path: str) -> bool:
    path = Path(relative_path)
    parts = path.parts
    return path.name == "project-context.yaml" or any(
        parts[index:index + 2] == ("docs", "usage")
        for index in range(max(0, len(parts) - 1))
    )


def tracked_and_untracked_files(repository: Path) -> list[str]:
    process = subprocess.run(
        ["git", "-C", str(repository), "ls-files", "-co", "--exclude-standard", "-z"],
        check=True,
        capture_output=True,
    )
    return sorted(
        path.decode("utf-8", errors="surrogateescape")
        for path in process.stdout.split(b"\0")
        if path
    )


def file_fingerprint(path: Path) -> str:
    if path.is_symlink():
        return "symlink:" + os.readlink(path)
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
    except FileNotFoundError:
        return "missing"
    return "sha256:" + digest.hexdigest()


def safety_snapshot(repository: Path) -> dict[str, str]:
    return {
        relative: file_fingerprint(repository / relative)
        for relative in tracked_and_untracked_files(repository)
        if not is_authoring_path(relative)
    }


def command_init(arguments: argparse.Namespace) -> int:
    workspace = Path(arguments.workspace).expanduser().resolve()
    if not workspace.is_dir():
        raise SystemExit(f"Workspace does not exist: {workspace}")
    state_path = Path(arguments.state).expanduser().resolve()
    exclude_path = Path(arguments.exclude_file).expanduser().resolve() if arguments.exclude_file else None
    excluded = read_excludes(exclude_path)
    repositories = discover_repositories(workspace, excluded)

    previous_by_path: dict[str, dict[str, Any]] = {}
    if state_path.exists() and not arguments.restart:
        previous = load_state(state_path)
        previous_by_path = {
            item["path"]: item
            for item in previous.get("repositories", [])
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        }
    elif state_path.exists():
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = state_path.with_name(f"{state_path.name}.{timestamp}.bak")
        shutil.copy2(state_path, backup)
        print(f"Previous campaign state copied to {backup}", file=sys.stderr)

    records: list[dict[str, Any]] = []
    for repository in repositories:
        record = previous_by_path.get(str(repository), repository_record(repository))
        record = {**repository_record(repository), **record, "name": repository.name, "path": str(repository)}
        record["attempts"] = int(record.get("attempts", 0))
        if record.get("status") == "running":
            baseline = record.pop("safety_baseline", None)
            current = safety_snapshot(repository) if isinstance(baseline, dict) else {}
            changed = sorted(
                path for path in set(baseline or {}) | set(current)
                if (baseline or {}).get(path) != current.get(path)
            )
            record["status"] = "failed"
            record["completed_at"] = utc_now()
            if changed:
                record["attempts"] = MAX_ATTEMPTS
                record["changed_outside_scope"] = changed
                record["last_message"] = (
                    "Прерванная сессия изменила файлы вне project-context.yaml и docs/usage/*.md."
                )
            else:
                record["last_message"] = "Предыдущая сессия прервалась во время попытки."
        records.append(record)

    state = {
        "schema_version": SCHEMA_VERSION,
        "workspace": str(workspace),
        "exclude_file": str(exclude_path) if exclude_path else None,
        "max_attempts_per_repository": MAX_ATTEMPTS,
        "updated_at": utc_now(),
        "repositories": records,
    }
    save_state(state_path, state)
    print(json.dumps(summary(state), ensure_ascii=False))
    return 0


def find_record(state: dict[str, Any], repository: str) -> dict[str, Any]:
    expected = canonical(repository)
    for record in state.get("repositories", []):
        if canonical(record.get("path", "")) == expected:
            return record
    raise SystemExit(f"Repository is not present in campaign state: {expected}")


def is_eligible(record: dict[str, Any]) -> bool:
    return record.get("status") != "successful" and int(record.get("attempts", 0)) < MAX_ATTEMPTS


def command_next(arguments: argparse.Namespace) -> int:
    state = load_state(Path(arguments.state).expanduser().resolve())
    for record in state.get("repositories", []):
        if is_eligible(record):
            result = {**record, "next_attempt": int(record.get("attempts", 0)) + 1}
            print(json.dumps(result, ensure_ascii=False))
            return 0
    print("NO_ELIGIBLE_REPOSITORIES")
    return 10


def command_start(arguments: argparse.Namespace) -> int:
    state_path = Path(arguments.state).expanduser().resolve()
    state = load_state(state_path)
    record = find_record(state, arguments.repository)
    attempts = int(record.get("attempts", 0))
    if record.get("status") == "successful":
        raise SystemExit(f"Repository is already successful: {record['path']}")
    if attempts >= MAX_ATTEMPTS:
        raise SystemExit(f"Attempt limit ({MAX_ATTEMPTS}) reached: {record['path']}")
    record.update({
        "status": "running",
        "attempts": attempts + 1,
        "started_at": utc_now(),
        "completed_at": None,
        "last_message": "",
        "changed_outside_scope": [],
        "safety_baseline": safety_snapshot(Path(record["path"])),
    })
    save_state(state_path, state)
    print(json.dumps(record, ensure_ascii=False))
    return 0


def command_finish(arguments: argparse.Namespace) -> int:
    state_path = Path(arguments.state).expanduser().resolve()
    state = load_state(state_path)
    record = find_record(state, arguments.repository)
    if record.get("status") != "running":
        raise SystemExit(f"Repository does not have a running attempt: {record['path']}")
    repository = Path(record["path"])
    baseline = record.get("safety_baseline")
    if not isinstance(baseline, dict):
        raise SystemExit(f"Safety baseline is missing for running repository: {record['path']}")
    current = safety_snapshot(repository)
    changed = sorted(
        path for path in set(baseline) | set(current)
        if baseline.get(path) != current.get(path)
    )
    record.pop("safety_baseline", None)
    if changed:
        record.update({
            "status": "failed",
            "attempts": MAX_ATTEMPTS,
            "completed_at": utc_now(),
            "last_message": "Safety violation: изменены файлы вне project-context.yaml и docs/usage/*.md.",
            "changed_outside_scope": changed,
        })
        save_state(state_path, state)
        print(json.dumps(record, ensure_ascii=False))
        return 6
    record.update({
        "status": arguments.status,
        "completed_at": utc_now(),
        "last_message": arguments.message or "",
        "changed_outside_scope": [],
    })
    save_state(state_path, state)
    print(json.dumps(record, ensure_ascii=False))
    return 0


def summary(state: dict[str, Any]) -> dict[str, int]:
    records = state.get("repositories", [])
    return {
        "total": len(records),
        "pending": sum(item.get("status") == "pending" for item in records),
        "running": sum(item.get("status") == "running" for item in records),
        "successful": sum(item.get("status") == "successful" for item in records),
        "retryable_failed": sum(item.get("status") == "failed" and is_eligible(item) for item in records),
        "terminal_failed": sum(
            item.get("status") == "failed" and int(item.get("attempts", 0)) >= MAX_ATTEMPTS
            for item in records
        ),
    }


def command_report(arguments: argparse.Namespace) -> int:
    state = load_state(Path(arguments.state).expanduser().resolve())
    print(json.dumps(summary(state), ensure_ascii=False, indent=2))
    return 0


def command_list(arguments: argparse.Namespace) -> int:
    state = load_state(Path(arguments.state).expanduser().resolve())
    for record in state.get("repositories", []):
        if arguments.status == "all" or record.get("status") == arguments.status:
            print(record["path"])
    return 0


def command_invalidate(arguments: argparse.Namespace) -> int:
    state_path = Path(arguments.state).expanduser().resolve()
    state = load_state(state_path)
    record = find_record(state, arguments.repository)
    if record.get("status") != "successful":
        raise SystemExit(f"Only a successful repository can be invalidated: {record['path']}")
    record.update({
        "status": "failed",
        "completed_at": utc_now(),
        "last_message": arguments.message,
    })
    save_state(state_path, state)
    print(json.dumps(record, ensure_ascii=False))
    return 0


def command_check(arguments: argparse.Namespace) -> int:
    state = load_state(Path(arguments.state).expanduser().resolve())
    result = summary(state)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["pending"] or result["running"] or result["retryable_failed"]:
        return 4
    if result["terminal_failed"]:
        return 5
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    subparsers = result.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init")
    init.add_argument("--workspace", required=True)
    init.add_argument("--state", required=True)
    init.add_argument("--exclude-file")
    init.add_argument("--restart", action="store_true")
    init.set_defaults(handler=command_init)

    for name, handler in (("next", command_next), ("report", command_report), ("check", command_check)):
        command = subparsers.add_parser(name)
        command.add_argument("--state", required=True)
        command.set_defaults(handler=handler)

    start = subparsers.add_parser("start")
    start.add_argument("--state", required=True)
    start.add_argument("--repository", required=True)
    start.set_defaults(handler=command_start)

    finish = subparsers.add_parser("finish")
    finish.add_argument("--state", required=True)
    finish.add_argument("--repository", required=True)
    finish.add_argument("--status", required=True, choices=("successful", "failed"))
    finish.add_argument("--message", default="")
    finish.set_defaults(handler=command_finish)

    list_command = subparsers.add_parser("list")
    list_command.add_argument("--state", required=True)
    list_command.add_argument(
        "--status",
        default="all",
        choices=("all", "pending", "running", "successful", "failed"),
    )
    list_command.set_defaults(handler=command_list)

    invalidate = subparsers.add_parser("invalidate")
    invalidate.add_argument("--state", required=True)
    invalidate.add_argument("--repository", required=True)
    invalidate.add_argument("--message", required=True)
    invalidate.set_defaults(handler=command_invalidate)
    return result


def main() -> None:
    arguments = parser().parse_args()
    raise SystemExit(arguments.handler(arguments))


if __name__ == "__main__":
    main()
