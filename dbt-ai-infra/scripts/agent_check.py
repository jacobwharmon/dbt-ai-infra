"""Static agent check: parse the dbt project, enforce contract and layer rules from the
manifest, and write .agents/project_map.md. Never touches warehouse data.

Usage: python scripts/agent_check.py   (Python 3.11+, settings in .agents/check.toml)
Exit 1 = agent-fixable failures. Open human questions are listed but do not fail the check.
"""
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG = tomllib.loads((ROOT / ".agents" / "check.toml").read_text(encoding="utf-8"))
PROJECT = (ROOT / CFG.get("project_dir", ".")).resolve()

MODEL_KEYS = ["grain", "unique_key", "required_fields", "relationships", "accepted_values",
              "rows_dropped", "rows_multiplied", "reconciles_to", "idempotent"]
SOURCE_KEYS = ["source_key", "duplicates", "ingest_idempotent"]
UNIQUE_TESTS = {"unique", "unique_combination_of_columns"}
RECONCILE_TESTS = {"reconciles_to", "equal_rowcount", "equality"}
# contract key -> test that must exist when the answer is not "none"
SIMPLE_TESTS = {"relationships": {"relationships"}, "accepted_values": {"accepted_values"}, "reconciles_to": RECONCILE_TESTS}

fix, human = [], []  # (node, message)


def dbt(*args):
    cmd = list(CFG.get("dbt", ["dbt"])) + list(args) + ["--project-dir", str(PROJECT)]
    try:
        result = subprocess.run(cmd, cwd=PROJECT, capture_output=True, encoding="utf-8", errors="replace", timeout=600)
    except (OSError, subprocess.TimeoutExpired) as e:
        sys.exit(f"FAILED: {' '.join(cmd)}\n{e}")
    if result.returncode:
        sys.exit(f"FAILED: {' '.join(cmd)}\n{result.stdout[-4000:]}{result.stderr[-2000:]}")


def manifest_for(target):
    path = f"target/agent/{target or 'default'}"
    dbt("parse", *(["--target", target] if target else []), "--target-path", path)
    return json.loads((PROJECT / path / "manifest.json").read_text(encoding="utf-8"))


def in_layer(node, key):
    return any(p in CFG.get(key, []) for p in node["fqn"][1:-1])


def meta_contract(node):
    meta = {**node.get("meta", {}), **node.get("config", {}).get("meta", {})}
    return meta.get("contract") or {}


def unanswered(value):
    return value in (None, "", []) or (isinstance(value, str) and value.strip().upper().startswith("TODO"))


def is_no(value, word="no"):
    return isinstance(value, str) and re.match(rf"{word}\b", value.strip().lower()) is not None


def as_set(value):
    return {v.lower() for v in ([value] if isinstance(value, str) else value)}


def has_unique(node_tests, key):
    return any(t in UNIQUE_TESTS and as_set(kw.get("combination_of_columns") or [col or ""]) == as_set(key)
               for t, col, kw in node_tests)


def relation(node):
    return ".".join(p for p in (node.get("database"), node.get("schema"), node.get("alias") or node.get("identifier")) if p)


targets = CFG.get("targets") or [None]
manifests = {t: manifest_for(t) for t in targets}
primary = manifests[targets[0]]
if CFG.get("compile"):
    dbt("compile", *(["--target", targets[0]] if targets[0] else []), "--target-path", f"target/agent/{targets[0] or 'default'}")

project = primary["metadata"]["project_name"]
models = {k: n for k, n in primary["nodes"].items() if n["resource_type"] == "model" and n["package_name"] == project}
sources = {k: s for k, s in primary["sources"].items() if s["package_name"] == project}

# Tests that can actually fail, per tested node: {node_id: [(test_name, column, kwargs)]}
tests = {}
for n in primary["nodes"].values():
    cfg = n.get("config", {})
    if n["resource_type"] != "test" or not n.get("test_metadata") or cfg.get("where") or cfg.get("severity", "").lower() == "warn":
        continue
    md = n["test_metadata"]
    for parent in [n["attached_node"]] if n.get("attached_node") else [d for d in n["depends_on"]["nodes"] if d.startswith("source.")]:
        tests.setdefault(parent, []).append((md["name"], n.get("column_name"), md.get("kwargs", {})))

