"""Read-only inventory of data left by the retired single-review workflow."""
import argparse
import asyncio
import json
from pathlib import Path
import sys

from sqlalchemy import distinct, func, select

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import AsyncSessionLocal, engine
from app.models.research import CodingAdjudication, CodingAnnotation, CodingUnit
from app.models.session import CodedSegment


async def audit() -> dict[str, int]:
    async with AsyncSessionLocal() as db:
        annotation_count = int(
            await db.scalar(select(func.count(CodingAnnotation.id))) or 0
        )
        adjudication_count = int(
            await db.scalar(select(func.count(CodingAdjudication.id))) or 0
        )
        legacy_score_count = int(
            await db.scalar(
                select(func.count(CodedSegment.id)).where(
                    CodedSegment.human_score.is_not(None)
                )
            ) or 0
        )
        mapped_score_count = int(
            await db.scalar(
                select(func.count(distinct(CodedSegment.id)))
                .join(
                    CodingUnit,
                    CodingUnit.transcript_segment_id
                    == CodedSegment.transcript_segment_id,
                )
                .where(
                    CodedSegment.human_score.is_not(None),
                    CodingUnit.status.in_(("agreed", "adjudicated")),
                )
            ) or 0
        )
    return {
        "legacy_annotations": annotation_count,
        "legacy_adjudications": adjudication_count,
        "segments_with_legacy_human_score": legacy_score_count,
        "legacy_scored_segments_with_resolved_batch_unit": mapped_score_count,
        "legacy_scored_segments_without_resolved_batch_unit": max(
            0, legacy_score_count - mapped_score_count
        ),
    }


async def run_audit() -> dict[str, int]:
    try:
        return await audit()
    finally:
        # aiomysql connections must be disposed on the same event loop that
        # performed the query, particularly on Windows' proactor loop.
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fail-on-legacy",
        action="store_true",
        help="exit with status 2 when any retired-workflow records remain",
    )
    args = parser.parse_args()
    result = asyncio.run(run_audit())
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if args.fail_on_legacy and any(result.values()):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
