"""Validated, versioned hyperparameter contract for every training experiment."""
from __future__ import annotations

from typing import Any


def _number(label: str, default: float, minimum: float, maximum: float, step: float, description: str):
    return {"type": "number", "label": label, "default": default, "min": minimum, "max": maximum, "step": step, "description": description}


def _integer(label: str, default: int, minimum: int, maximum: int, step: int, description: str):
    return {"type": "integer", "label": label, "default": default, "min": minimum, "max": maximum, "step": step, "description": description}


def _choice(label: str, default: str, choices: list[str], description: str):
    return {"type": "choice", "label": label, "default": default, "choices": choices, "description": description}


HYPERPARAMETER_SPECS: dict[str, dict[str, dict[str, Any]]] = {
    "tfidf_linear_svc": {
        "C": _number("惩罚系数 C", 1.0, 0.001, 100.0, 0.1, "C 越大越强调训练集拟合，边界更窄；C 越小正则化越强。结果页面会明确记录本次使用的 C。"),
        "class_weight": _choice(
            "类别权重",
            "balanced",
            ["balanced", "none"],
            "balanced 会按训练折内类别频数自动提高少数类权重；none 不进行类别加权。应结合折外 Macro-F1 与三类 F1 判断。",
        ),
        "max_iter": _integer("最大迭代次数", 5000, 500, 20000, 500, "求解器允许的最大迭代次数；只有出现未收敛警告时才建议增加。"),
    },
    "embedding_linear_svc": {
        "C": _number("惩罚系数 C", 1.0, 0.001, 100.0, 0.1, "控制分类间隔与训练误差的权衡；C 较大更贴合训练数据，也更可能过拟合。"),
        "class_weight": _choice(
            "类别权重",
            "balanced",
            ["balanced", "none"],
            "balanced 会按训练折内类别频数自动提高少数类权重；none 不进行类别加权。类别不均衡时通常优先 balanced。",
        ),
        "max_iter": _integer("最大迭代次数", 5000, 500, 20000, 500, "线性 SVM 的最大求解迭代数。"),
    },
    "embedding_logistic": {
        "C": _number("逆正则化强度 C", 1.0, 0.001, 100.0, 0.1, "C 越小正则化越强；C 越大模型更贴合训练数据。该值直接影响概率边界。"),
        "class_weight": _choice(
            "类别权重",
            "balanced",
            ["balanced", "none"],
            "balanced 会按训练折内各类别样本数自动给予少数类更高权重；none 不进行类别加权。类别不均衡时通常优先 balanced，但必须以折外 Macro-F1 和各类别 F1 为准。",
        ),
        "max_iter": _integer("最大迭代次数", 2000, 200, 10000, 200, "逻辑回归求解器的最大迭代数。"),
    },
    "embedding_random_forest": {
        "n_estimators": _integer("树数量", 300, 50, 1200, 50, "森林中的树数量；更多通常更稳定，但训练、模型体积和推理耗时增加。"),
        "max_depth": _integer("最大树深", 0, 0, 40, 1, "限制单棵树复杂度；0 表示不限制，较小值可抑制过拟合。"),
        "min_samples_leaf": _integer("叶节点最少样本", 1, 1, 50, 1, "叶节点至少包含的样本数；增大可得到更平滑、更保守的模型。"),
        "max_features": _choice("每次分裂特征数", "sqrt", ["sqrt", "log2", "all"], "每次分裂考虑的特征比例；all 使用全部向量维度，计算量更高。"),
    },
    "embedding_xgboost": {
        "n_estimators": _integer("树数量（trees）", 300, 50, 1500, 50, "XGBoost 中实际控制树数量的参数；需与学习率共同调整，树越多训练时间和模型体积通常越大。"),
        "max_depth": _integer("最大树深", 6, 2, 16, 1, "单棵树最大深度；越深表达能力越强，也越容易过拟合。"),
        "min_child_weight": _number("子节点最小权重（min_child）", 1.0, 0.0, 100.0, 0.5, "子节点继续分裂所需的最小样本权重和；数值越大模型越保守，可抑制小样本节点造成的过拟合。"),
        "learning_rate": _number("学习率", 0.05, 0.005, 0.5, 0.005, "每轮新增树的贡献比例；越小通常需要更多提升轮数。"),
        "subsample": _number("样本采样比例", 0.9, 0.5, 1.0, 0.05, "每轮使用的训练样本比例；小于 1 可增加随机性并抑制过拟合。"),
        "colsample_bytree": _number("特征采样比例", 0.9, 0.3, 1.0, 0.05, "每棵树使用的向量维度比例。"),
        "reg_alpha": _number("L1 正则", 0.0, 0.0, 20.0, 0.1, "叶权重的 L1 正则化，增大可产生更稀疏的模型。"),
        "reg_lambda": _number("L2 正则", 1.0, 0.0, 50.0, 0.1, "叶权重的 L2 正则化，增大可使模型更保守。"),
    },
    "embedding_lightgbm": {
        "n_estimators": _integer("提升轮数", 300, 50, 1500, 50, "提升树数量；与学习率共同决定拟合程度和训练时间。"),
        "num_leaves": _integer("最大叶子数", 31, 4, 255, 1, "单棵树叶子数量上限，是 LightGBM 控制模型复杂度的核心参数。"),
        "max_depth": _integer("最大树深", -1, -1, 32, 1, "-1 表示不限制；设置正值可限制叶子优先生长带来的复杂度。"),
        "learning_rate": _number("学习率", 0.05, 0.005, 0.5, 0.005, "每轮提升步长；较小值通常需要更多提升轮数。"),
        "min_child_samples": _integer("叶节点最少样本", 20, 2, 100, 1, "叶节点最少样本数；增大有助于抑制小样本过拟合。"),
        "subsample": _number("样本采样比例", 0.9, 0.5, 1.0, 0.05, "每轮树使用的样本比例。"),
        "colsample_bytree": _number("特征采样比例", 0.9, 0.3, 1.0, 0.05, "每棵树使用的向量维度比例。"),
        "reg_alpha": _number("L1 正则", 0.0, 0.0, 20.0, 0.1, "叶权重 L1 正则化。"),
        "reg_lambda": _number("L2 正则", 0.0, 0.0, 50.0, 0.1, "叶权重 L2 正则化。"),
    },
    "embedding_catboost": {
        "iterations": _integer("迭代轮数", 300, 50, 1500, 50, "最多构建的树数量；较多轮数需要搭配较小学习率。"),
        "depth": _integer("树深", 6, 2, 12, 1, "对称树深度；深度增加会快速提高模型复杂度与内存需求。"),
        "learning_rate": _number("学习率", 0.05, 0.005, 0.5, 0.005, "每轮梯度更新步长。"),
        "l2_leaf_reg": _number("叶节点 L2 正则", 3.0, 0.01, 100.0, 0.1, "叶节点权重的 L2 正则化系数，增大可抑制过拟合。"),
        "random_strength": _number("分裂随机强度", 1.0, 0.0, 20.0, 0.1, "选择分裂时加入的随机程度，可用于降低过拟合。"),
    },
}


