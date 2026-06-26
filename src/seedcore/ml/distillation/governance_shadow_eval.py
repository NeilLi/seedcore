from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Sequence

from pydantic import ValidationError

from seedcore.ml.distillation.governance_dataset import GovernanceDatasetRow
from seedcore.models.governance_advisory import GovernanceAdvisoryOutputV1


@dataclass(frozen=True)
class GovernanceShadowEvalMetrics:
    total: int
    exact_reason_matches: int
    taxonomy_valid_predictions: int
    trust_gap_true_positive: int
    trust_gap_false_positive: int
    trust_gap_false_negative: int
    abstention_matches: int
    false_safe_advisory_count: int
    authority_usage_count: int

    @property
    def exact_reason_match_rate(self) -> float:
        return _rate(self.exact_reason_matches, self.total)

    @property
    def taxonomy_valid_rate(self) -> float:
        return _rate(self.taxonomy_valid_predictions, self.total)

    @property
    def trust_gap_precision(self) -> float:
        return _rate(
            self.trust_gap_true_positive,
            self.trust_gap_true_positive + self.trust_gap_false_positive,
        )

    @property
    def trust_gap_recall(self) -> float:
        return _rate(
            self.trust_gap_true_positive,
            self.trust_gap_true_positive + self.trust_gap_false_negative,
        )

    @property
    def abstention_match_rate(self) -> float:
        return _rate(self.abstention_matches, self.total)


def evaluate_shadow_student(student, rows: Iterable[GovernanceDatasetRow]) -> GovernanceShadowEvalMetrics:
    resolved_rows = tuple(rows)
    predictions = student.predict_batch([row.features for row in resolved_rows])
    return evaluate_predictions(resolved_rows, predictions)


def evaluate_predictions(
    rows: Sequence[GovernanceDatasetRow],
    predictions: Sequence[GovernanceAdvisoryOutputV1],
) -> GovernanceShadowEvalMetrics:
    if len(rows) != len(predictions):
        raise ValueError("rows and predictions must have the same length")

    exact_reason_matches = 0
    taxonomy_valid_predictions = 0
    trust_gap_true_positive = 0
    trust_gap_false_positive = 0
    trust_gap_false_negative = 0
    abstention_matches = 0
    false_safe_advisory_count = 0
    authority_usage_count = 0

    for row, raw_prediction in zip(rows, predictions):
        prediction = _coerce_prediction(raw_prediction)
        taxonomy_valid_predictions += 1
        teacher = row.label

        if prediction.reason_code == teacher.reason_code:
            exact_reason_matches += 1
        if prediction.abstain == teacher.abstain:
            abstention_matches += 1
        if teacher.abstain and not prediction.abstain:
            false_safe_advisory_count += 1
        if prediction.student_final_authority_usage != 0:
            authority_usage_count += 1

        predicted_gaps = set(prediction.trust_gap_codes)
        expected_gaps = set(teacher.trust_gap_codes)
        trust_gap_true_positive += len(predicted_gaps & expected_gaps)
        trust_gap_false_positive += len(predicted_gaps - expected_gaps)
        trust_gap_false_negative += len(expected_gaps - predicted_gaps)

    if authority_usage_count:
        raise ValueError("student_final_authority_usage must remain zero")

    return GovernanceShadowEvalMetrics(
        total=len(rows),
        exact_reason_matches=exact_reason_matches,
        taxonomy_valid_predictions=taxonomy_valid_predictions,
        trust_gap_true_positive=trust_gap_true_positive,
        trust_gap_false_positive=trust_gap_false_positive,
        trust_gap_false_negative=trust_gap_false_negative,
        abstention_matches=abstention_matches,
        false_safe_advisory_count=false_safe_advisory_count,
        authority_usage_count=authority_usage_count,
    )


def _coerce_prediction(raw_prediction) -> GovernanceAdvisoryOutputV1:
    if isinstance(raw_prediction, GovernanceAdvisoryOutputV1):
        return GovernanceAdvisoryOutputV1(**raw_prediction.model_dump())
    if isinstance(raw_prediction, dict):
        try:
            return GovernanceAdvisoryOutputV1(**raw_prediction)
        except ValidationError as exc:
            raise ValueError("prediction is not a valid GovernanceAdvisoryOutputV1") from exc
    try:
        return GovernanceAdvisoryOutputV1(**raw_prediction.__dict__)
    except (TypeError, ValidationError, AttributeError) as exc:
        raise ValueError("prediction is not a valid GovernanceAdvisoryOutputV1") from exc


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator
