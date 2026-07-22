import json
from pathlib import Path

import pytest

from src.input.loader import (
    BatchValidationError,
    InvalidJson,
    PayloadTooLarge,
    load_ground_truth_batch,
)


ROOT = Path(__file__).resolve().parents[2]


def _ground_truth(record_id: str = "h1", **changes: object) -> dict[str, object]:
    return {
        "id": record_id,
        "is_hallucination": False,
        "hallucination_type": None,
        "detail": "normal",
        "severity": None,
        **changes,
    }


@pytest.mark.parametrize(
    ("payload", "error_path"),
    [
        (b"not json", "$"),
        (b"{}", "$"),
        (json.dumps([_ground_truth("bad/id")]).encode(), "$[0].id"),
        (json.dumps([_ground_truth(extra="forbidden")]).encode(), "$[0].extra"),
        (json.dumps([_ground_truth(detail="bad\x01detail")]).encode(), "$[0].detail"),
    ],
)
def test_invalid_ground_truth_batches_report_paths(payload: bytes, error_path: str) -> None:
    error_type = InvalidJson if payload == b"not json" else BatchValidationError
    with pytest.raises(error_type) as caught:
        load_ground_truth_batch(payload)

    if isinstance(caught.value, BatchValidationError):
        assert error_path in caught.value.paths


def test_ground_truth_label_rules_and_detail_boundary() -> None:
    assert load_ground_truth_batch(json.dumps([_ground_truth()]).encode())[0].severity is None

    invalid_records = (
        _ground_truth(hallucination_type="知识冲突"),
        _ground_truth(severity="高"),
        _ground_truth(is_hallucination=True, hallucination_type=None, detail="detail"),
        _ground_truth(is_hallucination=True, hallucination_type="知识冲突", detail=" "),
    )
    for record in invalid_records:
        with pytest.raises(BatchValidationError) as caught:
            load_ground_truth_batch(json.dumps([record]).encode())
        assert any(path.startswith("$[0]") for path in caught.value.paths)

    positive = _ground_truth(
        is_hallucination=True, hallucination_type="知识冲突", detail="d" * 10_000
    )
    assert load_ground_truth_batch(json.dumps([positive]).encode())[0].detail == "d" * 10_000
    with pytest.raises(BatchValidationError) as caught:
        load_ground_truth_batch(json.dumps([{**positive, "detail": "d" * 10_001}]).encode())
    assert "$[0].detail" in caught.value.paths


def test_ground_truth_duplicate_and_batch_size_limits() -> None:
    with pytest.raises(BatchValidationError) as caught:
        load_ground_truth_batch(json.dumps([]).encode())
    assert "$" in caught.value.paths

    assert len(load_ground_truth_batch(json.dumps([_ground_truth()]).encode())) == 1
    assert (
        len(
            load_ground_truth_batch(
                json.dumps([_ground_truth(f"h{i}") for i in range(20)]).encode()
            )
        )
        == 20
    )
    with pytest.raises(BatchValidationError) as caught:
        load_ground_truth_batch(json.dumps([_ground_truth(f"h{i}") for i in range(21)]).encode())
    assert "$" in caught.value.paths

    with pytest.raises(BatchValidationError) as caught:
        load_ground_truth_batch(json.dumps([_ground_truth("h1"), _ground_truth("h1")]).encode())
    assert "$[1].id" in caught.value.paths


def test_ground_truth_payload_size_limit() -> None:
    with pytest.raises(PayloadTooLarge):
        load_ground_truth_batch(b" " * (5 * 1024 * 1024 + 1))


def test_ground_truth_benchmark_loads_read_only() -> None:
    path = ROOT / "task4_ground_truth.json"
    before = path.read_bytes()

    records = load_ground_truth_batch(before)

    assert len(records) == 20
    assert path.read_bytes() == before
