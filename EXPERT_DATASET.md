# 专家标注数据集

## 数据链路

`Audio/ASR Job -> TranscriptSegment -> ExtractionCandidate -> CodingUnit -> ExpertAnnotation -> CSV`

- `CodingUnit.raw_text` 保留 ASR 候选片段原文。
- `CodingUnit.clean_text` 保留 AI 清洗文本，不覆盖原文。
- `CodingUnit.ai_label` 保留 AI 判断。
- `ExpertAnnotation.expert_label` 按专家分行保存，不覆盖 AI 或另一位专家。
- 两位专家一致后生成共识标签；不一致时交给指定仲裁员。

## 标签

- `non_metacognitive`
- `planning`
- `monitoring`
- `regulation`

## 导出

管理员在“研究管理 -> 专家双人编码”中可选择：

- 文本：`clean_text` （默认）或 `raw_text`
- 标签：共识/仲裁结果（默认）或每位专家的独立编码

命令行示例：

```powershell
$token = "管理员访问令牌"
Invoke-WebRequest `
  -Headers @{ Authorization = "Bearer $token" } `
  -Uri "http://127.0.0.1:8000/api/research/review/training-dataset/export?text_source=clean_text&label_mode=resolved" `
  -OutFile ".\expert_training_dataset.csv"
```

只有已获得四分类专家标签的行会被导出。
