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
from knowledge_indexer import chunks, redact  # noqa: E402
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

    def test_safe_sequential_authoring_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "projects"
            clean = workspace / "clean-project"
            dirty = workspace / "dirty-project"
            for project in (clean, dirty):
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
            (dirty / "README.md").write_text(
                "# Fixture\n\nНезавершённое изменение пользователя.\n", encoding="utf-8"
            )
            fake_bin = root / "bin"
            fake_bin.mkdir()
            calls = root / "gigacode-calls.jsonl"
            fake_gigacode = fake_bin / "gigacode"
            fake_gigacode.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "with Path(os.environ['FAKE_GIGACODE_CALLS']).open('a', encoding='utf-8') as out:\n"
                "    out.write(json.dumps({'cwd': str(Path.cwd()), 'args': sys.argv[1:]}, ensure_ascii=False) + '\\n')\n"
                "name = Path.cwd().name\n"
                "Path('project-context.yaml').write_text(\n"
                "    'schema_version: 1\\n'\n"
                "    'kind: application\\n'\n"
                "    f'name: {name}\\n'\n"
                "    'purpose: Описывает тестовое приложение.\\n'\n"
                "    'use_when:\\n  - Нужно проверить безопасный runner.\\n'\n"
                "    'evidence:\\n  - path: README.md\\n    proves: Подтверждает назначение проекта.\\n',\n"
                "    encoding='utf-8',\n"
                ")\n"
                "if os.environ.get('FAKE_GIGACODE_UNSAFE') == '1':\n"
                "    Path('README.md').write_text('# Unsafe\\n', encoding='utf-8')\n"
                "print('fake gigacode completed')\n",
                encoding="utf-8",
            )
            fake_gigacode.chmod(0o755)
            state = root / "authoring-state.tsv"
            logs = root / "logs"
            environment = os.environ.copy()
            environment.update({
                "PATH": str(fake_bin) + os.pathsep + environment.get("PATH", ""),
                "FAKE_GIGACODE_CALLS": str(calls),
                "PROJECT_CONTEXT_STATE_FILE": str(state),
                "PROJECT_CONTEXT_LOG_DIR": str(logs),
                "PROJECT_CONTEXT_OUTPUT_FORMAT": "text",
                "PYTHON_BIN": sys.executable,
            })
            runner = ROOT / "skills/project-context-authoring/scripts/run-all-project-contexts.sh"
            first = subprocess.run(
                ["bash", str(runner), str(workspace)],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
            )
            self.assertEqual(0, first.returncode, first.stdout + first.stderr)
            invocations = [json.loads(line) for line in calls.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(1, len(invocations))
            self.assertEqual(clean.resolve(), Path(invocations[0]["cwd"]).resolve())
            arguments = invocations[0]["args"]
            self.assertIn("--approval-mode=auto-edit", arguments)
            self.assertIn("--allowed-mcp-server-names", arguments)
            self.assertIn("mcp__local-library-mcp__suggest_dependency", arguments)
            self.assertIn("mcp__local-library-mcp__find_library_usages", arguments)
            self.assertIn("$project-context-authoring", arguments[-1])
            self.assertIn("SKIPPED_DIRTY", first.stdout)
            self.assertTrue((clean / "project-context.yaml").is_file())
            self.assertFalse((dirty / "project-context.yaml").exists())
            self.assertIn("successful", state.read_text(encoding="utf-8"))
            self.assertIn("skipped_dirty", state.read_text(encoding="utf-8"))
            second = subprocess.run(
                ["bash", str(runner), str(workspace)],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
            )
            self.assertEqual(0, second.returncode, second.stdout + second.stderr)
            self.assertIn("Уже успешно обработан", second.stdout)
            self.assertEqual(1, len(calls.read_text(encoding="utf-8").splitlines()))
            unsafe = root / "unsafe-project"
            unsafe.mkdir()
            (unsafe / "README.md").write_text("# Safe before agent\n", encoding="utf-8")
            subprocess.run(["git", "init", str(unsafe)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(unsafe), "add", "."], check=True)
            subprocess.run(
                [
                    "git", "-C", str(unsafe),
                    "-c", "user.name=Fixture",
                    "-c", "user.email=fixture@example.invalid",
                    "commit", "-m", "Fixture",
                ],
                check=True,
                capture_output=True,
            )
            unsafe_environment = {**environment, "FAKE_GIGACODE_UNSAFE": "1"}
            one_runner = ROOT / "skills/project-context-authoring/scripts/run-project-context.sh"
            unsafe_result = subprocess.run(
                ["bash", str(one_runner), str(unsafe)],
                cwd=ROOT,
                env=unsafe_environment,
                text=True,
                capture_output=True,
            )
            self.assertEqual(4, unsafe_result.returncode)
            self.assertIn("FAILED SAFETY CHECK", unsafe_result.stderr)
            self.assertIn(" M README.md", unsafe_result.stdout)

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
                        "expected_sources": ["fixture-project:src/main/kotlin/demo/Example.kt"],
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
            )
            draft_definition = json.loads(dependency_draft.read_text(encoding="utf-8"))
            self.assertTrue(draft_definition["dependency_case_draft"]["review_required"])
            self.assertEqual(
                3, draft_definition["dependency_case_draft"]["generated_positive_cases"]
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
