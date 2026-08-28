import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("release_verifier", ROOT / "deploy/verify-release.py")
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class ReleasePackageTests(unittest.TestCase):
    def fixture(self, root):
        entries = {name: b"fixture\n" for name in verifier.REQUIRED}
        records = [{"path": name, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)} for name, data in entries.items()]
        manifest = {"format_version": 1, "release_id": "test-release", "schema_phase": 33,
                    "files": records, "retired_files": ["backend/app/core/websocket.py"]}
        entries["RELEASE_MANIFEST.json"] = json.dumps(manifest).encode()
        for name, data in entries.items():
            file = root / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(data)
        return entries

    def test_archive_and_extracted_tree_verify(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            entries = self.fixture(root)
            archive = root / "release.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                for name, data in entries.items():
                    handle.writestr(name, data)
            self.assertEqual(verifier.verify(archive)["schema_phase"], 33)
            self.assertEqual(verifier.verify(root)["release_id"], "test-release")

    def test_mixed_source_version_is_rejected(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            (root / "frontend/src/views/DashboardView.vue").write_text("old student page")
            with self.assertRaisesRegex(ValueError, "differs"):
                verifier.verify(root)

    def test_retired_file_cannot_silently_remain(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            old = root / "backend/app/core/websocket.py"
            old.parent.mkdir(parents=True, exist_ok=True)
            old.write_text("old module")
            with self.assertRaisesRegex(ValueError, "Retired source"):
                verifier.verify(root)
            verifier.verify(root, allow_retired=True)

    def test_unsafe_paths_are_rejected(self):
        for name in ("../secrets", "/etc/passwd", "C:/file", "a\\b", "a/../b"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                verifier.safe_name(name)

    def test_exports_are_owned_by_one_worker_only(self):
        from app.api.research import create_audio_transcript_export
        from app.main import lifespan
        self.assertNotIn("create_task", inspect.getsource(create_audio_transcript_export))
        self.assertNotIn("create_task", inspect.getsource(lifespan))
        worker = (ROOT / "backend/scripts/export_worker.py").read_text(encoding="utf-8")
        self.assertIn("with_for_update(skip_locked=True)", worker)

    def test_linux_image_has_openmp_runtime(self):
        self.assertIn("libgomp1", (ROOT / "backend/Dockerfile").read_text())

    def test_frontend_public_permissions_are_normalized_after_copy(self):
        dockerfile = (ROOT / "frontend/Dockerfile").read_text()
        copy = dockerfile.index("COPY --from=build /app/dist /usr/share/nginx/html")
        directories = dockerfile.index("find /usr/share/nginx/html -type d -exec chmod 755 {} +")
        files = dockerfile.index("find /usr/share/nginx/html -type f -exec chmod 644 {} +")
        self.assertLess(copy, directories)
        self.assertLess(directories, files)
        self.assertNotIn("chmod 777", dockerfile)

    def test_frontend_update_does_not_rebuild_or_restart_dependencies(self):
        instructions = (ROOT / "deploy/QUICK_UPDATE.md").read_text(encoding="utf-8")
        self.assertIn("build --progress=plain frontend", instructions)
        self.assertIn("up -d --no-deps --no-build frontend", instructions)

    def test_student_measurement_card_is_independent_from_published_reports(self):
        source = (ROOT / "frontend/src/views/DashboardView.vue").read_text(encoding="utf-8")
        self.assertIn('<MacroAnalyticsDashboard user-role="student" />', source)
        self.assertIn('class="dashboard-macro-section"', source)
        self.assertNotIn('<h2>我的元认知画像</h2>', source)
        component = (ROOT / "frontend/src/components/dashboard/MacroAnalyticsDashboard.vue").read_text(encoding="utf-8")
        self.assertIn('aria-label="选择测量任务"', component)
        self.assertIn('reportApi.getMetacognitionMeasurement', component)
        self.assertIn("暂无已完成轮次", component)
        self.assertIn("reportApi.listMetacognitionMeasurements(page++, 100)", component)


if __name__ == "__main__":
    unittest.main()
