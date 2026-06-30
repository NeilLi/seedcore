from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from seedcore.ml.distillation.governance_dataset import GovernanceDatasetRow
from seedcore.models.governance_advisory import GovernanceAdvisoryOutputV1


class GovernanceShadowStudent:
    """
    Window H shadow student for advisory evaluation.

    Supports both conservative exact-row table lookup and XGBoost backends.
    Unknown/uncertain predictions fall back to a schema-valid abstention.
    """

    def __init__(self, model_dir: str | None = None) -> None:
        self.backend = "conservative_exact_row"
        self._labels_by_features: Dict[Tuple[float, ...], GovernanceAdvisoryOutputV1] = {}
        self._default_label = GovernanceAdvisoryOutputV1(
            reason_code="student_abstain_unknown",
            missing_authority_context=["unknown_authority_context"],
            evidence_risk_flags=["unknown_sample"],
            abstain=True,
            abstain_reasons=["student_unknown_sample"],
        )
        self.model_dir = model_dir
        self._abstention_model = None
        self._reason_model = None
        self.metadata: Dict[str, Any] = {}
        self.load()

    def fit(self, rows: Iterable[GovernanceDatasetRow]) -> "GovernanceShadowStudent":
        self.backend = "conservative_exact_row"
        for row in rows:
            self._labels_by_features[self._feature_key(row.features)] = row.label
        return self

    def load(self) -> None:
        path_str = self.model_dir or os.getenv("SEEDCORE_GOVERNANCE_STUDENT_PATH")
        if not path_str:
            storage_path = os.getenv("XGB_STORAGE_PATH", "/app/data/models")
            path_str = str(Path(storage_path) / "governance_shadow_student")

        dir_path = Path(path_str)
        metadata_file = dir_path / "metadata.json"

        if not metadata_file.is_file():
            return

        try:
            with open(metadata_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
            backend = meta.get("backend", "conservative_exact_row")
            if backend == "xgboost":
                import xgboost as xgb
                abstention_file = dir_path / "abstention_model.json"
                reason_file = dir_path / "reason_model.json"
                if abstention_file.is_file() and reason_file.is_file():
                    abs_bst = xgb.Booster()
                    abs_bst.load_model(str(abstention_file))
                    res_bst = xgb.Booster()
                    res_bst.load_model(str(reason_file))

                    self._abstention_model = abs_bst
                    self._reason_model = res_bst
                    self.metadata = meta
                    self.backend = "xgboost"
            else:
                self.backend = "conservative_exact_row"
        except Exception:
            # Fall back to default/exact row
            pass

    def save(self, path_str: str | None = None) -> None:
        target_path = path_str or self.model_dir or os.getenv("SEEDCORE_GOVERNANCE_STUDENT_PATH")
        if not target_path:
            storage_path = os.getenv("XGB_STORAGE_PATH", "/app/data/models")
            target_path = str(Path(storage_path) / "governance_shadow_student")

        dir_path = Path(target_path)
        dir_path.mkdir(parents=True, exist_ok=True)

        metadata_file = dir_path / "metadata.json"
        with open(metadata_file, "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, indent=2, default=str)

        if self.backend == "xgboost":
            import xgboost as xgb
            if self._abstention_model:
                self._abstention_model.save_model(str(dir_path / "abstention_model.json"))
            if self._reason_model:
                self._reason_model.save_model(str(dir_path / "reason_model.json"))

    def predict_one(self, features: Sequence[float]) -> GovernanceAdvisoryOutputV1:
        if self.backend == "xgboost" and self._abstention_model is not None and self._reason_model is not None:
            try:
                import numpy as np
                import xgboost as xgb

                feat_names = self.metadata.get("feature_names", [])
                if len(features) != len(feat_names):
                    return self._default_label

                x = np.array([features], dtype=np.float32)
                dmat = xgb.DMatrix(x, feature_names=list(feat_names))

                # 1. Predict abstention (probability of abstain)
                prob_abstain = float(self._abstention_model.predict(dmat)[0])

                # 2. Predict reason code multiclass
                prob_reasons = self._reason_model.predict(dmat)[0]
                pred_class_idx = int(np.argmax(prob_reasons))
                reason_confidence = float(prob_reasons[pred_class_idx])

                idx_to_reason = self.metadata.get("reason_code_map_reverse", {})
                reason_code = idx_to_reason.get(str(pred_class_idx))

                thresholds = self.metadata.get("thresholds", {})
                conf_thresh_abstain = float(thresholds.get("confidence_threshold_abstain", 0.8))
                conf_thresh_reason = float(thresholds.get("confidence_threshold_reason", 0.8))

                # Non-abstain is allowed ONLY when the abstention classifier confidently predicts clean-allow
                # (1.0 - prob_abstain) is the probability of clean-allow (abstain = False)
                is_confident_clean_allow = (1.0 - prob_abstain) >= conf_thresh_abstain

                abstain = True
                if is_confident_clean_allow and reason_confidence >= conf_thresh_reason:
                    templates = self.metadata.get("label_templates", {})
                    template = templates.get(reason_code)
                    if template and not template.get("abstain", True):
                        abstain = False

                templates = self.metadata.get("label_templates", {})
                template = templates.get(reason_code)

                if not template:
                    return self._default_label

                return GovernanceAdvisoryOutputV1(
                    reason_code=reason_code,
                    trust_gap_codes=list(template.get("trust_gap_codes", [])),
                    missing_authority_context=list(template.get("missing_authority_context", [])),
                    evidence_risk_flags=list(template.get("evidence_risk_flags", [])),
                    required_obligations=[dict(o) for o in template.get("required_obligations", [])],
                    abstain=abstain,
                    abstain_reasons=list(template.get("abstain_reasons", [])) if abstain else [],
                )
            except Exception:
                return self._default_label
        else:
            return self._labels_by_features.get(self._feature_key(features), self._default_label)

    def predict_batch(self, feature_rows: Iterable[Sequence[float]]) -> List[GovernanceAdvisoryOutputV1]:
        return [self.predict_one(features) for features in feature_rows]

    @staticmethod
    def _feature_key(features: Sequence[float]) -> Tuple[float, ...]:
        return tuple(round(float(value), 8) for value in features)


_ACTIVE_STUDENT: GovernanceShadowStudent | None = None
_ACTIVE_STUDENT_LOCK = Lock()


def get_active_shadow_student() -> GovernanceShadowStudent:
    """Return the process-local Window H shadow student."""
    global _ACTIVE_STUDENT
    with _ACTIVE_STUDENT_LOCK:
        if _ACTIVE_STUDENT is None:
            _ACTIVE_STUDENT = GovernanceShadowStudent()
        return _ACTIVE_STUDENT


def set_active_shadow_student(student: GovernanceShadowStudent) -> GovernanceShadowStudent:
    global _ACTIVE_STUDENT
    with _ACTIVE_STUDENT_LOCK:
        _ACTIVE_STUDENT = student
        return _ACTIVE_STUDENT


def train_conservative_shadow_student(
    rows: Iterable[GovernanceDatasetRow],
) -> GovernanceShadowStudent:
    return set_active_shadow_student(GovernanceShadowStudent().fit(rows))


def train_xgboost_shadow_student(
    rows: Iterable[GovernanceDatasetRow],
    eval_rows: Iterable[GovernanceDatasetRow],
    feature_names: Sequence[str],
    *,
    thresholds: dict[str, Any] | None = None,
    xgb_config: dict[str, Any] | None = None,
) -> GovernanceShadowStudent:
    import numpy as np
    import xgboost as xgb

    rows_list = list(rows)
    eval_rows_list = list(eval_rows)
    all_rows = rows_list + eval_rows_list

    if not rows_list:
        raise ValueError("Cannot train XGBoost shadow student: training rows are empty")

    # 1. Feature matrices
    X_train = np.array([row.features for row in rows_list], dtype=np.float32)

    # 2. Abstain targets (1.0 if row.label.abstain else 0.0)
    y_abstain = np.array([1.0 if row.label.abstain else 0.0 for row in rows_list], dtype=np.float32)

    # 3. Multiclass targets
    unique_reasons = sorted(list(set(row.label.reason_code for row in all_rows)))
    reason_to_idx = {reason: idx for idx, reason in enumerate(unique_reasons)}
    idx_to_reason = {idx: reason for idx, reason in enumerate(unique_reasons)}
    y_reason = np.array([reason_to_idx[row.label.reason_code] for row in rows_list], dtype=np.float32)

    # 4. Templates
    label_templates = {}
    for row in all_rows:
        reason = row.label.reason_code
        if reason not in label_templates:
            label_templates[reason] = {
                "trust_gap_codes": list(row.label.trust_gap_codes),
                "missing_authority_context": list(row.label.missing_authority_context),
                "evidence_risk_flags": list(row.label.evidence_risk_flags),
                "required_obligations": [dict(o) for o in row.label.required_obligations],
                "abstain": bool(row.label.abstain),
                "abstain_reasons": list(row.label.abstain_reasons),
            }

    # 5. Thresholds
    resolved_thresholds = {
        "confidence_threshold_abstain": float((thresholds or {}).get("confidence_threshold_abstain", 0.8)),
        "confidence_threshold_reason": float((thresholds or {}).get("confidence_threshold_reason", 0.8)),
    }

    # 6. XGB params
    num_boost_round = int((xgb_config or {}).get("num_boost_round", 50))

    abs_params = {
        "objective": "binary:logistic",
        "eval_metric": "logloss",
        "max_depth": int((xgb_config or {}).get("max_depth", 5)),
        "eta": float((xgb_config or {}).get("eta", 0.1)),
        "tree_method": str((xgb_config or {}).get("tree_method", "hist")),
    }

    dtrain_abs = xgb.DMatrix(X_train, label=y_abstain, feature_names=list(feature_names))
    bst_abs = xgb.train(abs_params, dtrain_abs, num_boost_round=num_boost_round)

    res_params = {
        "objective": "multi:softprob",
        "eval_metric": "mlogloss",
        "num_class": len(unique_reasons),
        "max_depth": int((xgb_config or {}).get("max_depth", 5)),
        "eta": float((xgb_config or {}).get("eta", 0.1)),
        "tree_method": str((xgb_config or {}).get("tree_method", "hist")),
    }
    dtrain_res = xgb.DMatrix(X_train, label=y_reason, feature_names=list(feature_names))
    bst_res = xgb.train(res_params, dtrain_res, num_boost_round=num_boost_round)

    metadata = {
        "backend": "xgboost",
        "feature_names": list(feature_names),
        "reason_code_map": reason_to_idx,
        "reason_code_map_reverse": {str(k): v for k, v in idx_to_reason.items()},
        "label_templates": label_templates,
        "thresholds": resolved_thresholds,
        "training_metrics": {},
    }

    student = GovernanceShadowStudent()
    student.backend = "xgboost"
    student._abstention_model = bst_abs
    student._reason_model = bst_res
    student.metadata = metadata

    return set_active_shadow_student(student)
