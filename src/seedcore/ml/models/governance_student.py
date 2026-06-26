from __future__ import annotations

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
