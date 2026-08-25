from __future__ import annotations

import csv
import io
import json
import re
import uuid
import zipfile
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import require_role
from app.database import get_db
from app.models.research import AuditLog, ModelTrainingJob
from app.models.user import User
from app.schemas.model_training import (
    ExperimentType, TrainingAuditOut, TrainingJobCreate, TrainingJobOut,
    TrainingDatasetOut, TrainingSuiteCreate,
)
from app.services.model_artifacts import load_model_artifact
from app.services.model_inference import probe_model_activation
from app.services.model_metrics_service import group_evaluations, load_job_evaluation
from app.services.runtime_model_config import load_runtime_model_settings
from app.config import get_settings
from app.services.model_training import TRAINING_PIPELINE_VERSION, _reviewed_samples
from app.services.model_training_datasets import (
    build_dataset_template, get_dataset_metadata, list_uploaded_datasets, materialize_dataset,
    load_dataset_samples, parse_uploaded_dataset,
)
from app.training.hyperparameters import (
    normalize_hyperparameters, public_hyperparameter_catalog,
)

router = APIRouter(prefix="/research/model-training", tags=["模型训练"])
settings = get_settings()

EXPERIMENTS: dict[str, tuple[str, str, str]] = {
    "tfidf_linear_svc": ("tfidf", "linear_svc", "TF-IDF + LinearSVC"),
    "embedding_linear_svc": ("remote_embedding", "linear_svc", "Embedding + LinearSVC"),
    "embedding_logistic": ("remote_embedding", "logistic", "Embedding + LogisticRegression"),
    "embedding_random_forest": ("remote_embedding", "random_forest", "Embedding + RandomForest"),
    "embedding_xgboost": ("remote_embedding", "xgboost", "Embedding + XGBoost"),
    "embedding_lightgbm": ("remote_embedding", "lightgbm", "Embedding + LightGBM"),
    "embedding_catboost": ("remote_embedding", "catboost", "Embedding + CatBoost"),
}


def _effective_embedding() -> tuple[str, str, int, str]:
    base_url = settings.EMBEDDING_API_BASE or settings.QWEN_EMBEDDING_BASE_URL
    model = settings.EMBEDDING_MODEL or settings.QWEN_EMBEDDING_MODEL
    dimensions = settings.EMBEDDING_DIMENSION if settings.EMBEDDING_MODEL else settings.QWEN_EMBEDDING_DIMENSIONS
    api_key = settings.EMBEDDING_API_KEY or settings.QWEN_EMBEDDING_API_KEY
    return base_url, model, dimensions, api_key


