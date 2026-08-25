"""Run every idempotent database migration in the required order."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys


SCRIPTS = (
    "migrate_phase2.py",
    "migrate_phase3.py",
    "migrate_phase4.py",
    "migrate_task_order.py",
    "migrate_phase5.py",
    "migrate_phase6.py",
    "migrate_phase7.py",
    "migrate_phase8.py",
    "migrate_phase9.py",
    "migrate_phase10.py",
    "migrate_phase11.py",
    "migrate_phase12.py",
    "migrate_phase13.py",
    "migrate_phase14.py",
    "migrate_phase15.py",
    "migrate_phase16.py",
    "migrate_phase17.py",
    "migrate_phase18.py",
    "migrate_phase19.py",
    "migrate_phase20.py",
    "migrate_phase21.py",
    "migrate_phase22.py",
    "migrate_phase23.py",
    "migrate_phase24.py",
    "migrate_phase25.py",
    "migrate_phase26.py",
    "migrate_phase27.py",
    "migrate_phase28.py",
    "migrate_phase29.py",
    "migrate_phase30.py",
    "migrate_phase31.py",
)


def main() -> None:
    scripts_dir = Path(__file__).resolve().parent
    for name in SCRIPTS:
        print(f"Applying {name}...", flush=True)
        subprocess.run(
            [sys.executable, str(scripts_dir / name)],
            check=True,
        )
    print("All database migrations completed.", flush=True)


if __name__ == "__main__":
    main()
