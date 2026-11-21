# Kaya Kopi Holdings Pte Ltd — AI Engineering Capstone (team1_kaya_kopi)

Your team is the forward-deployed engineering unit for **Kaya Kopi Holdings Pte Ltd**. Your job: build the
F&B ops copilot described in [CLIENT_BRIEF.md](CLIENT_BRIEF.md) and survive a live demo with the
customer on **Fri 27 Nov 2026**.

## Quick start

Prerequisite: Docker Desktop, or Docker Engine with Docker Compose v2.

```bash
git clone <repository-url>
cd team1_kaya_kopi_prototype
cp .env.example .env
# Configure the passwords, ports and OPENAI_API_KEY in .env.
# Copy the client package contents into data/; see data/README.md.
./scripts/bootstrap.sh
./scripts/reload_data.sh
./scripts/test.sh
./scripts/start.sh
```

Open <http://localhost:8501> (or the configured `KAYA_STREAMLIT_HOST_PORT`). Docker images provide
the isolated Python environments; no host virtual environment or manual `pip install` is required.

The commands have deliberately separate responsibilities:

- `bootstrap.sh` validates the environment and builds the images;
- `reload_data.sh` explicitly purges and rebuilds the database from the private inputs;
- `test.sh` runs the parser tests and read-only database health/functional checks; and
- `start.sh` starts MySQL and Streamlit without rerunning ingestion or tests.

The first run is slower because Docker builds the application images and PaddleOCR downloads its
English model. Parsed files remain under the git-ignored `runtime/` directory, the MySQL data
uses a Docker volume, and chat checkpoints use a separate Docker volume.

Useful commands:

```bash
docker compose logs -f copilot  # application logs
docker compose down             # stop services; preserve database volumes
./scripts/reload_data.sh         # explicitly purge and rebuild business data
```

The deterministic test command does not call the LLM. To manually review the non-deterministic
answers against the project acceptance questions after loading the database, run:

```bash
docker compose --profile test run --rm test python scripts/run_llm_acceptance.py
```

This uses the configured OpenAI key and prints each answer beside its expected evidence checklist;
it is intentionally not part of the automated test suite.

Agent context and execution limits are configured in `.env`; see `.env.example` for the available
`KAYA_LLM_*` and `KAYA_AGENT_MAX_STEPS` settings. Defaults are applied when these optional values are
absent, and invalid limits fail at application startup. Conversation checkpoints retain full history,
while only the most recent complete turns that fit the configured input budget are sent to OpenAI.
Model-visible tool results are also capped by `KAYA_TOOL_MAX_RESULT_BYTES`. Complete financial
aggregates are calculated from all eligible rows before that cap is applied; an oversized result fails
closed instead of being truncated. Paginated detail is labelled incomplete and must not be summed by
the model.

The context-handling live acceptance test is also opt-in because it consumes API credit:

```bash
docker compose --profile test run --rm \
  -e KAYA_RUN_LIVE_LLM_TESTS=1 \
  test python -m unittest tests.live.test_context_handling -v
```

It makes one short request to the configured OpenAI model and verifies returned token-usage metadata
and the output-token limit. Normal `unittest discover` runs skip this test and make no paid LLM calls.

See [ingestion/README.md](ingestion/README.md) for individual parser, schema and loader commands.

## Rules of engagement

1. **No client data in git.** `data/` is git-ignored; keep it that way. Same for `.env` and your API key.
2. **Every member contributes.** Team-process marks are graded per person from commit history — every member commits real work under their own GitHub account (set `git config user.email` to the e-mail on your GitHub profile, or your commits are credited to nobody). Pair-programming is fine; say so in commit messages (`Co-authored-by:`).
3. **Budget.** Your API key has a hard budget. Watch your spend; a burned key is not replaced.
4. **Cite everything.** Answers your app gives must say where the fact came from. See [HARNESS_CHECKLIST.md](HARNESS_CHECKLIST.md) — it is the grading rubric in checklist form.
5. **Ask the client, by email.** The client is reachable only by email to the course director (subject `Client question — Team N`), replies within two working days and does not take calls. If the brief mentions something that is not in the package, ask — do not guess and do not quietly work around it. Keep every answer in [`CLIENT_QA.md`](CLIENT_QA.md).

## Deliverables

- Working application (live demo; a judging panel plays your customer and asks unscripted questions)
- Architecture documentation with **at least two Mermaid diagrams** at the repository root
- Data quality report: every trap you found and how you handled it
- 5-minute pitch
- Honest post-mortem (what you'd do differently)




