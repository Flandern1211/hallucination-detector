### Task 3: Reply and Ground-Truth Input Validation

**Files:**
- Create: `src/input/loader.py`
- Create: `src/input/validator.py`
- Create: `tests/unit/test_input_validation.py`
- Create: `tests/unit/test_ground_truth_validation.py`

**Interfaces:**
- Produces: `load_reply_batch(raw: bytes) -> list[ReplyRecord]`; `load_ground_truth_batch(raw: bytes) -> list[GroundTruthRecord]`; `reply_input_hash(records) -> str`; exceptions `PayloadTooLarge`, `InvalidJson`, `BatchValidationError` carrying field paths.
- Consumes: strict models and canonical hashing from Task 2.

- [ ] **Step 1: Write parameterized boundary tests**

```python
@pytest.mark.parametrize("payload,error_path", [
    (b"{}", "$"), (b"[]", "$"),
    (json.dumps([{"id": "../x", "user_question": "q", "system_reply": "a",
                  "knowledge_base": "k"}]).encode(), "$[0].id"),
    (json.dumps([{"id": "h1", "user_question": " ", "system_reply": "a",
                  "knowledge_base": "k"}]).encode(), "$[0].user_question"),
])
def test_invalid_reply_batches_report_paths(payload: bytes, error_path: str) -> None:
    with pytest.raises(BatchValidationError) as caught:
        load_reply_batch(payload)
    assert error_path in caught.value.paths


def test_normalizes_only_id_preserves_order_and_text() -> None:
    records = load_reply_batch(json.dumps([
        {"id": " h2 ", "user_question": " q ", "system_reply": " a ", "knowledge_base": ""},
        {"id": "h1", "user_question": "q", "system_reply": "a", "knowledge_base": "k"},
    ]).encode())
    assert [record.id for record in records] == ["h2", "h1"]
    assert records[0].user_question == " q "


def test_hash_changes_with_order_but_not_json_key_order() -> None:
    first = load_reply_batch(FIRST_ENCODING)
    assert reply_input_hash(first) == reply_input_hash(load_reply_batch(REORDERED_KEYS))
    assert reply_input_hash(first) != reply_input_hash(list(reversed(first)))
```

- [ ] **Step 2: Confirm RED**

Run: `python -m pytest tests/unit/test_input_validation.py tests/unit/test_ground_truth_validation.py -q`

Expected: FAIL because loaders do not exist.

- [ ] **Step 3: Implement byte, JSON, model, batch, duplicate-ID, and total-character gates**

```python
MAX_BODY_BYTES = 5 * 1024 * 1024
MAX_RECORDS = 20
MAX_BATCH_TEXT_CHARS = 200_000


def load_reply_batch(raw: bytes) -> list[ReplyRecord]:
    if len(raw) > MAX_BODY_BYTES:
        raise PayloadTooLarge(MAX_BODY_BYTES)
    value = decode_json_array(raw)
    records = validate_items(value, ReplyRecord)
    enforce_batch_size(records, 1, MAX_RECORDS)
    enforce_unique_ids(records)
    total = sum(len(r.user_question) + len(r.system_reply) + len(r.knowledge_base) for r in records)
    if total > MAX_BATCH_TEXT_CHARS:
        raise BatchValidationError(["$"] , "batch text exceeds 200000 characters")
    return records
```

Ground truth uses the same 5 MiB, 1–20, safe-ID, unique-ID, C0, and `extra="forbid"` rules; normal labels require null type/severity, positive labels require non-empty type/detail, and detail is capped at 10,000 characters.

- [ ] **Step 4: Run focused tests and benchmarks read-only**

Run: `python -m pytest tests/unit/test_input_validation.py tests/unit/test_ground_truth_validation.py -q`

Expected: PASS; both existing benchmark arrays load as 20 records and their bytes remain unchanged.

- [ ] **Step 5: Request approval and commit**

```powershell
git add src/input tests/unit/test_input_validation.py tests/unit/test_ground_truth_validation.py
git commit -m "feat: validate reply and ground truth batches"
```

