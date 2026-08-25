"""Update the two official tasks so each ends with one best-performing choice."""
from pathlib import Path
import sys

import pymysql

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings
from app.services.narration_catalog import (
    INSTRUCTION_NARRATION,
    PRACTICE_NARRATION,
    QUESTIONNAIRE_NARRATION,
)


TASK_UPDATES = (
    (
        "task-pitching-2026-2",
        "最优投球机判断",
        "根据四台投球机相对于目标点的多次偏离距离，设计数学评价程序并判断哪台投球机表现最优。",
        "红色叉号代表理想落点，蓝色菱形代表实际落点，旁边数字表示该次投球到目标点的距离。"
        "请比较四台投球机，设计并说明一种合理的数学程序来综合评价各投球机的表现，"
        "最终明确判断哪台投球机表现最优，并说明理由。"
        "请在整个作答过程中持续口头说出你脑海中实时产生的所有想法。",
    ),
    (
        "task-jumps-2026-2",
        "跨项目最优运动员判断",
        "根据跳高和跳远最佳成绩的频数分布，设计公平的跨项目评价程序并判断哪位运动员表现最优。",
        "Bill参加跳高，Joe参加跳远。表2给出了2000年跳高和跳远最佳成绩及其出现次数。"
        "请根据表格设计并说明一种公平的数学程序来比较两位运动员，"
        "最终明确判断Bill和Joe中哪位运动员表现最优，并说明理由。"
        "请在整个作答过程中持续口头说出你脑海中实时产生的所有想法。",
    ),
    (
        "task-001-default",
        "最优投球机判断",
        "根据四台投球机相对于目标点的多次偏离距离，设计数学评价程序并判断哪台投球机表现最优。",
        "红色叉号代表理想落点，蓝色菱形代表实际落点，旁边数字表示该次投球到目标点的距离。"
        "请比较四台投球机，设计并说明一种合理的数学程序来综合评价各投球机的表现，"
        "最终明确判断哪台投球机表现最优，并说明理由。"
        "请在整个作答过程中持续口头说出你脑海中实时产生的所有想法。",
    ),
    (
        "task-002-athletes",
        "跨项目最优运动员判断",
        "根据跳高和跳远最佳成绩的频数分布，设计公平的跨项目评价程序并判断哪位运动员表现最优。",
        "Bill参加跳高，Joe参加跳远。表2给出了2000年跳高和跳远最佳成绩及其出现次数。"
        "请根据表格设计并说明一种公平的数学程序来比较两位运动员，"
        "最终明确判断Bill和Joe中哪位运动员表现最优，并说明理由。"
        "请在整个作答过程中持续口头说出你脑海中实时产生的所有想法。",
    ),
)


def main() -> None:
    settings = get_settings()
    connection = pymysql.connect(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=settings.DB_NAME,
        charset="utf8mb4",
        autocommit=False,
    )
    changed_task_ids: list[str] = []
    updated_image_titles = 0
    disabled_stale_narrations = 0
    try:
        with connection.cursor() as cursor:
            for task_id, title, description, scenario in TASK_UPDATES:
                cursor.execute(
                    "SELECT title, description, scenario FROM assessment_tasks WHERE id=%s",
                    (task_id,),
                )
                current = cursor.fetchone()
                if current is None or current == (title, description, scenario):
                    continue
                cursor.execute(
                    """
                    UPDATE assessment_tasks
                    SET title=%s, description=%s, scenario=%s
                    WHERE id=%s
                    """,
                    (title, description, scenario, task_id),
                )
                changed_task_ids.append(task_id)

            cursor.execute(
                """
                UPDATE assessment_tasks
                SET stimulus_data=JSON_SET(
                    COALESCE(stimulus_data, JSON_OBJECT()),
                    '$.image_title',
                    %s
                )
                WHERE id IN (%s, %s)
                  AND COALESCE(
                      JSON_UNQUOTE(JSON_EXTRACT(stimulus_data, '$.image_title')),
                      ''
                  ) <> %s
                """,
                (
                    "四台投球机落点与距离分布图",
                    "task-pitching-2026-2",
                    "task-001-default",
                    "四台投球机落点与距离分布图",
                ),
            )
            updated_image_titles = cursor.rowcount

            cursor.execute(
                """
                UPDATE assessment_tasks
                SET stimulus_data=JSON_SET(
                    COALESCE(stimulus_data, JSON_OBJECT()),
                    '$.image_title', %s,
                    '$.image_sha256', %s
                )
                WHERE id IN (%s, %s)
                  AND (
                      COALESCE(
                          JSON_UNQUOTE(JSON_EXTRACT(stimulus_data, '$.image_title')),
                          ''
                      ) <> %s
                      OR COALESCE(
                          JSON_UNQUOTE(JSON_EXTRACT(stimulus_data, '$.image_sha256')),
                          ''
                      ) <> %s
                  )
                """,
                (
                    "2000年跳高与跳远最佳成绩频数表",
                    "528b8726eee06ac964583b5c12d01c3d526c76dcdf06d4c44d6f97bb23cea08f",
                    "task-jumps-2026-2",
                    "task-002-athletes",
                    "2000年跳高与跳远最佳成绩频数表",
                    "528b8726eee06ac964583b5c12d01c3d526c76dcdf06d4c44d6f97bb23cea08f",
                ),
            )
            updated_image_titles += cursor.rowcount

            if changed_task_ids:
                slot_keys = [f"task:{task_id}" for task_id in changed_task_ids]
                placeholders = ", ".join(["%s"] * len(slot_keys))
                cursor.execute(
                    f"""
                    UPDATE narration_assets
                    SET is_active=FALSE
                    WHERE is_active=TRUE AND slot_key IN ({placeholders})
                    """,
                    slot_keys,
                )
                disabled_stale_narrations += cursor.rowcount

            for slot_key, source_text in (
                ("instructions", INSTRUCTION_NARRATION),
                ("practice", PRACTICE_NARRATION),
                ("questionnaire", QUESTIONNAIRE_NARRATION),
            ):
                cursor.execute(
                    """
                    UPDATE narration_assets
                    SET is_active=FALSE
                    WHERE is_active=TRUE
                      AND slot_key=%s
                      AND source_text<>%s
                    """,
                    (slot_key, source_text),
                )
                disabled_stale_narrations += cursor.rowcount
        connection.commit()
        print(
            "Phase 15 task conclusions are ready; "
            f"updated_tasks={len(changed_task_ids)}, "
            f"updated_image_titles={updated_image_titles}, "
            f"disabled_stale_narrations={disabled_stale_narrations}."
        )
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
