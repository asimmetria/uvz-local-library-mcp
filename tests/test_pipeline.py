import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dependency_graph import find_alias_usages, parse_version_catalog  # noqa: E402
from knowledge_indexer import chunks, redact, sync_progress  # noqa: E402
from knowledge_schema import KnowledgeSchemaError, SCHEMA_VERSION, create_schema, validate_database  # noqa: E402
from project_context import validate_card  # noqa: E402
from retrieval_evaluator import evaluate_dependency_graph  # noqa: E402
import server as server_module  # noqa: E402
from server import query  # noqa: E402

try:  # noqa: E402
    import tomllib as toml
except ImportError:  # noqa: E402
    import tomli as toml


class KnowledgePipelineTest(unittest.TestCase):
    def run_script(self, name, *arguments, cwd=None, check=True):
        return subprocess.run(
            [sys.executable, str(ROOT / name), *map(str, arguments)],
            cwd=str(cwd or ROOT),
            text=True,
            capture_output=True,
            check=check,
        )

    def test_line_ranges_and_dotted_secret_redaction(self):
        content = "\n\npackage demo\n\nclass Example {\n    fun fetch() = Unit\n}\n"
        indexed = chunks(content, "kotlin")
        self.assertEqual([(3, 7)], [(start, end) for _, start, end in indexed])
        redacted = redact(
            "spring.datasource.username=test\nspring.datasource.password=real-secret\n",
            "properties",
        )
        self.assertIn("spring.datasource.password= <redacted>", redacted)
        self.assertNotIn("real-secret", redacted)
        self.assertEqual('"sbertone-adapter" "SaveMode" "INSERT"', query("sbertone-adapter SaveMode.INSERT"))
        large = (
            "class First {\n"
            + "    val first = 1\n" * 12
            + "}\n\n"
            + "class Second {\n"
            + "    val second = 2\n" * 12
            + "}\n"
        )
        split = chunks(large, "kotlin", max_chars=180)
        self.assertGreater(len(split), 1)
        self.assertTrue(any(part.startswith("class Second") for part, _, _ in split))
        self.assertEqual(
            "sync_skipped_dirty (sync skipped; indexing current dirty working tree)",
            sync_progress("sync_skipped_dirty"),
        )
        self.assertEqual("synced", sync_progress("synced"))

    def test_workspace_build_rejects_repository_without_commit_before_indexing(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            repository = workspace / "empty-repository"
            repository.mkdir(parents=True)
            subprocess.run(
                ["git", "init", str(repository)], check=True, capture_output=True
            )
            cases = Path(directory) / "evaluation-cases.json"
            cases.write_text('{"version": 1, "cases": []}', encoding="utf-8")
            result = self.run_script(
                "build_workspace.py",
                workspace,
                "--evaluation-cases", cases,
                check=False,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("empty-repository", result.stderr)
            self.assertIn("no valid Git HEAD", result.stderr)
            self.assertNotIn("[1/1]", result.stdout)

    def test_authoring_worktree_check_ignores_generated_caches_only(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory) / "fixture"
            repository.mkdir()
            subprocess.run(["git", "init", str(repository)], check=True, capture_output=True)
            (repository / "settings.gradle.kts").write_text(
                'rootProject.name = "fixture"\n', encoding="utf-8"
            )
            subprocess.run(
                ["git", "-C", str(repository), "add", "settings.gradle.kts"],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "git", "-C", str(repository),
                    "-c", "user.name=Fixture",
                    "-c", "user.email=fixture@example.invalid",
                    "commit", "-m", "Fixture",
                ],
                check=True,
                capture_output=True,
            )
            cache = repository / "nested/.gradle/buildOutputCleanup/cache.properties"
            cache.parent.mkdir(parents=True)
            cache.write_text("generated=true\n", encoding="utf-8")
            check_script = (
                ROOT / "skills/project-context-authoring/scripts/check-authoring-worktree.sh"
            )
            generated_only = subprocess.run(
                ["bash", str(check_script), str(repository)],
                text=True,
                capture_output=True,
            )
            self.assertEqual(0, generated_only.returncode, generated_only.stdout)

            source = repository / "src/main/kotlin/demo/Changed.kt"
            source.parent.mkdir(parents=True)
            source.write_text("class Changed\n", encoding="utf-8")
            source_change = subprocess.run(
                ["bash", str(check_script), str(repository)],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(0, source_change.returncode)
            self.assertIn("src/main/kotlin/demo/Changed.kt", source_change.stdout)

    def test_single_authoring_runner_uses_non_interactive_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "fixture"
            repository.mkdir()
            (repository / "README.md").write_text(
                "# Fixture\n\nТестовый проект.\n", encoding="utf-8"
            )
            subprocess.run(["git", "init", str(repository)], check=True, capture_output=True)
            subprocess.run(
                ["git", "-C", str(repository), "add", "README.md"],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "git", "-C", str(repository),
                    "-c", "user.name=Fixture",
                    "-c", "user.email=fixture@example.invalid",
                    "commit", "-m", "Fixture",
                ],
                check=True,
                capture_output=True,
            )
            fake_bin = root / "bin"
            fake_bin.mkdir()
            invocation = root / "gigacode-args.json"
            fake_gigacode = fake_bin / "gigacode"
            fake_gigacode.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "Path(os.environ['FAKE_GIGACODE_ARGS']).write_text(json.dumps(sys.argv[1:]), encoding='utf-8')\n"
                "Path('project-context.yaml').write_text(\n"
                "    'schema_version: 1\\n'\n"
                "    'kind: application\\n'\n"
                "    'name: fixture\\n'\n"
                "    'purpose: \"Описывает тестовое приложение.\"\\n'\n"
                "    'use_when:\\n  - \"Нужно проверить non-interactive runner.\"\\n'\n"
                "    'evidence:\\n  - path: README.md\\n    proves: \"Подтверждает назначение.\"\\n',\n"
                "    encoding='utf-8',\n"
                ")\n",
                encoding="utf-8",
            )
            fake_gigacode.chmod(0o755)
            environment = os.environ.copy()
            environment.update({
                "PATH": str(fake_bin) + os.pathsep + environment.get("PATH", ""),
                "FAKE_GIGACODE_ARGS": str(invocation),
                "PROJECT_CONTEXT_OUTPUT_FORMAT": "text",
                "PYTHON_BIN": sys.executable,
            })
            runner = ROOT / "skills/project-context-authoring/scripts/run-project-context.sh"
            result = subprocess.run(
                ["bash", str(runner), str(repository)],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            arguments = json.loads(invocation.read_text(encoding="utf-8"))
            self.assertIn("--exclude-tools", arguments)
            self.assertIn("agent", arguments)
            self.assertIn("run_shell_command", arguments)
            self.assertEqual("-p", arguments[-2])
            self.assertIn("$project-context-authoring", arguments[-1])

    def test_structured_catalog_and_comment_free_usage_extraction(self):
        catalog = parse_version_catalog(
            '[versions]\nfixture = "1.2.3"\nstrict = { strictly = "4.0" }\n\n'
            '[libraries]\n'
            'fixtureLibrary = { module = "com.example:fixture-library", version.ref = "fixture" }\n'
            'fixture-test-kit = { group = "com.example", name = "fixture-test-kit", version = "2.0" }\n'
            'nested.adapter = { module = "com.example:nested-adapter" }\n'
            'strictLibrary = { module = "com.example:strict-library", version.ref = "strict" }\n'
            'legacy = "com.example:legacy-lib:3.0"\n',
            toml,
        )
        by_alias = {item["alias"]: item for item in catalog}
        self.assertEqual("1.2.3", by_alias["fixtureLibrary"]["version_value"])
        self.assertEqual("fixture.test.kit", by_alias["fixture-test-kit"]["accessor"])
        self.assertEqual("nested.adapter", by_alias["nested.adapter"]["accessor"])
        self.assertEqual("4.0", by_alias["strictLibrary"]["version_value"])
        self.assertEqual("3.0", by_alias["legacy"]["version_value"])
        usages = find_alias_usages(
            "dependencies {\n"
            "  implementation(libs.fixtureLibrary)\n"
            "  implementation(libs.bundles.fixture)\n"
            "  // api(libs.commentOnly)\n"
            "  val documentation = \"libs.stringOnly\"\n"
            "  /* runtimeOnly(libs.blockCommentOnly) */\n"
            "  testImplementation(platform(libs.fixtureBom))\n"
            "  runtimeOnly libs.legacyRuntime\n"
            "  implementation(\n"
            "    platform(\n"
            "      libs.multilineBom\n"
            "    )\n"
            "  )\n"
            "  customBucket(\n"
            "    libs.customLibrary\n"
            "  )\n"
            "  add(\n"
            "    \"integrationTestImplementation\",\n"
            "    libs.integrationSupport\n"
            "  )\n"
            "}\n"
        )
        self.assertEqual(
            [
                {"accessor": "fixtureLibrary", "configuration": "implementation", "line": 2},
                {"accessor": "fixtureBom", "configuration": "testImplementation", "line": 7},
                {"accessor": "legacyRuntime", "configuration": "runtimeOnly", "line": 8},
                {"accessor": "multilineBom", "configuration": "implementation", "line": 11},
                {"accessor": "customLibrary", "configuration": "customBucket", "line": 15},
                {"accessor": "integrationSupport", "configuration": "integrationTestImplementation", "line": 19},
            ],
            usages,
        )

    def test_old_schema_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "old.db"
            connection = sqlite3.connect(database)
            connection.execute("CREATE TABLE chunks (source_id TEXT, content TEXT)")
            connection.commit()
            connection.close()
            with self.assertRaises(KnowledgeSchemaError):
                validate_database(database)

    def test_dependency_graph_gate_requires_real_matching_consumers(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        create_schema(connection)
        connection.execute(
            "INSERT INTO dependency_aliases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "fixture", "uvz-platform", "gradle/libs.versions.toml", "a" * 40,
                "fixtureLibrary", "fixtureLibrary", "com.example", "fixture-library",
                "fixture", "1.0", "fixture-project", ":",
            ),
        )
        connection.execute(
            "INSERT INTO dependency_usages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "fixture", "uvz-platform", "gradle/libs.versions.toml",
                "fixtureLibrary", "fixtureLibrary", "fixture-consumer", ":api",
                "api/build.gradle.kts", "implementation", "b" * 40, 12,
            ),
        )
        good_case = {
            "id": "fixture-consumer",
            "query": "fixture library",
            "expected_aliases": ["fixtureLibrary"],
            "expected_consumers": [{
                "repository": "fixture-consumer",
                "module": ":api",
                "path": "api/build.gradle.kts",
                "configuration": "implementation",
            }],
        }
        below_minimum = evaluate_dependency_graph(connection, {
            "thresholds": {"min_dependency_cases": 2},
            "dependency_cases": [good_case],
        })
        self.assertFalse(below_minimum["passed"])
        wrong_consumer = evaluate_dependency_graph(connection, {
            "thresholds": {"min_dependency_cases": 1},
            "dependency_cases": [{
                **good_case,
                "expected_consumers": [{"repository": "another-consumer"}],
            }],
        })
        self.assertFalse(wrong_consumer["passed"])
        verified = evaluate_dependency_graph(connection, {
            "thresholds": {"min_dependency_cases": 1},
            "dependency_cases": [good_case],
        })
        self.assertTrue(verified["passed"])
        self.assertTrue(verified["results"][0]["provenance_valid"])
        connection.close()

    def test_one_agent_authoring_campaign_includes_dirty_and_tracks_every_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "projects"
            clean = workspace / "clean-project"
            dirty = workspace / "dirty-project"
            excluded = workspace / "excluded-project"
            authoring_excluded = workspace / "authoring-excluded-project"
            for project in (clean, dirty, excluded, authoring_excluded):
                project.mkdir(parents=True)
                (project / "README.md").write_text(
                    "# Fixture\n\nТестовый проект.\n", encoding="utf-8"
                )
                subprocess.run(["git", "init", str(project)], check=True, capture_output=True)
                subprocess.run(["git", "-C", str(project), "add", "."], check=True)
                subprocess.run(
                    [
                        "git", "-C", str(project),
                        "-c", "user.name=Fixture",
                        "-c", "user.email=fixture@example.invalid",
                        "commit", "-m", "Fixture",
                    ],
                    check=True,
                    capture_output=True,
                )
            dirty_text = "# Fixture\n\nНезавершённое изменение пользователя.\n"
            (dirty / "README.md").write_text(dirty_text, encoding="utf-8")
            exclude_file = root / "index-exclude.txt"
            exclude_file.write_text("excluded-project\n", encoding="utf-8")
            authoring_exclude_file = root / "project-context-exclude.txt"
            authoring_exclude_file.write_text(
                "authoring-excluded-project\n", encoding="utf-8"
            )

            fake_bin = root / "bin"
            fake_bin.mkdir()
            calls = root / "gigacode-calls.jsonl"
            fake_gigacode = fake_bin / "gigacode"
            fake_gigacode.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, subprocess, sys\n"
                "from pathlib import Path\n"
                "with Path(os.environ['FAKE_GIGACODE_CALLS']).open('a', encoding='utf-8') as out:\n"
                "    out.write(json.dumps({'cwd': str(Path.cwd()), 'args': sys.argv[1:]}, ensure_ascii=False) + '\\n')\n"
                "tool = os.environ['FAKE_CAMPAIGN_TOOL']\n"
                "state = os.environ['PROJECT_CONTEXT_STATE_FILE']\n"
                "while True:\n"
                "    next_run = subprocess.run([sys.executable, tool, 'next', '--state', state], text=True, capture_output=True)\n"
                "    if next_run.returncode == 10:\n"
                "        break\n"
                "    item = json.loads(next_run.stdout)\n"
                "    repository = Path(item['path'])\n"
                "    subprocess.run([sys.executable, tool, 'start', '--state', state, '--repository', str(repository)], check=True)\n"
                "    (repository / 'project-context.yaml').write_text('fixture', encoding='utf-8')\n"
                "    subprocess.run([sys.executable, tool, 'finish', '--state', state, '--repository', str(repository), '--status', 'successful'], check=True)\n"
                "print('fake primary agent completed')\n",
                encoding="utf-8",
            )
            fake_gigacode.chmod(0o755)
            fake_site = root / "fake-site"
            fake_site.mkdir()
            (fake_site / "yaml.py").write_text(
                "def safe_load(_text):\n"
                "    return {\n"
                "        'schema_version': 1,\n"
                "        'kind': 'application',\n"
                "        'name': 'fixture',\n"
                "        'purpose': 'Описывает тестовое приложение.',\n"
                "        'use_when': ['Нужно проверить безопасную кампанию.'],\n"
                "        'evidence': [{'path': 'README.md', 'proves': 'Подтверждает назначение проекта.'}],\n"
                "    }\n",
                encoding="utf-8",
            )
            state = root / "authoring-campaign.json"
            state_tool = ROOT / "skills/project-context-authoring/scripts/project-context-campaign-state.py"
            environment = os.environ.copy()
            environment.update({
                "PATH": str(fake_bin) + os.pathsep + environment.get("PATH", ""),
                "FAKE_GIGACODE_CALLS": str(calls),
                "FAKE_CAMPAIGN_TOOL": str(state_tool),
                "PROJECT_CONTEXT_STATE_FILE": str(state),
                "PROJECT_CONTEXT_OUTPUT_FORMAT": "text",
                "INDEX_EXCLUDE_FILE": str(exclude_file),
                "PROJECT_CONTEXT_EXCLUDE_FILE": str(authoring_exclude_file),
                "PYTHON_BIN": sys.executable,
                "PYTHONPATH": str(fake_site),
            })
            runner = ROOT / "skills/project-context-authoring/scripts/run-all-project-contexts.sh"
            result = subprocess.run(
                ["bash", str(runner), str(workspace)],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            invocations = [json.loads(line) for line in calls.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(1, len(invocations))
            self.assertEqual(workspace.resolve(), Path(invocations[0]["cwd"]).resolve())
            arguments = invocations[0]["args"]
            self.assertIn("--approval-mode=auto-edit", arguments)
            self.assertIn("--exclude-tools", arguments)
            self.assertIn("agent", arguments)
            self.assertIn("run_shell_command", arguments)
            self.assertIn("mcp__local-library-mcp__project_context_campaign_finish", arguments)
            self.assertIn("mcp__local-library-mcp__validate_project_context", arguments)
            self.assertEqual("-p", arguments[-2])
            self.assertIn("$project-context-authoring", arguments[-1])
            campaign = json.loads(state.read_text(encoding="utf-8"))
            records = {item["name"]: item for item in campaign["repositories"]}
            self.assertEqual({"clean-project", "dirty-project"}, set(records))
            self.assertTrue(all(item["status"] == "successful" for item in records.values()))
            self.assertTrue(all(item["attempts"] == 1 for item in records.values()))
            self.assertEqual(dirty_text, (dirty / "README.md").read_text(encoding="utf-8"))
            self.assertFalse((excluded / "project-context.yaml").exists())
            self.assertFalse((authoring_excluded / "project-context.yaml").exists())

    def test_authoring_campaign_enforces_two_attempts_and_safety_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "projects"
            retry = workspace / "retry-project"
            unsafe = workspace / "unsafe-project"
            validation = workspace / "validation-project"
            interrupted = workspace / "interrupted-project"
            for project in (retry, unsafe, validation, interrupted):
                project.mkdir(parents=True)
                (project / "README.md").write_text("# Fixture\n", encoding="utf-8")
                subprocess.run(["git", "init", str(project)], check=True, capture_output=True)
                subprocess.run(["git", "-C", str(project), "add", "."], check=True)
                subprocess.run(
                    [
                        "git", "-C", str(project),
                        "-c", "user.name=Fixture",
                        "-c", "user.email=fixture@example.invalid",
                        "commit", "-m", "Fixture",
                    ],
                    check=True,
                    capture_output=True,
                )
            state = root / "campaign.json"
            tool = ROOT / "skills/project-context-authoring/scripts/project-context-campaign-state.py"

            def campaign(*arguments, check=True):
                return subprocess.run(
                    [sys.executable, str(tool), *map(str, arguments)],
                    text=True,
                    capture_output=True,
                    check=check,
                )

            campaign("init", "--workspace", workspace, "--state", state)
            campaign("start", "--state", state, "--repository", retry)
            blocked_next = campaign("next", "--state", state, check=False)
            self.assertEqual(11, blocked_next.returncode)
            self.assertIn("ACTIVE_REPOSITORY_MUST_BE_FINISHED", blocked_next.stdout)
            blocked_start = campaign(
                "start", "--state", state, "--repository", unsafe, check=False
            )
            self.assertNotEqual(0, blocked_start.returncode)
            self.assertIn("Finish the active repository", blocked_start.stderr)
            campaign(
                "finish", "--state", state, "--repository", retry,
                "--status", "failed", "--message", "attempt 1",
            )
            campaign("start", "--state", state, "--repository", retry)
            campaign(
                "finish", "--state", state, "--repository", retry,
                "--status", "failed", "--message", "attempt 2",
            )
            third = campaign(
                "start", "--state", state, "--repository", retry, check=False
            )
            self.assertNotEqual(0, third.returncode)
            self.assertIn("Attempt limit (2) reached", third.stderr)

            campaign("start", "--state", state, "--repository", unsafe)
            (unsafe / "README.md").write_text("# Unauthorized change\n", encoding="utf-8")
            finish = campaign(
                "finish", "--state", state, "--repository", unsafe,
                "--status", "successful", check=False,
            )
            self.assertEqual(6, finish.returncode)
            records = {
                item["name"]: item
                for item in json.loads(state.read_text(encoding="utf-8"))["repositories"]
            }
            self.assertEqual("failed", records["unsafe-project"]["status"])
            self.assertEqual(2, records["unsafe-project"]["attempts"])
            self.assertEqual(["README.md"], records["unsafe-project"]["changed_outside_scope"])

            campaign("start", "--state", state, "--repository", validation)
            (validation / "project-context.yaml").write_text(
                "schema_version: 1\n"
                "kind: application\n"
                "name: validation-project\n"
                "purpose: \"Проверяет validator feedback.\"\n"
                "use_when:\n"
                "  - Ошибочная строка: превращается в mapping\n"
                "evidence:\n"
                "  - path: README.md\n"
                "    proves: \"Подтверждает fixture.\"\n",
                encoding="utf-8",
            )
            validation_result = server_module.call_tool(
                "validate_project_context", {"repository": str(validation)}
            )[0]["text"]
            self.assertIn("VALIDATION_FAILED", validation_result)
            self.assertIn("use_when must contain only non-empty strings", validation_result)
            campaign(
                "finish", "--state", state, "--repository", validation,
                "--status", "successful",
            )
            campaign(
                "invalidate", "--state", state, "--repository", validation,
                "--message", "Deterministic validation failed after the agent session. use_when error",
            )
            reset = campaign("reset-validation-failures", "--state", state)
            self.assertEqual(1, json.loads(reset.stdout)["reset"])
            records = {
                item["name"]: item
                for item in json.loads(state.read_text(encoding="utf-8"))["repositories"]
            }
            self.assertEqual("pending", records["validation-project"]["status"])
            self.assertEqual(0, records["validation-project"]["attempts"])
            self.assertEqual(1, records["validation-project"]["repair_resets"])

            campaign("start", "--state", state, "--repository", interrupted)
            campaign("init", "--workspace", workspace, "--state", state)
            records = {
                item["name"]: item
                for item in json.loads(state.read_text(encoding="utf-8"))["repositories"]
            }
            self.assertEqual("failed", records["interrupted-project"]["status"])
            self.assertEqual(
                "Предыдущая сессия прервалась во время попытки.",
                records["interrupted-project"]["last_message"],
            )
            repaired = campaign("reset-interrupted-failures", "--state", state)
            self.assertEqual(1, json.loads(repaired.stdout)["reset"])
            records = {
                item["name"]: item
                for item in json.loads(state.read_text(encoding="utf-8"))["repositories"]
            }
            self.assertEqual("pending", records["interrupted-project"]["status"])
            self.assertEqual(0, records["interrupted-project"]["attempts"])
            report = server_module.call_tool(
                "project_context_campaign_report", {"state_file": str(state)}
            )
            self.assertIn('"terminal_failed": 2', report[0]["text"])
            report_payload = json.loads(report[0]["text"])
            failed_by_name = {
                item["name"]: item
                for item in report_payload["failed_repositories"]
            }
            self.assertEqual(
                {"retry-project", "unsafe-project"}, set(failed_by_name)
            )
            self.assertEqual("attempt 2", failed_by_name["retry-project"]["last_message"])
            self.assertTrue(failed_by_name["retry-project"]["terminal"])
            self.assertEqual(2, failed_by_name["unsafe-project"]["attempts"])

    def test_project_context_rejects_non_portable_or_missing_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            card = {
                "schema_version": 1,
                "kind": "library",
                "name": "fixture-library",
                "purpose": "Предоставляет тестовый API.",
                "use_when": ["Нужно проверить интеграцию."],
                "evidence": [
                    {"path": "/home/user/Fixture.kt", "proves": "Подтверждает API."},
                    {"path": "missing.kt", "proves": "Подтверждает API."},
                ],
            }
            errors = validate_card(card, root)
            self.assertTrue(any("absolute local path" in error for error in errors))
            self.assertTrue(any("does not exist" in error for error in errors))

    def test_build_verify_package_and_install(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            source = workspace / "fixture-project"
            kotlin = source / "src/main/kotlin/demo/Example.kt"
            properties = source / "src/main/resources/application.properties"
            kotlin.parent.mkdir(parents=True)
            properties.parent.mkdir(parents=True)
            docs = source / "docs"
            usage = docs / "usage"
            usage.mkdir(parents=True)
            (source / "settings.gradle.kts").write_text('rootProject.name = "fixture-project"\n', encoding="utf-8")
            (source / "build.gradle.kts").write_text(
                "dependencies {\n"
                "    implementation(libs.fixtureLibrary)\n"
                "    api(libs.helperAdapter.get())\n"
                "    testImplementation(libs.fixtureTestKit)\n"
                "    // runtimeOnly(libs.ignoredAlias)\n"
                "    val sample = \"libs.ignoredAlias\"\n"
                "}\n",
                encoding="utf-8",
            )
            legacy_build = source / "legacy/build.gradle"
            legacy_build.parent.mkdir()
            legacy_build.write_text(
                "dependencies {\n    runtimeOnly libs.helperAdapter\n}\n",
                encoding="utf-8",
            )
            kotlin.write_text(
                "\n\npackage demo\n\nclass Example {\n    fun fetchItems(): List<String> = emptyList()\n}\n",
                encoding="utf-8",
            )
            properties.write_text(
                "spring.datasource.username=test\nspring.datasource.password=real-secret\n",
                encoding="utf-8",
            )
            duplicate = "# Duplicate fixture\n\nDuplicateFixtureKnowledge demonstrates deterministic duplicate suppression.\n"
            (docs / "copy-a.md").write_text(duplicate, encoding="utf-8")
            (docs / "copy-b.md").write_text(duplicate, encoding="utf-8")
            (docs / "multi.md").write_text(
                "# First section\n\nFirstSectionMarker " + "first " * 20
                + "\n\n# Second section\n\nSecondSectionMarker " + "second " * 20 + "\n",
                encoding="utf-8",
            )
            (usage / "fetch-items.md").write_text(
                "# Получение данных Fixture\n\n"
                "## Когда использовать\n\nНужно получить данные Fixture через публичный Example API.\n\n"
                "## Зависимость\n\nДля fixture не требуется внешняя зависимость.\n\n"
                "## Минимальный пример\n\n`Example().fetchItems()` возвращает список строк.\n\n"
                "## Обязательная конфигурация\n\nДополнительная конфигурация не требуется.\n\n"
                "## Ожидаемый результат\n\nВозвращается список строк.\n\n"
                "## Ограничения и типичные ошибки\n\nИспользуй публичный класс `Example`.\n\n"
                "## Evidence\n\n- `src/main/kotlin/demo/Example.kt` — подтверждает публичный вызов.\n",
                encoding="utf-8",
            )
            (source / "project-context.yaml").write_text(
                "schema_version: 1\n"
                "kind: library\n"
                "name: fixture-library\n"
                "aliases:\n  - Fixture API\n"
                "modules:\n  - ':'\n"
                "purpose: Предоставляет тестовый API для получения данных Fixture.\n"
                "use_when:\n  - Нужно получить данные Fixture из другого модуля.\n"
                "entrypoints:\n  - demo.Example\n"
                "examples:\n"
                "  - id: fetch-items\n"
                "    path: docs/usage/fetch-items.md\n"
                "    summary: Получение данных через публичный API.\n"
                "evidence:\n"
                "  - path: src/main/kotlin/demo/Example.kt\n"
                "    proves: Подтверждает публичную точку входа.\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "init", str(source)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(source), "add", "."], check=True, capture_output=True)
            subprocess.run(
                [
                    "git", "-C", str(source),
                    "-c", "user.name=Fixture",
                    "-c", "user.email=fixture@example.invalid",
                    "commit", "-m", "Fixture",
                ],
                check=True,
                capture_output=True,
            )
            validated_context = self.run_script("validate_project_contexts.py", source)
            self.assertIn("Validated 1 project context cards", validated_context.stdout)
            platform = workspace / "uvz-platform"
            platform_catalog = platform / "gradle/libs.versions.toml"
            platform_catalog.parent.mkdir(parents=True)
            platform_catalog.write_text(
                '[versions]\nfixture = "1.4.2"\n\n'
                '[libraries]\n'
                'fixtureLibrary = { module = "com.example:fixture-library", version.ref = "fixture" }\n'
                'helperAdapter = { module = "com.example:helper-adapter", version = "2.0" }\n'
                'fixtureTestKit = { group = "com.example", name = "fixture-test-kit", version.ref = "fixture" }\n'
                'ignoredAlias = { module = "com.example:ignored-alias" }\n',
                encoding="utf-8",
            )
            (platform / "settings.gradle.kts").write_text(
                'rootProject.name = "uvz-platform"\n', encoding="utf-8"
            )
            subprocess.run(["git", "init", str(platform)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(platform), "add", "."], check=True, capture_output=True)
            subprocess.run(
                [
                    "git", "-C", str(platform),
                    "-c", "user.name=Fixture",
                    "-c", "user.email=fixture@example.invalid",
                    "commit", "-m", "Fixture platform",
                ],
                check=True,
                capture_output=True,
            )
            build_output = workspace / "build-output"
            database = build_output / "knowledge.db"
            catalog = build_output / "skills/library-knowledge-workflow/generated-catalog.md"
            audit = build_output / "audit-summary.json"
            evaluation = build_output / "evaluation-summary.json"
            cases = workspace / "evaluation-cases.json"
            cases.write_text(json.dumps({
                "version": 1,
                "top_k": 5,
                "thresholds": {
                    "min_recall_at_k": 1.0,
                    "min_mrr": 1.0,
                    "min_negative_pass_rate": 1.0,
                    "min_dependency_cases": 3,
                    "min_dependency_pass_rate": 1.0,
                },
                "cases": [
                    {
                        "id": "fixture-fetch",
                        "query": "fetchItems",
                        "filters": {"path": "src/main/kotlin/demo/Example.kt"},
                        "expected_paths": ["src/main/kotlin/demo/Example.kt"],
                    },
                    {
                        "id": "fixture-dependency-implementation",
                        "query": "implementation libs.fixtureLibrary",
                        "expected_sources": ["fixture-project:build.gradle.kts"],
                    },
                    {
                        "id": "fixture-dependency-api",
                        "query": "api libs.helperAdapter",
                        "expected_sources": ["fixture-project:build.gradle.kts"],
                    },
                    {
                        "id": "fixture-dependency-test",
                        "query": "testImplementation libs.fixtureTestKit",
                        "expected_sources": ["fixture-project:build.gradle.kts"],
                    },
                    {
                        "id": "fixture-missing",
                        "query": "DefinitelyMissingFixtureSymbol",
                        "expect_no_results": True,
                    },
                ],
                "dependency_cases": [
                    {
                        "id": "fixture-library-consumer",
                        "query": "fixture library",
                        "expected_aliases": ["fixtureLibrary"],
                        "expected_consumers": [{
                            "alias": "fixtureLibrary",
                            "repository": "fixture-project",
                            "module": ":",
                            "path": "build.gradle.kts",
                            "configuration": "implementation",
                        }],
                    },
                    {
                        "id": "helper-adapter-consumer",
                        "query": "helper adapter",
                        "expected_aliases": ["helperAdapter"],
                        "expected_consumers": [{
                            "repository": "fixture-project",
                            "module": ":",
                            "path": "build.gradle.kts",
                            "configuration": "api",
                        }],
                    },
                    {
                        "id": "fixture-test-kit-consumer",
                        "query": "libs.fixtureTestKit",
                        "expected_aliases": ["fixtureTestKit"],
                        "expected_consumers": [{
                            "repository": "fixture-project",
                            "module": ":",
                            "path": "build.gradle.kts",
                            "configuration": "testImplementation",
                        }],
                    },
                    {
                        "id": "missing-dependency",
                        "query": "DefinitelyMissingDependencyAlias",
                        "expect_no_results": True,
                    },
                ],
            }), encoding="utf-8")
            self.run_script(
                "build_workspace.py",
                workspace,
                "--output-dir", build_output,
                "--evaluation-cases", cases,
            )
            dependency_draft = workspace / "evaluation-cases.local.json"
            self.run_script(
                "scripts/draft-dependency-cases.py",
                "--db", database,
                "--base", ROOT / "evaluation-cases.json",
                "--output", dependency_draft,
                "--limit", "3",
                "--include-external",
            )
            draft_definition = json.loads(dependency_draft.read_text(encoding="utf-8"))
            self.assertTrue(draft_definition["dependency_case_draft"]["review_required"])
            self.assertEqual(
                3, draft_definition["dependency_case_draft"]["generated_positive_cases"]
            )
            self.assertEqual(
                "all-aliases",
                draft_definition["dependency_case_draft"]["selection_scope"],
            )
            self.assertEqual(3, draft_definition["thresholds"]["min_dependency_cases"])
            self.assertEqual(
                {"fixtureLibrary", "fixtureTestKit", "helperAdapter"},
                {
                    case["expected_aliases"][0]
                    for case in draft_definition["dependency_cases"]
                },
            )
            draft_connection = sqlite3.connect(database)
            draft_connection.row_factory = sqlite3.Row
            try:
                unreviewed = evaluate_dependency_graph(draft_connection, draft_definition)
                self.assertFalse(unreviewed["review_acknowledged"])
                self.assertFalse(unreviewed["passed"])
                draft_definition["dependency_case_draft"]["review_required"] = False
                reviewed = evaluate_dependency_graph(draft_connection, draft_definition)
                self.assertTrue(reviewed["review_acknowledged"])
                self.assertTrue(reviewed["passed"])
            finally:
                draft_connection.close()
            original_draft = dependency_draft.read_bytes()
            refused_overwrite = self.run_script(
                "scripts/draft-dependency-cases.py",
                "--db", database,
                "--base", ROOT / "evaluation-cases.json",
                "--output", dependency_draft,
                "--limit", "3",
                check=False,
            )
            self.assertNotEqual(0, refused_overwrite.returncode)
            self.assertEqual(original_draft, dependency_draft.read_bytes())
            internal_draft = workspace / "evaluation-cases.internal.json"
            self.run_script(
                "scripts/draft-dependency-cases.py",
                "--db", database,
                "--base", ROOT / "evaluation-cases.json",
                "--output", internal_draft,
                "--limit", "1",
            )
            internal_definition = json.loads(internal_draft.read_text(encoding="utf-8"))
            self.assertEqual(
                "internally-owned-aliases",
                internal_definition["dependency_case_draft"]["selection_scope"],
            )
            self.assertEqual(
                ["fixtureLibrary"],
                internal_definition["dependency_cases"][0]["expected_aliases"],
            )
            self.assertEqual(SCHEMA_VERSION, validate_database(database))
            audit_report = json.loads(audit.read_text(encoding="utf-8"))
            self.assertEqual(1, audit_report["duplicate_content_groups"])
            self.assertEqual(1, audit_report["project_contexts_indexed"])
            self.assertEqual(0, audit_report["project_contexts_invalid"])
            self.assertEqual(1, audit_report["usage_documents_indexed"])
            self.assertEqual(4, audit_report["dependency_aliases_indexed"])
            self.assertEqual(4, audit_report["dependency_usages_indexed"])
            self.assertEqual(1, audit_report["dependency_aliases_with_owner"])
            self.assertEqual("knowledge.db", audit_report["database"])
            connection = sqlite3.connect(database)
            row = connection.execute(
                "SELECT line_start, line_end, content FROM chunks WHERE path LIKE '%Example.kt'"
            ).fetchone()
            secret_content = connection.execute(
                "SELECT content FROM chunks WHERE path LIKE '%application.properties'"
            ).fetchone()[0]
            curated_kinds = dict(connection.execute(
                "SELECT path, kind FROM chunks WHERE kind IN ('context', 'usage')"
            ).fetchall())
            dependency_alias = connection.execute(
                "SELECT group_id, artifact_id, version_ref, version_value, "
                "owner_repository, owner_module FROM dependency_aliases "
                "WHERE alias = 'fixtureLibrary'"
            ).fetchone()
            dependency_usages = connection.execute(
                "SELECT alias, configuration, line FROM dependency_usages ORDER BY path, line"
            ).fetchall()
            connection.close()
            self.assertEqual((3, 7), row[:2])
            self.assertNotIn("real-secret", secret_content)
            self.assertEqual("context", curated_kinds["project-context.yaml"])
            self.assertEqual("usage", curated_kinds["docs/usage/fetch-items.md"])
            self.assertEqual(
                ("com.example", "fixture-library", "fixture", "1.4.2", "fixture-project", ":"),
                dependency_alias,
            )
            self.assertEqual(
                [
                    ("fixtureLibrary", "implementation", 2),
                    ("helperAdapter", "api", 3),
                    ("fixtureTestKit", "testImplementation", 4),
                    ("helperAdapter", "runtimeOnly", 2),
                ],
                dependency_usages,
            )
            generated_catalog = catalog.read_text(encoding="utf-8")
            self.assertIn("fixture-library [library, curated]", generated_catalog)
            self.assertIn("Предоставляет тестовый API", generated_catalog)
            previous_database = server_module.DB_PATH
            server_module.DB_PATH = database
            try:
                suggestion = server_module.dependency_suggestion({"query": "fixture library"})
                self.assertIn("implementation(libs.fixtureLibrary)", suggestion)
                self.assertIn("com.example:fixture-library", suggestion)
                self.assertIn("fixture-project", suggestion)
                verified_usages = server_module.library_usages({"query": "libs.fixtureLibrary"})
                self.assertIn("fixture-project", verified_usages)
                self.assertIn("build.gradle.kts:2", verified_usages)
                self.assertNotIn("ignoredAlias", verified_usages)
                curated_results = server_module.search({"query": "получить данные Fixture", "limit": 5})
                self.assertLess(
                    curated_results.find("path: `project-context.yaml:"),
                    curated_results.find("path: `docs/usage/fetch-items.md:"),
                    curated_results,
                )
                duplicate_results = server_module.search({"query": "DuplicateFixtureKnowledge", "limit": 5})
                self.assertEqual(1, duplicate_results.count("source: `"))
                connection = sqlite3.connect(database)
                first_source = connection.execute(
                    "SELECT source_id FROM chunks WHERE path = 'docs/multi.md' ORDER BY source_id LIMIT 1"
                ).fetchone()[0]
                connection.close()
                exact_source = server_module.source({"source_id": first_source})
                self.assertIn("FirstSectionMarker", exact_source)
                self.assertNotIn("SecondSectionMarker", exact_source)
                whole_source = server_module.source({"source_id": first_source.split("#")[0]})
                self.assertIn("SecondSectionMarker", whole_source)
            finally:
                server_module.DB_PATH = previous_database
            report = json.loads(evaluation.read_text(encoding="utf-8"))
            self.assertTrue(report["passed"])
            self.assertEqual("evaluation-cases.built.json", report["retrieval_cases"])
            self.assertEqual(1.0, report["retrieval_evaluation"]["recall_at_k"])
            self.assertEqual(1.0, report["retrieval_evaluation"]["mrr"])
            self.assertEqual(4, report["dependency_graph_evaluation"]["cases"])
            self.assertEqual(1.0, report["dependency_graph_evaluation"]["pass_rate"])
            self.assertTrue(report["dependency_graph_evaluation"]["passed"])
            self.assertEqual(hashlib.sha256(database.read_bytes()).hexdigest(), report["database_sha256"])
            output = workspace / "dist"
            self.run_script(
                "package_pack.py",
                "--db", database,
                "--catalog", catalog,
                "--audit", audit,
                "--evaluation", evaluation,
                "--version", "test",
                "--output", output,
            )
            archive = output / "knowledge-pack-test.zip"
            with zipfile.ZipFile(archive) as packaged:
                manifest = json.loads(packaged.read("manifest.json"))
                packaged_audit = json.loads(packaged.read("audit-summary.json"))
                packaged_evaluation = json.loads(packaged.read("evaluation-summary.json"))
            self.assertEqual(SCHEMA_VERSION, manifest["schema_version"])
            self.assertEqual("fixture-project", manifest["sources"][0]["repository"])
            self.assertEqual("knowledge.db", packaged_audit["database"])
            self.assertEqual("knowledge.db", packaged_evaluation["database"])
            self.assertEqual("evaluation-cases.built.json", packaged_evaluation["retrieval_cases"])
            destination = workspace / "installed"
            self.run_script("install_pack.py", archive, "--destination", destination)
            self.assertEqual(SCHEMA_VERSION, validate_database(destination / "knowledge.db"))
            self.assertTrue((destination / "audit-summary.json").exists())
            self.assertTrue((destination / "evaluation-summary.json").exists())
            self.assertTrue((destination / "evaluation-cases.built.json").exists())
            for name in ("server.py", "knowledge_schema.py", "retrieval_evaluator.py"):
                shutil.copy2(ROOT / name, destination / name)
            self.run_script(
                "smoke_test.py",
                "--server", destination / "server.py",
                "--python", sys.executable,
            )
            installed_database = (destination / "knowledge.db").read_bytes()
            corrupt_archive = output / "knowledge-pack-corrupt.zip"
            with zipfile.ZipFile(archive) as source_pack, zipfile.ZipFile(corrupt_archive, "w") as corrupt_pack:
                for name in source_pack.namelist():
                    payload = source_pack.read(name)
                    if name == "generated-catalog.md":
                        payload += b"corrupt"
                    corrupt_pack.writestr(name, payload)
            failed_install = self.run_script(
                "install_pack.py",
                corrupt_archive,
                "--destination", destination,
                check=False,
            )
            self.assertNotEqual(0, failed_install.returncode)
            self.assertEqual(installed_database, (destination / "knowledge.db").read_bytes())

    def test_failed_build_preserves_existing_database(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            database = workspace / "knowledge.db"
            database.write_bytes(b"previous-good-index")
            result = self.run_script(
                "knowledge_indexer.py",
                "--pack", "fixture",
                "--source", workspace / "missing-source",
                "--db", database,
                "--catalog", workspace / "catalog.md",
                "--audit", workspace / "audit.json",
                check=False,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertEqual(b"previous-good-index", database.read_bytes())

    def test_failed_quality_gate_preserves_published_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "projects"
            source = workspace / "empty-project"
            (source / ".git").mkdir(parents=True)
            (source / "settings.gradle.kts").write_text("// too short\n", encoding="utf-8")
            output = root / "output"
            output.mkdir()
            database = output / "knowledge.db"
            database.write_bytes(b"previous-verified-index")
            result = self.run_script(
                "build_workspace.py",
                workspace,
                "--output-dir", output,
                check=False,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertEqual(b"previous-verified-index", database.read_bytes())


if __name__ == "__main__":
    unittest.main()
