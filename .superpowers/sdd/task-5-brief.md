### Task 5: Provider HTTP Transport, Retry, Repair, and Budget Enforcement

**Files:**
- Modify: `src/providers/base.py`
- Modify: `src/providers/budget.py`
- Create: `src/providers/llm_provider.py`
- Create: `tests/contract/test_llm_provider.py`
- Create: `tests/unit/test_task_budget.py`

**Interfaces:**
- Produces: `ProviderConfig.from_environment(environment: Mapping[str, str]) -> ProviderConfig`; `LLMProvider`; full typed exceptions and thread-safe enforcement in the Task 4 `TaskBudget`.
- Consumes: Task 2 models, Task 4 protocols/budget, baseline prompts, and a replaceable `HttpTransport.send(request: HttpRequest, timeout_seconds: float, max_response_bytes: int) -> HttpResponse` so tests never open sockets.

- [ ] **Step 1: Write contract tests around a scripted local transport**

```python
def test_chat_completion_wire_contract_and_usage() -> None:
    transport = ScriptedTransport([ok_response("extract_claims", claims_payload(), model="m1")])
    provider = LLMProvider(provider_config(), transport=transport, sleeper=lambda seconds: None)
    result = provider.extract_claims(reply_record(), baseline_config(), detection_budget())
    sent = transport.requests[0]
    assert sent.url == "https://provider.example/v1/chat/completions"
    assert sent.headers["Authorization"] == "Bearer test-only-secret"
    assert sent.json["temperature"] == 0
    assert sent.json["stream"] is False
    assert sent.json["max_tokens"] == 2000
    assert sent.json["response_format"]["json_schema"]["name"] == "extract_claims"
    assert result.usage.total_tokens >= result.usage.prompt_tokens + result.usage.completion_tokens


def test_retryable_statuses_back_off_then_succeed() -> None:
    waits: list[float] = []
    transport = ScriptedTransport([http_error(429), http_error(503), ok_response(
        "extract_claims", claims_payload(), model="m1")])
    provider = LLMProvider(provider_config(), transport, waits.append)
    result = provider.extract_claims(reply_record(), baseline_config(), detection_budget())
    assert result.attempts == 3
    assert waits == [1.0, 2.0]


def test_invalid_json_gets_one_non_retrying_repair() -> None:
    transport = ScriptedTransport([ok_raw("{"), ok_response(
        "extract_claims", claims_payload(), model="m1")])
    result = LLMProvider(provider_config(), transport, lambda seconds: None).extract_claims(
        reply_record(), baseline_config(), detection_budget())
    assert result.repaired is True
    assert len(transport.requests) == 2
```

Also test HTTPS enforcement with only `localhost`, `127.0.0.1`, and `[::1]` HTTP exceptions; missing env variables; 408/429/500/502/503/504 retry; non-retryable 4xx; numeric `Retry-After` capped at 30; 60-second timeout; 2 MiB response cap; context rejection; missing/invalid usage; model drift; fixed operation names; `extra="forbid"`; sanitized errors; and `UNTRUSTED_DATA` boundaries.

- [ ] **Step 2: Write deterministic budget/deadline/cancellation tests**

```python
def test_request_budget_never_permits_attempt_201() -> None:
    budget = TaskBudget(200, 250_000, 1800, FakeClock(), Event())
    for _ in range(200):
        budget.before_request()
    with pytest.raises(RequestBudgetExhausted):
        budget.before_request()


def test_token_breaker_allows_only_last_response_to_cross_limit() -> None:
    budget = TaskBudget(200, 250_000, 1800, FakeClock(), Event())
    budget.record_usage(ProviderUsage(prompt_tokens=249_999, completion_tokens=2,
                                      total_tokens=250_001))
    with pytest.raises(TokenBudgetExhausted):
        budget.before_request()


def test_cancel_and_monotonic_deadline_stop_before_transport() -> None:
    clock, cancelled = FakeClock(), Event()
    budget = TaskBudget(8, 50_000, 300, clock, cancelled)
    cancelled.set()
    with pytest.raises(TaskCancelled):
        budget.before_request()
```

- [ ] **Step 3: Confirm RED**

Run: `python -m pytest tests/contract/test_llm_provider.py tests/unit/test_task_budget.py -q`

Expected: provider contract tests FAIL because `LLMProvider` and transport are missing; Task 4’s basic budget tests remain green.

- [ ] **Step 4: Implement the standard-library configuration and bounded transport, retaining Task 4’s locked budget**

```python
@dataclass(frozen=True)
class ProviderConfig:
    api_key: str
    base_url: str
    model: str

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> "ProviderConfig":
        names = ("HALLUCINATION_API_KEY", "HALLUCINATION_BASE_URL", "HALLUCINATION_MODEL")
        missing = [name for name in names if not environment.get(name, "").strip()]
        if missing:
            raise ProviderConfigurationError(missing)
        base_url = validate_base_url(environment["HALLUCINATION_BASE_URL"].rstrip("/"))
        return cls(environment["HALLUCINATION_API_KEY"], base_url,
                   environment["HALLUCINATION_MODEL"].strip())


class UrllibTransport:
    def send(self, request: HttpRequest, timeout_seconds: float,
             max_response_bytes: int) -> HttpResponse:
        wire = urllib.request.Request(request.url, data=canonical_bytes(request.json),
                                      headers=request.headers, method="POST")
        with urllib.request.urlopen(wire, timeout=timeout_seconds) as response:
            body = response.read(max_response_bytes + 1)
            if len(body) > max_response_bytes:
                raise ProviderResponseTooLarge(max_response_bytes)
            return HttpResponse(status=response.status, headers=dict(response.headers), body=body)
```

`LLMProvider._invoke()` must call `before_request()` immediately before each real transport attempt, parse no more than 2 MiB, require content/model/usage, bind the first successful model for the task, use one schema-repair request only for JSON/schema shape failures, and translate all failures to local typed exceptions without response bodies, secrets, or raw exception strings.

- [ ] **Step 5: Run contract tests and ensure no network was opened**

Run: `python -m pytest tests/contract/test_llm_provider.py tests/unit/test_task_budget.py -q`

Expected: PASS; scripted transport records at most 3 regular attempts plus 1 repair per logical call.

- [ ] **Step 6: Request approval and commit**

```powershell
git add src/providers tests/contract/test_llm_provider.py tests/unit/test_task_budget.py
git commit -m "feat: implement bounded OpenAI-compatible provider"
```

