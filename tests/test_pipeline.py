import hashlib
import json
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

from knowledge_indexer import chunks, redact  # noqa: E402
from knowledge_schema import KnowledgeSchemaError, SCHEMA_VERSION, validate_database  # noqa: E402
from project_context import validate_card  # noqa: E402
import server as server_module  # noqa: E402
from server import query  # noqa: E402


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

    def test_old_schema_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "old.db"
            connection = sqlite3.connect(database)
            connection.execute("CREATE TABLE chunks (source_id TEXT, content TEXT)")
            connection.commit()
            connection.close()
            with self.assertRaises(KnowledgeSchemaError):
                validate_database(database)

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
                },
                "cases": [
                    {
                        "id": "fixture-fetch",
                        "query": "fetchItems",
                        "expected_sources": ["fixture-project:src/main/kotlin/demo/Example.kt"],
                    },
                    {
                        "id": "fixture-missing",
                        "query": "DefinitelyMissingFixtureSymbol",
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
            self.assertEqual(SCHEMA_VERSION, validate_database(database))
            audit_report = json.loads(audit.read_text(encoding="utf-8"))
            self.assertEqual(1, audit_report["duplicate_content_groups"])
            self.assertEqual(1, audit_report["project_contexts_indexed"])
            self.assertEqual(0, audit_report["project_contexts_invalid"])
            self.assertEqual(1, audit_report["usage_documents_indexed"])
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
            connection.close()
            self.assertEqual((3, 7), row[:2])
            self.assertNotIn("real-secret", secret_content)
            self.assertEqual("context", curated_kinds["project-context.yaml"])
            self.assertEqual("usage", curated_kinds["docs/usage/fetch-items.md"])
            generated_catalog = catalog.read_text(encoding="utf-8")
            self.assertIn("fixture-library [library, curated]", generated_catalog)
            self.assertIn("Предоставляет тестовый API", generated_catalog)
            previous_database = server_module.DB_PATH
            server_module.DB_PATH = database
            try:
                curated_results = server_module.search({"query": "получить данные Fixture", "limit": 5})
                self.assertLess(
                    curated_results.find("path: `project-context.yaml:"),
                    curated_results.find("path: `docs/usage/fetch-items.md:"),
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
