# UDb — Testing Strategy

## Overview

UDb uses a single test tier: **unit tests**. All I/O boundaries are doubled — storage backends via in-memory test doubles, LLM calls via recorded responses. Unit tests run on every push in CI.

> **Status in 1.0:** the sections below are the original plan. What 1.0 has is summarized in §0; where a section no longer applies, it says so.

---

## 0. As Built in 1.0

**Two tiers.**

- **Unit tests**, offline and fast, with no API key: `lib/tests/unit/` (`backends/`, `data/`, `interaction/`, `reasoning/`, `sources/`, plus top-level modules) and one suite per platform package — `platform/cli/tests/unit/` (Click's `CliRunner`), `platform/api/tests/` (FastAPI's `TestClient`) and `platform/mcp/tests/` (tool functions called directly).
- **Benchmarks**, `lib/tests/benchmarks/` (`extraction/`, `querying/`, `reasoning/`): report-only runs against the live LLM, scored per case and recorded per module in a committed history (`<module>/results/history.jsonl`, rendered with trend charts to `<module>/results/README.md`) and compared with the run flagged in it as the baseline (the 2026-10-10 gpt-4o run); a case more than 0.15 below its baseline raises a `BenchmarkRegression` warning, not a failure. Reports and VCR cassettes are written at run time and git-ignored; cassettes are scrubbed of credentials. Measuring clarification precision and recall, and making replay work, is #150.

**Doubles.** LLM calls are mocked, not recorded: tests patch `reasoning.reasoner._llm_complete` (or the method under test) with `AsyncMock`. Stores are the real in-memory backends (`MemoryJSONSource`, `MemoryKBSource`), or, where a test needs fixed KB answers, a mock from `tests/unit/doubles/sources.py` (`make_mock_kb`). An autouse fixture in `lib/tests/unit/conftest.py` blocks every non-loopback network connection, so a test that reaches a real service fails instead of silently calling it.

**No CI yet** — suites run locally (see [12-deployment-ops.md](12-deployment-ops.md) §7).

---

## 1. Tooling

| Tool | Purpose |
|------|---------|
| `pytest` | Test runner |
| `pytest-asyncio` | Async test support (`asyncio_mode = "auto"`) |
| `pytest-recording` | Record and replay LLM HTTP interactions (VCR-based) |
| `pytest-cov` | Coverage measurement (reported, not enforced) |

All tools are declared as `dev` dependencies in `pyproject.toml`.

---

## 2. Test Layout

Tests mirror the source layout under a top-level `tests/` directory.

```
tests/
  unit/
    reasoning/
      test_query_rewriter.py
      test_data_assessor.py
    data/
      test_query_planner.py
      test_query_executor.py
      test_source_manager.py
    interaction/
      test_contact_manager.py
      test_interaction_manager.py
    interfaces/
      test_rest_api.py
      test_mcp_server.py
      test_cli.py
  cassettes/          # Recorded LLM HTTP responses (VCR cassettes)
    query_rewriter/
    data_assessor/
```

---

## 3. Storage Test Doubles

> **1.0:** no `VectorSource` and no `tests/doubles/` of JSON stores; see §0.

`JSONSource` and `VectorSource` are tested against in-memory implementations of their abstract interfaces. These doubles are defined in `tests/doubles/` and injected via pytest fixtures.

The in-memory doubles must implement the same interface as the real backends (`set`, `get`, `delete`, `query`, `keys`). They do not simulate vectorization — the `VectorSource` double stores raw values alongside zero-vector placeholders, which is sufficient for testing write paths and interface contracts.

**Example fixture:**

```python
@pytest.fixture
def json_store() -> InMemoryJsonSource:
    return InMemoryJsonSource()

@pytest.fixture
def vector_store() -> InMemoryVectorSource:
    return InMemoryVectorSource()
```

---

## 4. LLM Test Doubles

> **1.0:** unit tests mock LLM calls instead of replaying cassettes; cassettes exist only for benchmarks and are not committed. See §0.

LLM calls are tested using recorded HTTP responses via `pytest-recording` (VCR.py). On first run with `--record-mode=once`, real LLM responses are captured and saved as cassettes under `tests/cassettes/`. Subsequent runs replay the cassettes without hitting the network.

**Recording rules:**

- Cassettes are committed to the repository.
- When a prompt changes in a way that would alter the response, the cassette must be re-recorded. Delete the cassette file and run with `--record-mode=once`.
- Tests fail if a cassette is missing and `--record-mode` is not set (default CI behavior).

**Example:**

```python
@pytest.mark.vcr
async def test_query_rewriter_expands_query(query_rewriter):
    result = await query_rewriter.rewrite("jobs suitable for me")
    assert "skills" in [q.lower() for q in result.questions]
```

---

## 5. Dual-Write Verification

> **1.0:** not applicable — there is no dual-write (see [10-data-model.md](10-data-model.md) §0).

Tests for data write operations assert that both the JSON store and the Vector store receive the write. Each test that exercises a write path should assert state in both doubles after the operation.

**Example:**

```python
async def test_data_entry_written_to_both_stores(dml, json_store, vector_store):
    await dml.write_entry(user_id="u1", key="skills", value=["Python"])
    assert json_store.get("u1", "skills") is not None
    assert vector_store.get("u1", "skills") is not None
```

---

## 6. Fixtures and Test Data

Common fixtures are defined in `tests/conftest.py`. A standard user fixture provides a pre-populated user database for tests that need existing data.

The CLI suite's `platform/cli/tests/unit/conftest.py` additionally isolates the CLI home: `--data-dir` alone is not enough, because profiles are read from the home directory *before* any option is applied, so without it the suite writes into the developer's own `~/.blue-userdb`. It points every home/data variable at `tmp_path`, clears every configuration parameter (so a developer's exported `OPENAI_API_KEY` cannot change what the tests observe), snapshots the environment around each invocation (a real run gets a fresh process; in-process, the profile's exports would leak into the next command), and asserts afterwards that nothing was written to the real `~/.blue-userdb`. That last guard is the durable part — the failure it catches is invisible until someone inspects their own home directory.

```python
@pytest.fixture
def user_id() -> str:
    return "test-user-001"

@pytest.fixture
async def populated_db(json_store, vector_store, user_id):
    await json_store.set(user_id, "metadata.profile", {"name": "Test User", ...})
    await json_store.set(user_id, "data", [
        {"key": "skills", "value": ["Python"], "metadata": {...}}
    ])
    # mirror to vector store
    ...
    return user_id
```

---

## 7. Interface Tests

Each external interface (REST, MCP, CLI) has its own test module. These are still unit tests — they use the same in-memory doubles and recorded LLM cassettes. They exercise the translation layer (request parsing, response serialization, error mapping) rather than end-to-end behavior.

- **REST API** — tested via FastAPI's `TestClient` (sync wrapper, compatible with `pytest-asyncio`)
- **MCP Server** — tested by calling tool handler functions directly with mock MCP context
- **CLI** — tested via Click's `CliRunner`

---

## 8. Coverage

Coverage is measured via `pytest-cov` (the library's default `addopts`) and reported in CI output once CI exists. No minimum threshold is enforced. The report is available as a CI artifact for review.

```toml
# pyproject.toml
[tool.pytest.ini_options]
addopts = "--cov=src --cov-report=term-missing"
asyncio_mode = "auto"
```

---

## 9. Running Tests

```bash
# Run all unit tests
pytest tests/unit/

# Run with coverage report
pytest tests/unit/ --cov=src --cov-report=term-missing

# Re-record LLM cassettes for a specific module
pytest tests/unit/reasoning/ --record-mode=once
```
