"""Diagnostic comparison of prespecified TF-IDF logistic configurations."""

from __future__ import annotations

import warnings

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.pipeline import Pipeline

from train_tfidf_logistic import LABELS, N_FOLDS, RANDOM_STATE, load_and_validate_data


VARIANTS = [
    ("saga_balanced", "saga", "balanced"),
    ("lbfgs_balanced", "lbfgs", "balanced"),
    ("lbfgs_unweighted", "lbfgs", None),
]


def build_model(solver: str, class_weight: str | None) -> Pipeline:
    return Pipeline(
        [
            (
                "tfidf",
                TfidfVectorizer(
                    analyzer="char",
                    ngram_range=(2, 5),
                    min_df=2,
                    max_features=20_000,
                    sublinear_tf=True,
                    norm="l2",
                ),
            ),
            (
                "classifier",
                LogisticRegression(
                    C=1.0,
                    class_weight=class_weight,
                    solver=solver,
                    max_iter=5_000,
                    random_state=RANDOM_STATE,
                ),
            ),
        ]
    )


def main() -> None:
    data = load_and_validate_data()
    for name, solver, class_weight in VARIANTS:
        fold_scores: list[float] = []
        fold_accuracy: list[float] = []
        warning_count = 0
        for fold in range(1, N_FOLDS + 1):
            train = data[data["fold"] != fold]
            test = data[data["fold"] == fold]
            model = build_model(solver, class_weight)
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", ConvergenceWarning)
                model.fit(train["cleaned_text"], train["label_train"])
            warning_count += sum(issubclass(item.category, ConvergenceWarning) for item in caught)
            prediction = model.predict(test["cleaned_text"])
            fold_scores.append(f1_score(test["label_train"], prediction, labels=LABELS, average="macro", zero_division=0))
            fold_accuracy.append(accuracy_score(test["label_train"], prediction))
        print(
            f"{name}: macro_f1={np.mean(fold_scores):.4f}±{np.std(fold_scores, ddof=1):.4f}; "
            f"accuracy={np.mean(fold_accuracy):.4f}; convergence_warnings={warning_count}; "
            f"fold_f1={[round(value, 4) for value in fold_scores]}"
        )


if __name__ == "__main__":
    main()
