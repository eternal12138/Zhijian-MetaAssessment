"""Run production migrations, bootstrap the first admin, and publish protocol."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys


def run(script: Path) -> None:
    subprocess.run([sys.executable, str(script)], check=True)


def main() -> None:
    scripts_dir = Path(__file__).resolve().parent
    run(scripts_dir / "create_schema.py")
    run(scripts_dir / "migrate_all.py")
    run(scripts_dir / "bootstrap_admin.py")
    run(scripts_dir / "seed_protocol.py")
    print("Production database setup completed.")


if __name__ == "__main__":
    main()