def _job_config_snapshot(
    experiment_type: ExperimentType,
    dataset: dict,
    comparison_group_id: str | None = None,
    comparison_group_label: str | None = None,
    comparison_expected_experiments: list[str] | None = None,
    hyperparameters: dict | None = None,
) -> dict:
    feature, classifier, display_name = EXPERIMENTS[experiment_type]
    classifier_parameters, hyperparameters_tuned = normalize_hyperparameters(
        experiment_type, hyperparameters,
    )
    base_url, model, dimensions, _ = _effective_embedding()
    return {
        "experiment_type": experiment_type,
        "display_name": display_name,
        "feature": feature,
        "classifier": classifier,
        "embedding_provider": settings.EMBEDDING_PROVIDER if feature == "remote_embedding" else None,
        "embedding_base_url": base_url.rstrip("/") if feature == "remote_embedding" else None,
        "embedding_model": model if feature == "remote_embedding" else None,
        "embedding_version": settings.EMBEDDING_VERSION if feature == "remote_embedding" else None,
        "embedding_dimension": dimensions if feature == "remote_embedding" else None,
        "dimensions": dimensions if feature == "remote_embedding" else None,
        "embedding_normalized": settings.EMBEDDING_NORMALIZED if feature == "remote_embedding" else None,
        "embedding_instruction": settings.EMBEDDING_INSTRUCTION or None if feature == "remote_embedding" else None,
        "batch_size": settings.EMBEDDING_BATCH_SIZE if feature == "remote_embedding" else None,
        "timeout_seconds": settings.EMBEDDING_TIMEOUT if feature == "remote_embedding" else None,
        "max_retries": settings.EMBEDDING_MAX_RETRIES if feature == "remote_embedding" else None,
        "folds": 5,
        "random_seed": 42,
        "training_pipeline_version": TRAINING_PIPELINE_VERSION,
        "dataset_id": dataset["id"],
        "dataset_source": dataset["source"],
        "dataset_name": dataset["name"],
        "dataset_sample_count": dataset["sample_count"],
        "dataset_training_sample_count": dataset.get("training_sample_count", dataset["sample_count"]),
        "training_labels": [1, 2, 3],
        "dataset_participant_count": dataset["participant_count"],
        "dataset_has_participant_ids": bool(dataset.get("has_participant_ids")),
        "dataset_split_strategy": dataset.get("split_strategy", "sentence_stratified_5fold"),
        "dataset_fingerprint": dataset["fingerprint"],
        "comparison_group_id": comparison_group_id,
        "comparison_group_label": comparison_group_label,
        "comparison_expected_experiments": comparison_expected_experiments if comparison_group_id else None,
        "classifier_parameters": classifier_parameters,
        "hyperparameters_tuned": hyperparameters_tuned,
        "hyperparameter_source": "manual" if hyperparameters_tuned else "default",
    }


async def _new_job(
    version: str, experiment_type: ExperimentType, dataset: dict,
    user: User, db: AsyncSession,
    comparison_group_id: str | None = None,
    comparison_group_label: str | None = None,
    comparison_expected_experiments: list[str] | None = None,
    hyperparameters: dict | None = None,
) -> ModelTrainingJob:
    if experiment_type != "tfidf_linear_svc":
        base_url, model, _, api_key = _effective_embedding()
        if not (api_key.strip() and base_url.startswith("https://") and model.strip()):
            raise HTTPException(409, "请先配置并诊断远程文本嵌入服务")
    exists = await db.scalar(select(ModelTrainingJob.id).where(ModelTrainingJob.version == version))
    if exists:
        raise HTTPException(409, f"训练版本 {version} 已存在，请使用新的版本号")
    job = ModelTrainingJob(
        version=version, requested_by=user.id,
        config_snapshot=_job_config_snapshot(
            experiment_type, dataset, comparison_group_id, comparison_group_label,
            comparison_expected_experiments,
            hyperparameters,
        ),
        dataset_fingerprint=dataset["fingerprint"],
        sample_count=dataset.get("training_sample_count", dataset["sample_count"]),
        label_distribution=dataset.get("training_label_distribution", dataset["label_distribution"]),
    )
    db.add(job)
    await db.flush()
    db.add(AuditLog(
        actor_id=user.id, action="model_training.create", target_type="model_training_job",
        target_id=job.id, detail={
            "version": version, "experiment_type": experiment_type,
            "dataset_id": dataset["id"], "dataset_source": dataset["source"],
            "dataset_name": dataset["name"], "dataset_fingerprint": dataset["fingerprint"],
            "comparison_expected_experiments": comparison_expected_experiments,
            "hyperparameters_tuned": bool(hyperparameters),
            "classifier_parameters": normalize_hyperparameters(experiment_type, hyperparameters)[0],
        },
    ))
    return job


async def _resolve_dataset(
    source: str, dataset_id: str | None, user: User, db: AsyncSession,
) -> dict:
    if source == "uploaded":
        if not dataset_id:
            raise HTTPException(422, "请选择已上传的训练数据")
        try:
            metadata = get_dataset_metadata(settings.model_training_path, dataset_id)
        except ValueError as error:
            raise HTTPException(404, str(error)) from error
        if metadata.get("source") != "uploaded":
            raise HTTPException(422, "所选数据集不是上传数据")
        return metadata
    try:
        samples = await _reviewed_samples(db)
        return materialize_dataset(
            settings.model_training_path, samples, source="system_gold",
            name=f"系统专家金标准 {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            original_filename=None, created_by=user.id,
        )
    except ValueError as error:
        raise HTTPException(409, str(error)) from error


