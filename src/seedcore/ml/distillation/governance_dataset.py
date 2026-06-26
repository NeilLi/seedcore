from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

from seedcore.ml.distillation.sample_store import load_governance_dataset
from seedcore.models.governance_advisory import GovernanceAdvisoryOutputV1
from seedcore.models.governance_learning import GovernanceLearningSampleV1
from seedcore.ops.governance_learning.labeler import GovernanceAdvisoryLabeler


FEATURE_NAMES: Tuple[str, ...] = (
    "telemetry_age_seconds",
    "has_valid_coordinates",
    "has_valid_signature",
    "has_matching_assets",
    "device_enrolled",
    "is_approved_zone",
    "approval_envelope_present",
    "declared_value_usd",
    "requires_co_signature",
    "trust_gap_count",
    "distance_to_boundary",
    "has_transition_receipts",
    "has_policy_receipt",
    "has_asset_fingerprint",
    "signer_profile_known",
    "telemetry_count",
    "media_count",
)


@dataclass(frozen=True)
class GovernanceDatasetRow:
    sample_id: str
    request_id: str
    features: Tuple[float, ...]
    label: GovernanceAdvisoryOutputV1
    source_sample: GovernanceLearningSampleV1


@dataclass(frozen=True)
class GovernanceDatasetSplit:
    feature_names: Tuple[str, ...]
    train: Tuple[GovernanceDatasetRow, ...]
    eval: Tuple[GovernanceDatasetRow, ...]


def encode_governance_features(sample: GovernanceLearningSampleV1) -> Tuple[float, ...]:
    features = sample.features
    evidence = sample.evidence_summary
    signer_profile = (evidence.signer_profile or "none").strip().lower()
    return (
        float(features.telemetry_age_seconds),
        _bool(features.has_valid_coordinates),
        _bool(features.has_valid_signature),
        _bool(features.has_matching_assets),
        _bool(features.device_enrolled),
        _bool(features.is_approved_zone),
        _bool(features.approval_envelope_present),
        float(features.declared_value_usd),
        _bool(features.requires_co_signature),
        float(features.trust_gap_count),
        float(features.distance_to_boundary),
        _bool(evidence.has_transition_receipts),
        _bool(evidence.has_policy_receipt),
        _bool(evidence.has_asset_fingerprint),
        0.0 if signer_profile in {"", "none"} else 1.0,
        float(evidence.telemetry_count),
        float(evidence.media_count),
    )


def build_governance_dataset_rows(
    samples: Iterable[GovernanceLearningSampleV1],
    *,
    labeler: Optional[GovernanceAdvisoryLabeler] = None,
) -> Tuple[GovernanceDatasetRow, ...]:
    resolved_labeler = labeler or GovernanceAdvisoryLabeler()
    rows: List[GovernanceDatasetRow] = []
    for sample in samples:
        rows.append(
            GovernanceDatasetRow(
                sample_id=sample.sample_id,
                request_id=sample.request_id,
                features=encode_governance_features(sample),
                label=resolved_labeler.label(sample),
                source_sample=sample,
            )
        )
    return tuple(rows)


def load_governance_advisory_dataset(
    *,
    samples: Optional[Sequence[GovernanceLearningSampleV1]] = None,
    eval_fraction: float = 0.2,
    labeler: Optional[GovernanceAdvisoryLabeler] = None,
) -> GovernanceDatasetSplit:
    if not 0.0 < eval_fraction < 1.0:
        raise ValueError("eval_fraction must be between 0 and 1")
    source_samples = tuple(samples) if samples is not None else tuple(load_governance_dataset())
    rows = build_governance_dataset_rows(source_samples, labeler=labeler)
    eval_rows: List[GovernanceDatasetRow] = []
    train_rows: List[GovernanceDatasetRow] = []
    threshold = int(eval_fraction * 10_000)
    for row in rows:
        bucket = _stable_bucket(row.sample_id)
        if bucket < threshold:
            eval_rows.append(row)
        else:
            train_rows.append(row)
    return GovernanceDatasetSplit(
        feature_names=FEATURE_NAMES,
        train=tuple(train_rows),
        eval=tuple(eval_rows),
    )


def _stable_bucket(sample_id: str) -> int:
    digest = hashlib.sha256(sample_id.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 10_000


def _bool(value: bool) -> float:
    return 1.0 if bool(value) else 0.0