for uid, m in models.items():
    name = m["name"] + (f" v{m['version']}" if m.get("version") is not None else "")
    if not in_layer(m, "source_layers") and any(d.startswith("source.") for d in m["depends_on"]["nodes"]):
        fix.append((name, f"calls source() outside {CFG.get('source_layers')}"))
    if not in_layer(m, "contract_layers"):
        continue
    c, node_tests = meta_contract(m), tests.get(uid, [])
    names = {t for t, _, _ in node_tests}
    for key in MODEL_KEYS:
        if unanswered(c.get(key)):
            human.append((name, f"{key}: {c.get(key) or 'missing'}"))
    if m["config"].get("materialized") != "ephemeral":
        cols = m.get("columns", {})
        if not m["config"].get("contract", {}).get("enforced"):
            fix.append((name, "config.contract.enforced is not true"))
        elif not cols or any(not col.get("data_type") for col in cols.values()):
            fix.append((name, "enforced contract needs every column listed with a data_type"))
    if not unanswered(c.get("unique_key")) and not has_unique(node_tests, c["unique_key"]):
        fix.append((name, f"no failing-severity uniqueness test on unique_key {sorted(as_set(c['unique_key']))}"))
    req = c.get("required_fields")
    if not unanswered(req) and not is_no(req, "none"):
        tested = {col.lower() for t, col, _ in node_tests if t == "not_null" and col}
        if missing := as_set(req) - tested:
            fix.append((name, f"required_fields without not_null tests: {sorted(missing)}"))
    for key, wanted in SIMPLE_TESTS.items():
        if not unanswered(c.get(key)) and not is_no(c.get(key), "none") and not names & wanted:
            fix.append((name, f"{key} is answered but no {'/'.join(sorted(wanted))} test exists"))
    if is_no(c.get("rows_multiplied")) and not any(
        t == "equal_rowcount" or (t == "reconciles_to" and "1" in [str(x) for x in kw.get("measures", [])]) for t, _, kw in node_tests
    ):
        fix.append((name, 'rows_multiplied is "no" but no row-count reconciliation (reconciles_to with measure "1")'))

for uid, s in sources.items():
    name = f"{s['source_name']}.{s['name']}"
    c = meta_contract(s)
    fresh = s.get("freshness") or s.get("config", {}).get("freshness") or {}
    if not ((fresh.get("warn_after") or {}).get("count") or (fresh.get("error_after") or {}).get("count")) \
            and not is_no(c.get("freshness"), "none"):
        human.append((name, 'freshness: missing (or meta.contract.freshness: "none: <why>")'))
    for key in SOURCE_KEYS:
        if unanswered(c.get(key)):
            human.append((name, f"{key}: {c.get(key) or 'missing'}"))
    if is_no(c.get("duplicates")) and not unanswered(c.get("source_key")) and not has_unique(tests.get(uid, []), c["source_key"]):
        fix.append((name, f'duplicates is "no" but no uniqueness test on source_key {sorted(as_set(c["source_key"]))}'))

# ---- project map ----
labels = [t or "default" for t in targets]
lines = ["# Project map", "", f"Generated by scripts/agent_check.py (targets: {', '.join(labels)}). Do not edit.", "",
         "## Models", "", "| model | folder | materialized | " + " | ".join(f"relation ({t})" for t in labels) + " | grain | unique_key | parents |",
         "|" + " --- |" * (6 + len(targets))]
for uid, m in sorted(models.items(), key=lambda kv: (kv[1]["fqn"], kv[0])):
    c = meta_contract(m)
    parents = ", ".join(p.split(".", 2)[-1] for p in m["depends_on"]["nodes"])
    rels = " | ".join(relation(manifests[t]["nodes"].get(uid, {})) for t in targets)
    lines.append(f"| {m['name']} | {'/'.join(m['fqn'][1:-1])} | {m['config'].get('materialized')} | {rels} | {c.get('grain', '')} | {c.get('unique_key', '')} | {parents} |")
lines += ["", "## Sources", "", "| source | relation | source_key | duplicates |", "| --- | --- | --- | --- |"]
for s in sorted(sources.values(), key=lambda s: (s["source_name"], s["name"])):
    c = meta_contract(s)
    lines.append(f"| {s['source_name']}.{s['name']} | {relation(s)} | {c.get('source_key', '')} | {c.get('duplicates', '')} |")
if human:
    lines += ["", "## Open contract questions", ""] + [f"- {n}: {msg}" for n, msg in human]
out = ROOT / ".agents" / "project_map.md"
out.write_text("\n".join(lines) + "\n", encoding="utf-8")

# ---- report ----
print(f"Parsed {len(models)} models, {len(sources)} sources (targets: {', '.join(labels)}). Map: {out.relative_to(ROOT)}")
for title, items in (("AGENT-FIXABLE", fix), ("NEEDS A HUMAN DECISION (does not fail the check)", human)):
    grouped = {}
    for n, msg in items:
        grouped.setdefault(n, []).append(msg)
    if grouped:
        print(f"\n{title}: {len(grouped)} nodes")
        print("\n".join(f"  - {n}: {'; '.join(msgs)}" for n, msgs in grouped.items()))
sys.exit(1 if fix else 0)
