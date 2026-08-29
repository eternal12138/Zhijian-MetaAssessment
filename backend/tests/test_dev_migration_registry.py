"""Development startup must use the same fail-fast registry as production."""
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from scripts import migrate_all


class DevMigrationRegistryTests(unittest.TestCase):
    def test_production_calls_the_same_registry_before_bootstrap(self):
        from scripts import setup_production
        with patch.object(setup_production, 'run') as run:
            setup_production.main()
        self.assertEqual([call.args[0].name for call in run.call_args_list], [
            'create_schema.py', 'migrate_all.py', 'bootstrap_admin.py', 'seed_protocol.py',
        ])

    def test_dev_uses_registry_and_stops_before_bootstrap_on_failure(self):
        source = (Path(__file__).resolve().parents[2] / "dev.ps1").read_text(encoding="utf-8-sig")
        block = source.split('Write-Step "Apply idempotent project database migrations"', 1)[1]
        block = block.split('scripts\\bootstrap_development.py', 1)[0]
        self.assertIn('scripts\\migrate_all.py', block)
        self.assertNotIn('scripts\\migrate_phase', block)
        self.assertIn('if ($LASTEXITCODE -ne 0)', block)
        self.assertIn('throw "Database migrations failed', block)

    def test_registry_contains_scope_and_correction_migrations_in_order(self):
        self.assertEqual(migrate_all.SCRIPTS[-5:], ("migrate_phase32.py", "migrate_phase33.py", "migrate_phase34.py", "migrate_phase35.py", "migrate_phase36.py"))
        self.assertEqual(len(migrate_all.SCRIPTS), len(set(migrate_all.SCRIPTS)))
        for script in migrate_all.SCRIPTS:
            self.assertTrue((Path(migrate_all.__file__).parent / script).is_file())

    def test_registry_does_not_continue_after_failure(self):
        with patch.object(migrate_all, "SCRIPTS", ("first.py", "failed.py", "never.py")), \
             patch.object(migrate_all.subprocess, "run", side_effect=[None, subprocess.CalledProcessError(1, "failed")]) as run:
            with self.assertRaises(subprocess.CalledProcessError):
                migrate_all.main()
        self.assertEqual(run.call_count, 2)
        self.assertTrue(all(call.kwargs["check"] for call in run.call_args_list))
