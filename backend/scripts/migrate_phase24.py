"""Repair legacy student notifications that implied reports were immediately available."""
from __future__ import annotations

from pathlib import Path
import sys

import pymysql

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings


COMPLETED_WITH_QUESTIONNAIRE = (
    "两项任务和任务后问卷已成功提交。数据将进入转录与研究复核，"
    "个人报告正式发布后系统会通知你。"
)
COMPLETED_WITHOUT_QUESTIONNAIRE = (
    "两项出声思维任务已成功提交。数据将进入转录与研究复核，"
    "个人报告正式发布后系统会通知你。"
)
REVIEW_IN_PROGRESS = (
    "初步人工复核已完成，仍需完成研究审核与发布；"
    "正式发布后系统会再次通知你。"
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
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """UPDATE notifications
                SET content=%s
                WHERE type='assessment' AND title='测评已完成'
                  AND content LIKE '%%现在可以生成个人报告%%'
                  AND content LIKE '%%任务后问卷%%'""",
                (COMPLETED_WITH_QUESTIONNAIRE,),
            )
            questionnaire_count = cursor.rowcount
            cursor.execute(
                """UPDATE notifications
                SET content=%s
                WHERE type='assessment' AND title='测评已完成'
                  AND content LIKE '%%现在可以生成个人报告%%'
                  AND content NOT LIKE '%%任务后问卷%%'""",
                (COMPLETED_WITHOUT_QUESTIONNAIRE,),
            )
            task_only_count = cursor.rowcount
            cursor.execute(
                """UPDATE notifications
                SET title='报告复核处理中', content=%s
                WHERE type='report' AND title='报告已完成人工复核'""",
                (REVIEW_IN_PROGRESS,),
            )
            review_count = cursor.rowcount
        connection.commit()
        print(
            "Phase 24 report notification migration completed: "
            f"assessment={questionnaire_count + task_only_count}, "
            f"review={review_count}."
        )
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    main()
