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

    def test_old_schema_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "old.db"
            connection = sqlite3.connect(database)
            connection.execute("CREATE TABLE chunks (source_id TEXT, content TEXT)")
            connection.commit()
            connection.close()
            with self.assertRaises(KnowledgeSchemaError):
                validate_database(database)

    def test_build_verify_package_and_install(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            source = workspace / "fixture-project"
            kotlin = source / "src/main/kotlin/demo/Example.kt"
            properties = source / "src/main/resources/application.properties"
            kotlin.parent.mkdir(parents=True)
            properties.parent.mkdir(parents=True)
            (source / "settings.gradle.kts").write_text('rootProject.name = "fixture-project"\n', encoding="utf-8")
            kotlin.write_text(
                "\n\npackage demo\n\nclass Example {\n    fun fetchItems(): List<String> = emptyList()\n}\n",
                encoding="utf-8",
            )
            properties.write_text(
                "spring.datasource.username=test\nspring.datasource.password=real-secret\n",
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
            database = workspace / "knowledge.db"
            catalog = workspace / "generated-catalog.md"
            audit = workspace / "audit-summary.json"
            evaluation = workspace / "evaluation-summary.json"
            self.run_script(
                "knowledge_indexer.py",
                "--pack", "fixture",
                "--source", source,
                "--db", database,
                "--catalog", catalog,
                "--audit", audit,
            )
            self.assertEqual(SCHEMA_VERSION, validate_database(database))
            connection = sqlite3.connect(database)
            row = connection.execute(
                "SELECT line_start, line_end, content FROM chunks WHERE path LIKE '%Example.kt'"
            ).fetchone()
            secret_content = connection.execute(
                "SELECT content FROM chunks WHERE path LIKE '%application.properties'"
            ).fetchone()[0]
            connection.close()
            self.assertEqual((3, 7), row[:2])
            self.assertNotIn("real-secret", secret_content)
            self.run_script(
                "verify_index.py",
                "--db", database,
                "--audit", audit,
                "--expect", "fetchItems",
                "--output", evaluation,
            )
            report = json.loads(evaluation.read_text(encoding="utf-8"))
            self.assertTrue(report["passed"])
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
            self.assertEqual(SCHEMA_VERSION, manifest["schema_version"])
            self.assertEqual("fixture-project", manifest["sources"][0]["repository"])
            destination = workspace / "installed"
            self.run_script("install_pack.py", archive, "--destination", destination)
            self.assertEqual(SCHEMA_VERSION, validate_database(destination / "knowledge.db"))
            self.assertTrue((destination / "audit-summary.json").exists())
            self.assertTrue((destination / "evaluation-summary.json").exists())
            for name in ("server.py", "knowledge_schema.py"):
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
