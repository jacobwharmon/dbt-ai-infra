# Agent guide

This is an analytics-engineering dbt repo. The human decides what the data must mean; the agent turns those decisions into dbt code, tests, and proof queries. Work only inside this repo unless told otherwise.

## Where truth lives

Read in this order, and never restate in prose what a higher source already says:

1. **Code and the dbt manifest** — what exists. `.agents/project_map.md` is a generated summary; running the check refreshes it.
2. **Model and source contracts** (`meta.contract` in YAML) — what must be true. See the `contract` skill.
3. **`DECISIONS.md`** — why: business decisions and platform facts the code cannot show.

Project settings (dbt command, project dir, targets, layer folders) are in `.agents/check.toml`.

## Work loop

1. Run the check: `uv run --no-project python scripts/agent_check.py` (any Python 3.11+ works).
2. Before changing a model or source, read its contract (`contract` skill). Draft any unanswered question from the code as `TODO: <proposal>` and ask the human. Only the human removes a `TODO:`.
3. Make the smallest change that meets the contract. Follow the repo's existing layer boundaries, and do not change a shared model's behavior to suit one consumer. If you were given a working query, it is the specification: preserve its results and do not "fix" unusual but valid logic.
4. Encode each answer as a test or config, and write proof queries to `analyses/` (the `contract` skill has the mapping and the proof format).
5. Rerun the check until AGENT-FIXABLE is empty.
6. Report: changed files, open contract questions, and the proof files. The human builds the changed models in dev, then runs the proofs.

## Execution boundary

- Never execute anything that runs models or tests or reads data. `scripts/agent_guard.py` enforces this as a hook and is the authoritative list.
- `dbt compile` runs on-run-start hooks and introspective queries. Never add `run_query` or `statement` to look at data.
- Compiling proves the SQL renders, not that the data is right. Never report data results you did not see; the human runs the proofs and pastes the results back.
