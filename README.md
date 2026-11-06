# blue-data-user-source

A per-user personal data store that agents can query in plain language, with quality checks that ask the user when the data falls short.

Agents acting for a person need what that person knows about themselves: their background, preferences, availability and how to reach them, kept current and private. blue-data-user-source gives each user their own knowledge graph, extracted from their documents, and answers questions over it only after checking the answer is complete, fresh and privacy-safe — asking the user directly when it is not — through a Python library, the `blue-userdb` CLI, an MCP server or a REST API.

→ **[Full documentation](docs/README.md)** · **[Quick start](docs/quickstart.md)** · **[Installation](docs/installation.md)** · **[Examples](examples/README.md)** · **[CLI](docs/cli.md)** · **[MCP](docs/mcp.md)** · **[REST API](docs/api.md)**

## What it does

- **Import** documents into a user's store: every file is chunked and embedded for search by meaning (OpenAI embeddings by default; keyword or hybrid search can be chosen per user), and `--query` questions extract typed entities and facts into the user's knowledge graph, each tied to the source it came from.
- **Query** the store in plain language: queries are rewritten ("my" becomes the user's name), expanded into schema-grounded sub-questions, and answered as JSON, a table, or prose.
- **Assess** every answer for completeness, freshness and privacy before returning it, with the privacy bar set by the user's own consent level.
- **Interact** with the user when an answer falls short: the system picks the best contact channel (the terminal, email, or a webhook), asks, and folds the reply back into the store.
- **Personalize** with per-user metadata (identity, preferences, availability, privacy) and contact methods that agents read when acting on the user's behalf.
- **Record** every query and clarification in sessions, so later questions have context and every answer has an audit trail.

See [docs/features.md](docs/features.md) for the full list with examples, and [examples/](examples/README.md) for runnable scripts.

## Repository layout

```
blue-data-user-source/
├── lib/                        # Python library (blue-data-user-source)
│   ├── src/blue_data_user_source/
│   ├── scripts/                # install.sh, build.sh, publish.sh
│   └── tests/
│       ├── unit/               # fast offline tests, no API key
│       └── benchmarks/         # report-only LLM benchmarks, compared to a committed baseline
├── platform/
│   ├── cli/                    # Command-line interface (blue-userdb)
│   ├── mcp/                    # MCP server (blue-userdb-mcp)
│   └── api/                    # REST API (blue-userdb-api)
├── scripts/                    # install.sh — installs every package, editable
├── data/                       # resume.txt, the sample document used in the docs
├── tools/                      # convert_schema.py — regenerates schema.json from schema.txt
├── docs/                       # User-facing documentation (start at docs/README.md)
├── examples/                   # Runnable examples (start at examples/README.md)
└── design/                     # Architecture and design-process documents
```

Each platform package has its own `src/`, `tests/` and `scripts/install.sh`.

## Requirements

- Python 3.12 or 3.13
- The sibling repositories [`blue-data`](https://github.com/megagonlabs/blue-data), [`blue-data-kb-source`](https://github.com/megagonlabs/blue-data-kb-source) and [`blue-data-doc-source`](https://github.com/megagonlabs/blue-data-doc-source), cloned beside this one (`../blue-data`, `../blue-data-kb-source`, `../blue-data-doc-source`); they provide the storage, knowledge-graph and document layers, and are not on PyPI
- An API key for the LLM features (extraction, query rewriting and expansion, quality assessment, and answers in prose): OpenAI by default, or Anthropic with `BLUE_DATA_LLM_PROVIDER=anthropic`

```bash
export OPENAI_API_KEY=sk-...
# or, for Claude: export BLUE_DATA_LLM_PROVIDER=anthropic ANTHROPIC_API_KEY=sk-ant-...
#   (document embeddings still use OPENAI_API_KEY; see docs/installation.md)
```

Every query and extraction makes many OpenAI calls: at the default model, gpt-4o, one query costs roughly $0.20–$2 and extracting a short document $0.20–$0.50. `data query --max-subqueries 1 --max-kb-turns 8` cut one query from 67 calls to 16 ($0.38 to $0.06). See [Cost](docs/guide.md#cost) for the bounds and the cheaper model settings.

## Quick start

```bash
# Install the sibling repos (from ../), the library with its extras, the CLI, the MCP server and the REST API
bash scripts/install.sh

# Create a database for Alice (add --no-onboard to skip the short onboarding interview)
blue-userdb database create alice --no-onboard
blue-userdb metadata set identity name "Alice Chen"

# Add her resume, extracting a few attributes into her knowledge graph
blue-userdb data source add data/resume.txt \
    --query "What skills does the user have?" \
    --query "What is the user's most recent job title?"

# Ask in plain language: as a table, or as a prose answer
blue-userdb data query "What skills do I have?"
blue-userdb data query "What jobs would suit me?" --format nl
```

Databases live under `~/.blue-userdb/` by default. When a check fails, `data query` asks for clarification right in the terminal (only when stdin is one: under a pipe or a script it uses another contact method, or answers without asking). The full walkthrough — sessions, contact methods, the Python-library equivalent, and connecting an agent over MCP — is in **[docs/quickstart.md](docs/quickstart.md)**.

## Packages

| Package | Description |
|---|---|
| [lib/](lib/README.md) | `blue-data-user-source`: the core Python library (`UserSource` with memory, file and Redis backends) |
| [platform/cli/](platform/cli/README.md) | `blue-data-user-cli`: the command-line tool, installs `blue-userdb` |
| [platform/mcp/](platform/mcp/README.md) | `blue-data-user-mcp`: MCP server for LLM agents, installs `blue-userdb-mcp` |
| [platform/api/](platform/api/README.md) | `blue-data-user-api`: REST API (FastAPI), installs `blue-userdb-api` |

---

## Code of Conduct

This project adheres to the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md).
By participating, you are expected to uphold this code. Report unacceptable behavior
to contact_oss@megagon.ai.

---

## Disclosures

This software may include, incorporate, or access open source software (OSS) components,
datasets and other third party components, including those identified below. The license terms
respectively governing the datasets and third-party components continue to govern those
portions, and you agree to those license terms may limit any distribution, use, and copying.
You may use any OSS components under the terms of their respective licenses, which may
include BSD 3, Apache 2.0, and other licenses. In the event of conflicts between Megagon Labs,
Inc. (“Megagon”) license conditions and the OSS license conditions, the applicable OSS
conditions governing the corresponding OSS components shall prevail.
You agree not to, and are not permitted to, distribute actual datasets used with the OSS
components listed below. You agree and are limited to distribute only links to datasets from
known sources by listing them in the datasets overview table below. You agree that any right to
modify datasets originating from parties other than Megagon are governed by the respective
third party’s license conditions.
You agree that Megagon grants no license as to any of its intellectual property and patent rights.
THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS (INCLUDING
MEGAGON) “AS IS” AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED
TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED
AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE. You agree to cease using,
incorporating, and distributing any part of the provided materials if you do not agree with the
terms or the lack of any warranty herein.
While Megagon makes commercially reasonable efforts to ensure that citations in this
document are complete and accurate, errors may occur. If you see any error or omission, please
help us improve this document by sending information to contact_oss@megagon.ai.

### Datasets

All datasets used within the product are listed below (including their copyright holders and the license information).

For Datasets having different portions released under different licenses, please refer to the included source link specified for each of the respective datasets for identifications of dataset files released under the identified licenses.

None. This repository uses, distributes and downloads no third-party datasets. Its sample data was written for this project: the fictional resume `data/resume.txt`, the KB, metadata and contact schemas under `lib/src/blue_data_user_source/data/`, the benchmark cases under `lib/tests/benchmarks/`, and the inputs of `examples/`.

### Open Source Software (OSS) Components

All OSS components used within the product are listed below (including their copyright holders and the license information).

For OSS components having different portions released under different licenses, please refer to the included Upstream link(s) specified for each of the respective OSS components for identifications of code files released under the identified licenses.

</br>

| ID  | OSS Component Name | Modified | Copyright Holder | Upstream Link | License  |
|-----|----------------------------------|----------|------------------|-----------------------------------------------------------------------------------------------------------|--------------------|
| 1 | aiosmtplib | No | Cole Maclean | [link](https://github.com/cole/aiosmtplib) | MIT License |
| 2 | arrow | No | Chris Smith | [link](https://github.com/arrow-py/arrow) | Apache Software License |
| 3 | click | No | Pallets | [link](https://github.com/pallets/click) | BSD License |
| 4 | fastapi | No | Sebastián Ramírez | [link](https://github.com/fastapi/fastapi) | MIT License |
| 5 | httpx | No | Encode OSS Ltd. | [link](https://github.com/encode/httpx) | BSD License |
| 6 | langchain-mcp-adapters | No | LangChain, Inc. | [link](https://github.com/langchain-ai/langchain-mcp-adapters) | MIT License |
| 7 | langchain-openai | No | LangChain, Inc. | [link](https://github.com/langchain-ai/langchain) | MIT License |
| 8 | langgraph | No | LangChain, Inc. | [link](https://github.com/langchain-ai/langgraph) | MIT License |
| 9 | litellm | No | Berri AI | [link](https://github.com/BerriAI/litellm) | MIT License |
| 10 | MCP | No | Anthropic, PBC | [link](https://github.com/modelcontextprotocol/python-sdk) | MIT License |
| 11 | openai | No | OpenAI | [link](https://github.com/openai/openai-python) | Apache Software License |
| 12 | pydantic | No | Pydantic Services Inc. and individual contributors | [link](https://github.com/pydantic/pydantic) | MIT License |
| 13 | pydantic-settings | No | Samuel Colvin and other contributors | [link](https://github.com/pydantic/pydantic-settings) | MIT License |
| 14 | rank-bm25 | No | Dorian Brown | [link](https://github.com/dorianbrown/rank_bm25) | Apache Software License |
| 15 | redis | No | Redis, inc. | [link](https://github.com/redis/redis-py) | MIT License |
| 16 | rich | No | Will McGugan | [link](https://github.com/Textualize/rich) | MIT License |
| 17 | uvicorn | No | Encode OSS Ltd. | [link](https://github.com/encode/uvicorn) | BSD License |
