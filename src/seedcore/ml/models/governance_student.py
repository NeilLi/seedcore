from __future__ import annotations

from threading import Lock
from typing import Dict, Iterable, List, Sequence, Tuple

from seedcore.ml.distillation.governance_dataset import GovernanceDatasetRow
from seedcore.models.governance_advisory import GovernanceAdvisoryOutputV1


class GovernanceShadowStudent:
    """
    Offline, conservative baseline for Window H shadow evaluation.

    The v1 student memorizes exact fitted feature rows. Unknown rows fall back
    to a schema-valid abstention instead of inventing safe authority.
    """

    def __init__(self) -> None:
        self._labels_by_features: Dict[Tuple[float, ...], GovernanceAdvisoryOutputV1] = {}
        self._default_label = GovernanceAdvisoryOutputV1(
            reason_code="student_abstain_unknown",
            missing_authority_context=["unknown_authority_context"],
            evidence_risk_flags=["unknown_sample"],
            abstain=True,
            abstain_reasons=["student_unknown_sample"],
        )

    def fit(self, rows: Iterable[GovernanceDatasetRow]) -> "GovernanceShadowStudent":
        for row in rows:
            self._labels_by_features[self._feature_key(row.features)] = row.label
        return self

    def predict_one(self, features: Sequence[float]) -> GovernanceAdvisoryOutputV1:
        return self._labels_by_features.get(self._feature_key(features), self._default_label)

    def predict_batch(self, feature_rows: Iterable[Sequence[float]]) -> List[GovernanceAdvisoryOutputV1]:
        return [self.predict_one(features) for features in feature_rows]

    @staticmethod
    def _feature_key(features: Sequence[float]) -> Tuple[float, ...]:
        return tuple(round(float(value), 8) for value in features)


_ACTIVE_STUDENT: GovernanceShadowStudent | None = None
_ACTIVE_STUDENT_LOCK = Lock()


def get_active_shadow_student() -> GovernanceShadowStudent:
    """Return the process-local Window H shadow student.

    The default student is intentionally conservative: without explicit training
    it abstains for every unknown feature row.
    """
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