@router.get("/datasets", response_model=list[TrainingDatasetOut])
async def list_datasets(user: User = Depends(require_role("admin"))):
    del user
    return list_uploaded_datasets(settings.model_training_path)


@router.get("/hyperparameters")
async def get_hyperparameter_catalog(user: User = Depends(require_role("admin"))):
    del user
    return public_hyperparameter_catalog()


@router.get("/datasets/template")
async def download_dataset_template(user: User = Depends(require_role("admin"))):
    del user
    return Response(
        content=build_dataset_template(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="metacognition-training-dataset-template.xlsx"'},
    )


@router.post("/datasets/upload", response_model=TrainingDatasetOut, status_code=201)
async def upload_dataset(
    name: str = Form(..., min_length=1, max_length=100),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    content = await file.read(15 * 1024 * 1024 + 1)
    if len(content) > 15 * 1024 * 1024:
        raise HTTPException(413, "训练数据文件不能超过 15 MB")
    try:
        samples = parse_uploaded_dataset(file.filename or "", content)
        metadata = materialize_dataset(
            settings.model_training_path, samples, source="uploaded", name=name,
            original_filename=file.filename, created_by=user.id,
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    db.add(AuditLog(
        actor_id=user.id, action="model_training.dataset_upload",
        target_type="model_training_dataset", target_id=metadata["id"],
        detail={
            "name": metadata["name"], "original_filename": metadata["original_filename"],
            "sample_count": metadata["sample_count"],
            "training_sample_count": metadata.get("training_sample_count", metadata["sample_count"]),
            "excluded_non_metacognitive_count": metadata.get("excluded_non_metacognitive_count", 0),
            "participant_count": metadata["participant_count"],
            "has_participant_ids": metadata.get("has_participant_ids", False),
            "split_strategy": metadata.get("split_strategy", "sentence_stratified_5fold"),
            "label_distribution": metadata["label_distribution"],
            "training_label_distribution": metadata.get("training_label_distribution", {}),
            "training_labels": metadata.get("training_labels", [1, 2, 3]),
            "fingerprint": metadata["fingerprint"],
        },
    ))
    await db.commit()
    return metadata


@router.post("/jobs", response_model=TrainingJobOut, status_code=201)
async def create_job(data: TrainingJobCreate, db: AsyncSession = Depends(get_db), user: User = Depends(require_role("admin"))):
    await load_runtime_model_settings(db, settings)
    if await db.scalar(select(ModelTrainingJob.id).where(ModelTrainingJob.version == data.version)):
        raise HTTPException(409, f"训练版本 {data.version} 已存在，请使用新的版本号")
    if data.experiment_type != "tfidf_linear_svc":
        base_url, model, _, api_key = _effective_embedding()
        if not (api_key.strip() and base_url.startswith("https://") and model.strip()):
            raise HTTPException(409, "请先配置并诊断远程文本嵌入服务")
    dataset = await _resolve_dataset(data.dataset_source, data.dataset_id, user, db)
    try:
        job = await _new_job(
            data.version, data.experiment_type, dataset, user, db,
            hyperparameters=data.hyperparameters,
        )
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    await db.commit()
    await db.refresh(job)
    return job


@router.post("/jobs/suite", response_model=list[TrainingJobOut], status_code=201)
async def create_suite(data: TrainingSuiteCreate, db: AsyncSession = Depends(get_db), user: User = Depends(require_role("admin"))):
    await load_runtime_model_settings(db, settings)
    suffixes = {
        "tfidf_linear_svc": "tfidf-svc",
        "embedding_linear_svc": "emb-svc",
        "embedding_logistic": "emb-logistic",
        "embedding_random_forest": "emb-rf",
        "embedding_xgboost": "emb-xgb",
        "embedding_lightgbm": "emb-lgbm",
        "embedding_catboost": "emb-cat",
    }
    selected_experiments = list(data.experiment_types or EXPERIMENTS)
    if any(experiment != "tfidf_linear_svc" for experiment in selected_experiments):
        base_url, model, _, api_key = _effective_embedding()
        if not (api_key.strip() and base_url.startswith("https://") and model.strip()):
            raise HTTPException(409, "请先配置并诊断远程文本嵌入服务")
    versions = [f"{data.version_prefix}-{suffixes[experiment]}" for experiment in selected_experiments]
    existing = set((await db.scalars(select(ModelTrainingJob.version).where(ModelTrainingJob.version.in_(versions)))).all())
    if existing:
        raise HTTPException(409, f"以下版本已存在：{', '.join(sorted(existing))}")
    dataset = await _resolve_dataset(data.dataset_source, data.dataset_id, user, db)
    comparison_group_id = str(uuid.uuid4())
    unknown_parameter_groups = sorted(set(data.hyperparameters) - set(EXPERIMENTS))
    if unknown_parameter_groups:
        raise HTTPException(422, f"包含未知训练方案的调参配置：{', '.join(unknown_parameter_groups)}")
    unselected_parameter_groups = sorted(set(data.hyperparameters) - set(selected_experiments))
    if unselected_parameter_groups:
        raise HTTPException(422, f"包含未选择模型的调参配置：{', '.join(unselected_parameter_groups)}")
    try:
        jobs = [
            await _new_job(
                f"{data.version_prefix}-{suffixes[kind]}", kind, dataset, user, db,
                comparison_group_id=comparison_group_id,
                comparison_group_label=data.version_prefix,
                comparison_expected_experiments=selected_experiments,
                hyperparameters=data.hyperparameters.get(kind),
            )
            for kind in selected_experiments
        ]
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    await db.commit()
    for job in jobs:
        await db.refresh(job)
    return jobs


@router.get("/jobs", response_model=list[TrainingJobOut])
async def list_jobs(db: AsyncSession = Depends(get_db), user: User = Depends(require_role("admin"))):
    del user
    result = await db.execute(select(ModelTrainingJob).order_by(ModelTrainingJob.created_at.desc(), ModelTrainingJob.id.desc()).limit(100))
    return list(result.scalars())


@router.get("/evaluations")
async def list_model_evaluations(
    db: AsyncSession = Depends(get_db), user: User = Depends(require_role("admin")),
):
    """返回由真实训练文件校验后的版本化模型评估结果。"""
    del user
    jobs = list((await db.scalars(
        select(ModelTrainingJob)
        .order_by(ModelTrainingJob.created_at.desc(), ModelTrainingJob.id.desc())
        .limit(500)
    )).all())
    return group_evaluations(jobs, settings.model_training_path)


@router.get("/jobs/{job_id}/evaluation")
async def get_model_evaluation(
    job_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(require_role("admin")),
):
    del user
    job = await db.get(ModelTrainingJob, job_id)
    if not job:
        raise HTTPException(404, "训练任务不存在")
    try:
        return load_job_evaluation(job, settings.model_training_path)
    except ValueError as error:
        raise HTTPException(409, f"训练评估结果一致性校验失败：{error}") from error


@router.get("/comparison/export")
async def export_comparison(
    job_ids: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    requested_ids = list(dict.fromkeys(item.strip() for item in (job_ids or "").split(",") if item.strip()))
    if requested_ids:
        if not (2 <= len(requested_ids) <= len(EXPERIMENTS)):
            raise HTTPException(422, f"对比导出必须选择 2 到 {len(EXPERIMENTS)} 项训练任务")
        jobs = list((await db.scalars(
            select(ModelTrainingJob)
            .where(ModelTrainingJob.id.in_(requested_ids), ModelTrainingJob.status == "completed")
        )).all())
        if len(jobs) != len(requested_ids):
            raise HTTPException(409, "所选批次仍有任务未完成，暂不能导出对比结果")
        fingerprints = {job.dataset_fingerprint for job in jobs if job.dataset_fingerprint}
        if len(fingerprints) != 1 or any(not job.dataset_fingerprint for job in jobs):
            raise HTTPException(409, "所选任务未使用同一冻结训练数据，不能直接横向比较")
        experiment_types = [
            str((job.config_snapshot or {}).get("experiment_type") or "") for job in jobs
        ]
        if len(set(experiment_types)) != len(jobs):
            raise HTTPException(409, "所选任务包含重复的实验方案，不能重复比较同一方案")
    else:
        jobs = list((await db.scalars(
            select(ModelTrainingJob)
            .where(ModelTrainingJob.status == "completed")
            .order_by(ModelTrainingJob.completed_at.desc(), ModelTrainingJob.id.desc())
        )).all())
    latest: dict[str, ModelTrainingJob] = {}
    for job in jobs:
        experiment = str((job.config_snapshot or {}).get("experiment_type") or "embedding_linear_svc")
        latest.setdefault(experiment, job)
    if not latest:
        raise HTTPException(409, "尚无已完成的模型可用于对比导出")
    rows: list[list[object]] = []
    for experiment_type in EXPERIMENTS:
        job = latest.get(experiment_type)
        if not job:
            continue
        metrics = job.metrics or {}
        snapshot = dict(job.config_snapshot or {})
        rows.append([
            EXPERIMENTS[experiment_type][2], job.version, job.sample_count,
            metrics.get("accuracy"), metrics.get("macro_precision"), metrics.get("macro_recall"),
            metrics.get("macro_specificity"), metrics.get("macro_f1"), metrics.get("weighted_f1"), metrics.get("macro_auc_ovr"),
            metrics.get("cross_entropy"), "是" if job.is_active else "否",
            "人工调参" if snapshot.get("hyperparameters_tuned") else "默认参数",
            json.dumps(snapshot.get("classifier_parameters") or {}, ensure_ascii=False, sort_keys=True),
            job.completed_at.isoformat() if job.completed_at else "",
        ])
    content = _csv_bytes(
        ["实验方案", "版本", "样本数", "Accuracy", "Macro-Precision", "Macro-Recall", "Macro-Specificity", "Macro-F1", "Weighted-F1", "Macro-AUC", "交叉熵", "生产启用", "参数来源", "分类器参数", "完成时间"],
        rows,
    )
    db.add(AuditLog(
        actor_id=user.id,
        action="model_training.export_comparison",
        target_type="model_training_comparison",
        target_id=None,
        detail={"job_ids": [job.id for job in latest.values()], "row_count": len(rows)},
    ))
    return Response(
        content=content, media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="model-comparison.csv"'},
    )


@router.get("/jobs/{job_id}", response_model=TrainingJobOut)
async def get_job(job_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(require_role("admin"))):
    del user
    job = await db.get(ModelTrainingJob, job_id)
    if not job:
        raise HTTPException(404, "训练任务不存在")
    return job


def _csv_bytes(headers: list[str], rows: list[list[object]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(headers)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8-sig")


@router.get("/jobs/{job_id}/export")
async def export_job_report(job_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(require_role("admin"))):
    job = await db.get(ModelTrainingJob, job_id)
    if not job:
        raise HTTPException(404, "训练任务不存在")
    if job.status != "completed" or not job.metrics:
        raise HTTPException(409, "只有已完成的训练任务可以导出结果")
    db.add(AuditLog(
        actor_id=user.id,
        action="model_training.export_report",
        target_type="model_training_job",
        target_id=job.id,
        detail={"version": job.version},
    ))
    metrics = dict(job.metrics)
    snapshot = dict(job.config_snapshot or {})
    label_names = {0: "非元认知", 1: "监控", 2: "调控", 3: "评估"}
    metric_labels = sorted(int(label) for label in (metrics.get("per_class") or {}).keys())
    labels = [label_names.get(label, f"标签{label}") for label in metric_labels]
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("训练摘要.csv", _csv_bytes(
            ["版本", "实验方案", "状态", "样本数", "参数来源", "分类器参数", "Accuracy", "Macro-Precision", "Macro-Recall", "Macro-Specificity", "Macro-F1", "Weighted-F1", "交叉熵", "Macro-AUC"],
            [[
                job.version, snapshot.get("display_name", ""), job.status,
                job.sample_count, "人工调参" if snapshot.get("hyperparameters_tuned") else "默认参数",
                json.dumps(snapshot.get("classifier_parameters") or {}, ensure_ascii=False, sort_keys=True),
                metrics.get("accuracy"), metrics.get("macro_precision"),
                metrics.get("macro_recall"), metrics.get("macro_specificity"), metrics.get("macro_f1"), metrics.get("weighted_f1"),
                metrics.get("cross_entropy"), metrics.get("macro_auc_ovr"),
            ]],
        ))
        package.writestr("训练参数.csv", _csv_bytes(
            ["参数", "取值", "来源"],
            [[name, value, "人工调参" if snapshot.get("hyperparameters_tuned") else "系统默认"]
             for name, value in (snapshot.get("classifier_parameters") or {}).items()],
        ))
        per_class = metrics.get("per_class") or {}
        package.writestr("各类别指标.csv", _csv_bytes(
            ["标签", "样本数", "Precision", "Recall", "Specificity", "F1"],
            [[label_names.get(label, f"标签{label}"), (per_class.get(str(label)) or {}).get("support"),
              (per_class.get(str(label)) or {}).get("precision"),
              (per_class.get(str(label)) or {}).get("recall"),
              (per_class.get(str(label)) or {}).get("specificity"),
              (per_class.get(str(label)) or {}).get("f1")] for label in metric_labels],
        ))
        package.writestr("五折结果.csv", _csv_bytes(
            ["折", "训练样本数", "测试样本数", "训练Accuracy", "训练Macro-F1", "测试Accuracy", "测试Macro-Precision", "测试Macro-Recall", "测试Macro-Specificity", "测试Macro-F1", "测试Weighted-F1", "训练集类别分布", "测试集类别分布"],
            [[fold.get("fold"), fold.get("train_sample_count"), fold.get("sample_count"),
              fold.get("train_accuracy"), fold.get("train_macro_f1"), fold.get("accuracy"),
              fold.get("macro_precision"), fold.get("macro_recall"), fold.get("macro_specificity"), fold.get("macro_f1"),
              fold.get("weighted_f1"),
              json.dumps(fold.get("train_label_distribution") or {}, ensure_ascii=False),
              json.dumps(fold.get("test_label_distribution") or {}, ensure_ascii=False)]
             for fold in metrics.get("folds", [])],
        ))
        evaluation = metrics.get("evaluation_summary") or {}
        package.writestr("评估数据说明.csv", _csv_bytes(
            ["评估方法", "划分策略", "总样本数", "被试数", "折数", "折外测试总次数", "每条样本仅测试一次", "最终模型全量重拟合", "独立外部测试集", "类别分布"],
            [[evaluation.get("method"), evaluation.get("split_strategy"),
              evaluation.get("sample_count", job.sample_count), evaluation.get("participant_count"),
              evaluation.get("fold_count", 5), evaluation.get("out_of_fold_sample_count"),
              evaluation.get("every_sample_evaluated_once"),
              evaluation.get("final_model_refit_on_all_data"), evaluation.get("external_holdout"),
              json.dumps(evaluation.get("label_distribution") or job.label_distribution or {}, ensure_ascii=False)]],
        ))
        for curve_label, curve in (metrics.get("roc_curves") or {}).items():
            curve_name = "Macro" if curve_label == "macro" else label_names.get(int(curve_label), f"标签{curve_label}")
            package.writestr(f"ROC曲线_{curve_name}.csv", _csv_bytes(
                ["假阳性率FPR", "真阳性率TPR", "AUC"],
                [[fpr, tpr, curve.get("auc")] for fpr, tpr in zip(curve.get("fpr") or [], curve.get("tpr") or [])],
            ))
        matrix = metrics.get("confusion_matrix") or []
        package.writestr("混淆矩阵.csv", _csv_bytes(
            ["真实标签/预测标签", *labels],
            [[labels[index], *row] for index, row in enumerate(matrix)],
        ))
        package.writestr("冻结配置.json", json.dumps(snapshot, ensure_ascii=False, indent=2))
        package.writestr("完整指标.json", json.dumps(metrics, ensure_ascii=False, indent=2))
        package.writestr("说明.txt", (
            "本压缩包为‘知见’元认知分类模型训练结果。\n"
            "训练摘要.csv：整体折外指标；各类别指标.csv：当前训练标签表现；五折结果.csv：每折真实训练/测试数量、分布与性能；"
            "评估数据说明.csv：数据划分及可信边界；ROC曲线_*.csv：绘图使用的真实FPR/TPR点；"
            "混淆矩阵.csv：真实标签与预测标签；冻结配置.json：创建任务时的配置快照。\n"
            "训练参数.csv：本次实际使用的分类器参数及其来源；其中 LinearSVC/LogisticRegression 的 C 即结果对应的精确 C 值。\n"
            "ROC来自五折交叉验证的折外预测，不是最终模型在训练集上的自测，也不是独立外部测试集结果。\n"
            "模型启用仍须由管理员在研究管理页面人工确认。\n"
        ))
    safe_version = "".join(character if character.isalnum() or character in "._-" else "_" for character in job.version)
    return Response(
        content=archive.getvalue(), media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="model-report-{safe_version}.zip"'},
    )


@router.post("/jobs/{job_id}/activate", response_model=TrainingJobOut)
async def activate_job(job_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(require_role("admin"))):
    job = await db.scalar(select(ModelTrainingJob).where(ModelTrainingJob.id == job_id).with_for_update())
    if not job:
        raise HTTPException(404, "训练版本不存在")
    if job.status != "completed" or not job.artifact_path:
        raise HTTPException(409, "只有训练完成且产物完整的版本可以启用")
    await load_runtime_model_settings(db, settings)
    try:
        load_model_artifact(job, settings)
        await probe_model_activation(job, settings)
    except Exception as error:
        raise HTTPException(409, f"模型产物或推理探针校验失败：{error}") from error
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    previous = await db.scalar(select(ModelTrainingJob).where(ModelTrainingJob.is_active.is_(True)))
    await db.execute(update(ModelTrainingJob).where(ModelTrainingJob.is_active.is_(True)).values(is_active=False))
    job.is_active = True
    job.activated_by = user.id
    job.activated_at = now
    db.add(AuditLog(actor_id=user.id, action="model_training.activate", target_type="model_training_job", target_id=job.id, detail={"version": job.version, "previous_version": previous.version if previous else None}))
    await db.commit()
    await db.refresh(job)
    return job


@router.post("/jobs/{job_id}/deactivate", response_model=TrainingJobOut)
async def deactivate_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    """Remove the production designation without deleting the trained artifact."""
    job = await db.scalar(
        select(ModelTrainingJob).where(ModelTrainingJob.id == job_id).with_for_update()
    )
    if not job:
        raise HTTPException(404, "训练版本不存在")
    if not job.is_active:
        raise HTTPException(409, "该模型当前未启用")
    job.is_active = False
    db.add(AuditLog(
        actor_id=user.id,
        action="model_training.deactivate",
        target_type="model_training_job",
        target_id=job.id,
        detail={"version": job.version},
    ))
    await db.commit()
    await db.refresh(job)
    return job


@router.post("/jobs/{job_id}/cancel", response_model=TrainingJobOut)
async def cancel_job(job_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(require_role("admin"))):
    job = await db.scalar(select(ModelTrainingJob).where(ModelTrainingJob.id == job_id).with_for_update())
    if not job:
        raise HTTPException(404, "训练任务不存在")
    if job.status not in {"queued", "running"}:
        raise HTTPException(409, "只有排队中或训练中的任务可以取消")
    if job.status == "queued":
        job.status = "cancelled"
        job.stage = "cancelled"
        job.completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    else:
        job.cancel_requested = True
    db.add(AuditLog(actor_id=user.id, action="model_training.cancel", target_type="model_training_job", target_id=job.id, detail={"version": job.version, "status": job.status}))
    await db.commit()
    await db.refresh(job)
    return job


@router.post("/jobs/{job_id}/retry", response_model=TrainingJobOut, status_code=201)
async def retry_job(job_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(require_role("admin"))):
    source = await db.get(ModelTrainingJob, job_id)
    if not source:
        raise HTTPException(404, "训练任务不存在")
    if source.status not in {"failed", "cancelled"}:
        raise HTTPException(409, "只有失败或已取消的任务可以重新运行")
    snapshot = dict(source.config_snapshot or {})
    snapshot["training_pipeline_version"] = TRAINING_PIPELINE_VERSION
    snapshot["training_labels"] = [1, 2, 3]
    dataset_id = str(snapshot.get("dataset_id") or "")
    retry_sample_count = source.sample_count
    retry_distribution = dict(source.label_distribution or {}) or None
    retry_fingerprint = source.dataset_fingerprint
    if snapshot.get("dataset_source") == "uploaded":
        if not dataset_id:
            raise HTTPException(409, "该历史任务未绑定上传数据快照，不能直接重试，请重新创建训练任务")
        try:
            samples = load_dataset_samples(settings.model_training_path, dataset_id)
        except ValueError as error:
            raise HTTPException(409, f"上传数据快照预检失败：{error}") from error
        training_samples = [item for item in samples if item[2] in {1, 2, 3}]
        retry_sample_count = len(training_samples)
        retry_distribution = {
            str(label): sum(1 for item in training_samples if item[2] == label)
            for label in (1, 2, 3)
        }
        retry_fingerprint = str(snapshot.get("dataset_fingerprint") or source.dataset_fingerprint or "") or None
    root_version = re.sub(r"(?:-retry\d+)+$", "", source.version)[:54]
    prefix = f"{root_version}-retry"
    existing = list((await db.scalars(
        select(ModelTrainingJob.version).where(ModelTrainingJob.version.like(f"{root_version}-retry%"))
    )).all())
    indices = [
        int(match.group(1)) for version in existing
        if (match := re.fullmatch(rf"{re.escape(root_version)}-retry(\d+)", version))
    ]
    index = max(indices, default=0) + 1
    job = ModelTrainingJob(
        version=f"{prefix}{index}", requested_by=user.id,
        config_snapshot=snapshot, parent_job_id=source.id,
        sample_count=retry_sample_count,
        label_distribution=retry_distribution,
        dataset_fingerprint=retry_fingerprint,
    )
    db.add(job)
    await db.flush()
    db.add(AuditLog(actor_id=user.id, action="model_training.retry", target_type="model_training_job", target_id=job.id, detail={"version": job.version, "source_job_id": source.id, "source_version": source.version}))
    await db.commit()
    await db.refresh(job)
    return job


@router.get("/audit", response_model=list[TrainingAuditOut])
async def list_training_audit(db: AsyncSession = Depends(get_db), user: User = Depends(require_role("admin"))):
    del user
    rows = (await db.execute(
        select(AuditLog, User.name)
        .outerjoin(User, User.id == AuditLog.actor_id)
        .where(AuditLog.action.like("model_training.%"))
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(300)
    )).all()
    return [TrainingAuditOut(
        id=audit.id, action=audit.action, job_id=audit.target_id,
        version=(audit.detail or {}).get("version"), actor_name=actor_name,
        detail=audit.detail, created_at=audit.created_at,
    ) for audit, actor_name in rows]
