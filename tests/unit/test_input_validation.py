import json
from pathlib import Path

import pytest

from src.input.loader import (
    MAX_BATCH_TEXT_CHARS,
    MAX_BODY_BYTES,
    BatchValidationError,
    PayloadTooLarge,
    load_reply_batch,
    reply_input_hash,
)


ROOT = Path(__file__).resolve().parents[2]


def _reply(record_id: str = "h1", **changes: object) -> dict[str, object]:
    return {
        "id": record_id,
        "user_question": "q",
        "system_reply": "a",
        "knowledge_base": "k",
        **changes,
    }


@pytest.mark.parametrize(
    ("payload", "error_path"),
    [
        (b"{}", "$"),
        (b"[]", "$"),
        (json.dumps([_reply("../x")]).encode(), "$[0].id"),
        (json.dumps([_reply(user_question=" ")]).encode(), "$[0].user_question"),
    ],
)
def test_invalid_reply_batches_report_paths(payload: bytes, error_path: str) -> None:
    with pytest.raises(BatchValidationError) as caught:
        load_reply_batch(payload)

    assert error_path in caught.value.paths


def test_normalizes_only_id_preserves_order_and_text() -> None:
    records = load_reply_batch(
        json.dumps(
            [
                _reply(" h2 ", user_question=" q ", system_reply=" a ", knowledge_base=""),
                _reply("h1"),
            ]
        ).encode()
    )

    assert [record.id for record in records] == ["h2", "h1"]
    assert records[0].user_question == " q "


def test_hash_changes_with_order_but_not_json_key_order() -> None:
    first_encoding = json.dumps([_reply("h1"), _reply("h2")]).encode()
    reordered_keys = json.dumps(
        [
            {"knowledge_base": "k", "system_reply": "a", "user_question": "q", "id": "h1"},
            {"knowledge_base": "k", "system_reply": "a", "user_question": "q", "id": "h2"},
        ]
    ).encode()

    first = load_reply_batch(first_encoding)
    assert reply_input_hash(first) == reply_input_hash(load_reply_batch(reordered_keys))
    assert reply_input_hash(first) != reply_input_hash(list(reversed(first)))


def test_reply_byte_and_record_count_boundaries() -> None:
    raw = json.dumps([_reply()]).encode()
    assert len(raw) < MAX_BODY_BYTES
    assert len(load_reply_batch(raw + b" " * (MAX_BODY_BYTES - len(raw)))) == 1
    with pytest.raises(PayloadTooLarge):
        load_reply_batch(raw + b" " * (MAX_BODY_BYTES - len(raw) + 1))

    assert len(load_reply_batch(json.dumps([_reply()]).encode())) == 1
    assert len(load_reply_batch(json.dumps([_reply(f"h{i}") for i in range(20)]).encode())) == 20
    with pytest.raises(BatchValidationError) as caught:
        load_reply_batch(json.dumps([_reply(f"h{i}") for i in range(21)]).encode())
    assert "$" in caught.value.paths


def test_reply_total_text_duplicate_c0_and_extra_field_gates() -> None:
    at_limit = [_reply(f"h{i}", user_question="q" * 9_999, knowledge_base="") for i in range(20)]
    assert (
        sum(
            len(record.user_question) + len(record.system_reply) + len(record.knowledge_base)
            for record in load_reply_batch(json.dumps(at_limit).encode())
        )
        == MAX_BATCH_TEXT_CHARS
    )

    over_limit = [*at_limit]
    over_limit[0] = _reply("h0", user_question="q" * 10_000, knowledge_base="")
    with pytest.raises(BatchValidationError) as caught:
        load_reply_batch(json.dumps(over_limit).encode())
    assert "$" in caught.value.paths

    for payload, error_path in (
        ([_reply("h1"), _reply("h1")], "$[1].id"),
        ([_reply(system_reply="bad\x01text")], "$[0].system_reply"),
        ([_reply(extra="forbidden")], "$[0].extra"),
    ):
        with pytest.raises(BatchValidationError) as caught:
            load_reply_batch(json.dumps(payload).encode())
        assert error_path in caught.value.paths


def test_reply_benchmark_loads_read_only() -> None:
    path = ROOT / "task4_replies.json"
    before = path.read_bytes()

    records = load_reply_batch(before)

    assert len(records) == 20
    assert path.read_bytes() == before
