"""Verify questionnaire versions and active-run assignments."""
from pathlib import Path
import sys

import pymysql

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings
from app.services.questionnaire import CURRENT_QUESTIONNAIRE_SOURCE


def main() -> None:
    settings = get_settings()
    connection = pymysql.connect(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=settings.DB_NAME,
        charset="utf8mb4",
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT source, COUNT(*), COALESCE(SUM(reversed), 0)
                FROM scale_items
                GROUP BY source
                ORDER BY source
                """
            )
            sources = cursor.fetchall()
            cursor.execute(
                """
                SELECT id, task_id, dimension
                FROM scale_dimension_groups
                ORDER BY dimension, id
                """
            )
            groups = cursor.fetchall()
            cursor.execute(
                """
                SELECT r.id, u.username, u.name, r.current_stage,
                       r.questionnaire_source, COUNT(q.id) AS answer_count
                FROM assessment_runs r
                JOIN users u ON u.id=r.user_id
                LEFT JOIN questionnaire_responses q ON q.run_id=r.id
                WHERE r.status='in_progress'
                GROUP BY r.id, u.username, u.name, r.current_stage,
                         r.questionnaire_source
                ORDER BY r.started_at
                """
            )
            active_runs = cursor.fetchall()
    finally:
        connection.close()

    print("Questionnaire sources:")
    for source, item_count, reversed_count in sources:
        print(f"- {source}: {item_count} items, {reversed_count} reversed")
    print("Scale dimension groups:")
    for group_id, task_id, dimension in groups:
        print(f"- {group_id} | {task_id} | {dimension}")
    print("Active assessment runs:")
    if not active_runs:
        print("- none")
    for run_id, username, name, stage, source, answer_count in active_runs:
        print(
            f"- {run_id} | {username} | {name} | {stage} | "
            f"{source} | {answer_count} answers"
        )

    current = next(
        (row for row in sources if row[0] == CURRENT_QUESTIONNAIRE_SOURCE),
        None,
    )
    if current is None or int(current[1]) != 24 or int(current[2]) != 1:
        raise RuntimeError("正式问卷必须为 24 题且仅包含 1 道反向计分题")


if __name__ == "__main__":
    main()