def default_hyperparameters(experiment_type: str) -> dict[str, Any]:
    specs = HYPERPARAMETER_SPECS.get(experiment_type)
    if specs is None:
        raise ValueError(f"不支持的训练方案：{experiment_type}")
    return {name: definition["default"] for name, definition in specs.items()}


def normalize_hyperparameters(experiment_type: str, values: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
    specs = HYPERPARAMETER_SPECS.get(experiment_type)
    if specs is None:
        raise ValueError(f"不支持的训练方案：{experiment_type}")
    supplied = dict(values or {})
    unknown = sorted(set(supplied) - set(specs))
    if unknown:
        raise ValueError(f"{experiment_type} 包含不支持的参数：{', '.join(unknown)}")
    normalized = default_hyperparameters(experiment_type)
    for name, value in supplied.items():
        definition = specs[name]
        if definition["type"] == "choice":
            if value not in definition["choices"]:
                raise ValueError(f"参数 {name} 只能是：{', '.join(definition['choices'])}")
            normalized[name] = value
            continue
        try:
            parsed = int(value) if definition["type"] == "integer" else float(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"参数 {name} 必须是有效数字") from error
        if parsed < definition["min"] or parsed > definition["max"]:
            raise ValueError(f"参数 {name} 必须在 {definition['min']} 到 {definition['max']} 之间")
        normalized[name] = parsed
    return normalized, bool(supplied)


def public_hyperparameter_catalog() -> dict[str, Any]:
    return {
        experiment: {"parameters": definitions, "defaults": default_hyperparameters(experiment)}
        for experiment, definitions in HYPERPARAMETER_SPECS.items()
    }
