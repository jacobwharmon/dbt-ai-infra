"""PreToolUse hook for Claude Code and Codex: block tool calls that execute against the
warehouse. Reads the hook JSON on stdin; exit 2 blocks with a reason. A guardrail against
agent mistakes, not a security boundary. Edit the patterns below to change the rule.
"""
import json
import re
import sys

# `dbt`/`dbtf`/`dbt.cli.main` at command position: line start, after ; & | ( or backtick, inside
# `bash -c '...'`/`pwsh -Command '...'`/`cmd /c "..."`, after env assignments, or after a runner
# such as `uv run --project x` or `python -m`. Any path prefix, quoted or not.
DBT = (r"(?:^|[;&|(\n`]|-c\s+['\"]|-Command\s+['\"]|/c\s+['\"]?)\s*"
       r"(?:env\s+)?(?:\w+=\S*\s+)*"
       r"(?:(?:uv|uvx|poetry|pipenv|pdm|hatch|python\d*|py)(?:\.exe)?\s[^;&|\n]*?)?"
       r"['\"]?(?:[^'\"\n;&|]*[/\\])?(?:dbtf?(?:\.exe)?|dbt\.cli\.main)['\"]?\s+")
SUB = r"(?:build|clean|clone|compile|deps|docs|init|list|ls|parse|retry|run|run-operation|seed|show|sl|snapshot|source|test)(?=\s|$|['\"])"
BLOCKED_SUB = r"(?:build|clone|retry|run|run-operation|seed|show|sl|snapshot|source|test)(?=\s|$|['\"])"

BLOCKED_SHELL = [
    rf"{DBT}(?:(?!{SUB})\S+\s+)*{BLOCKED_SUB}",  # first subcommand after dbt and its flags
    rf"{DBT}[^;&|\n]*\b(?:run_query|statement)\b",  # compile --inline used to read data
    # Add warehouse CLIs here, e.g. r"(?:^|[;&|\n])\s*(?:snowsql|bq\s+query|psql|databricks)\b".
]
# dbt MCP tools that execute (keep in step with DISABLE_TOOLS in .mcp.json and .codex/config.toml).
BLOCKED_MCP = r"^mcp__.*dbt.*__(run|build|test|show|clone|execute_sql|text_to_sql|query_metrics|get_dimension_values|trigger_job_run|retry_job_run)$"

REASON = ("Blocked by scripts/agent_guard.py: agents may not execute against the warehouse. "
          "Use parse/compile, and write proof queries to analyses/ for the human to run.")


def strings(value):
    """Every string in the tool input, so shell-running MCP tools are checked too."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from strings(v)
    elif isinstance(value, list):
        yield " ".join(v for v in value if isinstance(v, str))  # argv-style command arrays
        for v in value:
            yield from strings(v)


event = json.loads(sys.stdin.buffer.read().decode("utf-8"))
tool = event.get("tool_name", "")
if re.search(BLOCKED_MCP, tool) or any(
    re.search(p, s, re.MULTILINE) for s in strings(event.get("tool_input")) for p in BLOCKED_SHELL
):
    print(REASON, file=sys.stderr)
    sys.exit(2)
