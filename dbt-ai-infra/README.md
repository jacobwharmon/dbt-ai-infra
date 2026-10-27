# Agent infrastructure for a dbt repo

A small, company-agnostic setup for running Claude Code and Codex on an analytics-engineering dbt project. The human answers the contract questions (schema, freshness, keys, duplicates, grain, required fields, relationships, domains, row loss and fanout, reconciliation, idempotence). Agents encode the answers as dbt tests and config, write proof queries, and check their own work. They cannot execute anything against the warehouse.

## What's here

| Path | Purpose |
| --- | --- |
| `AGENTS.md` | The one instruction file: where truth lives, the work loop, the execution boundary. `CLAUDE.md` imports it. |
| `DECISIONS.md` | Business decisions and platform facts the code cannot show. Replaces a hand-written memory file. |
| `.agents/check.toml` | Project settings: dbt command, project dir, targets, layer folders. |
| `.agents/skills/contract/` | The one skill: each contract question, where its answer lives in YAML, how it is enforced, and the proof-query format. |
| `scripts/agent_check.py` | Parses each target, checks contracts and layer rules against the manifest, and writes `.agents/project_map.md`. Fails only on agent-fixable problems. Open human questions are listed, not failed. |
| `scripts/agent_guard.py` | Hook that blocks warehouse-executing dbt commands, including ones sent through shell-running MCP tools, and dbt MCP execution tools. |
| `.claude/settings.json`, `.codex/hooks.json` | Wire the guard into Claude Code (fails closed if the guard can't start) and Codex. |
| `.mcp.json`, `.codex/config.toml` | dbt MCP server, pinned, with its execution tools disabled. |
| `dbt/` | Merge into the dbt project: the `reconciles_to` generic test and the `dbt_utils` dependency. |

## Install

1. Copy everything except `README.md` and `dbt/` into the repo root. Merge with any existing `AGENTS.md`, `.claude/` and `.codex/` instead of overwriting them.
2. In the dbt project, merge `dbt/packages.yml` into `packages.yml`, copy `dbt/macros/reconciles_to.sql` into `macros/`, and run `dbt deps`.
3. Expose the skill to Claude Code; Codex reads `.agents/skills` directly. Either copy `.agents/skills/contract` into `.claude/skills/`, or symlink the folder. Symlinks on Windows need Developer Mode and `git config core.symlinks true`; otherwise use the copy.
4. Edit `.agents/check.toml`.
5. For the dbt MCP, set `DBT_PROJECT_DIR` and `DBT_PATH` in your environment for `.mcp.json`, and fill the same values into `.codex/config.toml`. In Codex, trust the project and approve the hook in `/hooks`.
6. Add `.agents/project_map.md` and `target/agent/` to `.gitignore`.
7. Run `uv run --no-project python scripts/agent_check.py`. Its list of open questions is your backlog of business conversations.

## Notes

- The scripts use only the standard library and need Python 3.11+. The hooks, MCP configs and AGENTS.md call them through `uv`. Without uv, replace `uv run --no-project python` with your Python 3.11+ executable. Without that change, Claude Code blocks every shell and MCP call until the guard can start.
- The check needs a local dbt Core or Fusion CLI. It does not work with a dbt platform–only setup.
- `compile = true` opens a warehouse connection. Leave it off if your login is interactive (SSO), or the check will wait on a browser prompt.
- The Codex hook finds the guard with `$(git rev-parse --show-toplevel)`, which works in bash and PowerShell. Check that it blocks a test `dbt run` once on a new machine.
