"""Strict CSV import for complete admin-reviewed session dialogue sets."""
import csv
import io

from app.services.metacognition_distribution import empty_counts, normalize_dimension

MAX_UPLOAD_BYTES = 5 * 1024 * 1024


def parse_correction_csv(content: bytes) -> dict[str, list[dict]]:
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("校对文件不能超过 5 MB")
    try:
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig"), newline=""))
        aliases = {"会话ID": "session_id", "校对文本": "text", "最终标签": "label"}
        headers = [aliases.get(h.strip(), h.strip()) for h in (reader.fieldnames or [])]
        if len(set(headers)) != len(headers) or not {"session_id", "text", "label"}.issubset(headers):
            raise ValueError("需要 会话ID、校对文本、最终标签 三列（或 session_id,text,label）")
        reader.fieldnames = headers
        grouped: dict[str, list[dict]] = {}
        for index, row in enumerate(reader, 2):
            if None in row:
                raise ValueError(f"第 {index} 行列数过多，请给含逗号的文本加双引号")
            session_id = (row.get("session_id") or "").strip()
            text = (row.get("text") or "").strip()
            raw_label = (row.get("label") or "").strip()
            label = {"0": "non_metacognitive", "1": "monitoring", "2": "regulation", "3": "evaluation",
                     "非元认知": "non_metacognitive", "监控": "monitoring", "调控": "regulation",
                     "评估": "evaluation"}.get(raw_label, raw_label)
            if not session_id or len(session_id) > 36 or not text or len(text) > 20000:
                raise ValueError(f"第 {index} 行会话ID或校对文本为空/过长")
            if label not in {"non_metacognitive", "monitoring", "regulation", "evaluation"}:
                raise ValueError(f"第 {index} 行标签不合法，请使用 0/1/2/3 或模板说明的类别")
            grouped.setdefault(session_id, []).append({"text": text, "label": label})
            if index > 10001 or len(grouped) > 100:
                raise ValueError("单次最多 10000 条对话、100 个会话，请分批上传")
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValueError("请上传 UTF-8 编码的 CSV 文件") from exc
    if not grouped:
        raise ValueError("文件没有有效对话；空文件不会清除已有校对版本")
    return grouped


def correction_counts(dialogues):
    counts = empty_counts()
    for row in dialogues:
        dimension = normalize_dimension(row["label"])
        if dimension:
            counts[dimension] += 1
    return counts
