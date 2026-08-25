# 元认知文本分类 Baseline

标签定义（以项目最终人工编码为准）：

- `0` → `non_metacognitive`（非元认知/不确定）
- `1` → `monitoring`（监控）
- `2` → `regulation`（调控）
- `3` → `evaluation`（评估）

训练数据会保留原始标签，并在内存中按上述显式映射规范化。若出现映射外标签，训练会被阻止，不会自动猜测。

## 运行

在项目根目录使用训练环境执行：

```powershell
.\.dev\python313\python.exe research\run_baselines.py `
  --dataset "$HOME\Desktop\training_dataset_v1.csv" `
  --output research\baseline_output `
  --skip-bge `
  --benchmark
```

移除 `--skip-bge` 执行 BGE-M3 三个对照模型。开发机有 CUDA 时可加入 `--bge-device cuda` 生成 embedding；生产资源报告仍必须在 CPU 模式单独运行。Embedding 缓存在 `cache/bge_m3_embeddings.npz`，更换分类器不会重复生成；数据内容、数据版本或 embedding 模型变化时缓存自动失效。

输出包括：

- `reports/data_quality.json|csv`
- `reports/baseline_comparison.csv`
- `reports/<model>/metrics.json`
- `reports/<model>/confusion_matrix.png|csv`
- `reports/<model>/error_cases.csv`
- `reports/<model>/confusion_pairs.csv`
- `reports/deployment_benchmark.csv`
- `reports/deployment_recommendation.json`
- `models/<model>/model.joblib|config.json|metrics.json|label_mapping.json`

TF-IDF 只在训练集上拟合。存在账号/被试字段时使用 GroupShuffleSplit，并断言训练与测试被试没有交集；无被试字段时才退化为分层随机划分，报告会明确标记 subject leakage 风险。
