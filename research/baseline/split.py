from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupShuffleSplit, train_test_split

from .constants import LABELS, RANDOM_STATE


@dataclass(frozen=True)
class DatasetSplit:
    train_indices: np.ndarray
    test_indices: np.ndarray
    strategy: str
    leakage_warning: str | None


def split_dataset(frame: pd.DataFrame, test_size: float = 0.2) -> DatasetSplit:
    labels = frame["_label"].to_numpy()
    has_groups = "_group_id" in frame and bool((frame["_group_id"] != "").all())
    if has_groups:
        groups = frame["_group_id"].to_numpy()
        best: tuple[float, np.ndarray, np.ndarray] | None = None
        overall = frame["_label"].value_counts(normalize=True)
        for seed in range(RANDOM_STATE, RANDOM_STATE + 200):
            splitter = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=seed)
            train_idx, test_idx = next(splitter.split(frame, labels, groups))
            train_labels = set(labels[train_idx])
            test_labels = set(labels[test_idx])
            if train_labels != set(LABELS) or test_labels != set(LABELS):
                continue
            test_distribution = frame.iloc[test_idx]["_label"].value_counts(normalize=True)
            distance = float(sum(abs(test_distribution.get(label, 0) - overall.get(label, 0)) for label in LABELS))
            if best is None or distance < best[0]:
                best = (distance, train_idx, test_idx)
        if best is None:
            raise ValueError("无法生成训练集和测试集均包含四类的被试级划分；请补充稀有类别被试")
        _, train_idx, test_idx = best
        train_groups = set(groups[train_idx])
        test_groups = set(groups[test_idx])
        assert train_groups.isdisjoint(test_groups), "subject leakage detected"
        return DatasetSplit(train_idx, test_idx, "GroupShuffleSplit", None)

    indices = np.arange(len(frame))
    train_idx, test_idx = train_test_split(
        indices,
        test_size=test_size,
        stratify=labels,
        random_state=RANDOM_STATE,
    )
    return DatasetSplit(
        np.asarray(train_idx),
        np.asarray(test_idx),
        "train_test_split(stratified)",
        "缺少可靠被试ID，存在潜在 subject leakage 风险",
    )
