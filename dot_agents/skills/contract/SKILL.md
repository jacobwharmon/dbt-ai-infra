---
name: contract
description: Define, review, or enforce the data contract for a dbt model or source (grain, keys, freshness, duplicates, required fields, relationships, domains, row loss or fanout, reconciliation, idempotence). Use before creating or changing a contracted model or source, including when turning a working SQL query into models.
---

# Data contracts

The human owns the answers. The agent drafts them from the code, asks, and enforces them. Native dbt config holds what dbt can express; `meta.contract` holds the rest. `->` means "encode the answer as". `scripts/agent_check.py` checks that every answer exists and that the tests it can verify are present.

## Template: each question, where its answer lives, and how it is enforced

```yaml
sources:
  - name: <source>
    tables:
      - name: <table>
        loaded_at_field: <timestamp col>                        # Omit only if the adapter computes freshness from metadata
        config:
          freshness: {warn_after: {count: 24, period: hour}}    # Expected freshness? -> dbt source freshness
          meta:
            contract:                                           # (static table: freshness: "none: <why>" here instead)
              source_key: [<col>]                               # Source key?
              duplicates: "no"                                  # Possible? Allowable? "no" -> unique test here on the source.
                                                                #   "possible, deduped in <staging model> by <rule>" -> unique test on that model.
              ingest_idempotent: "yes"                          # Or "no: <what happens on reload>"

models:
  - name: <model>
    description: <one sentence>
    config:
      contract: {enforced: true}                                # Expected schema? -> every column below needs data_type
      meta:
        contract:
          grain: "one row per <entity> per <period>"            # Grain?
          unique_key: [<col>, <col>]                            # What makes it unique? -> unique / unique_combination_of_columns test
          required_fields: [<col>]                              # Required fields? -> not_null on each
          relationships: "<col> -> <model>.<col>"               # Or "none: <why>" -> relationships tests
          accepted_values: "<col>: a, b, c"                     # Valid domain values? Or "none: <why>" -> accepted_values tests
          rows_dropped: "no"                                    # Rows lost? Or "yes, intentional: <rule>"
          rows_multiplied: "no"                                 # Rows multiplied? Or "yes, intentional: <why>"
          reconciles_to: "<upstream>: <measures> by <columns>"  # Or "none: <why>" -> reconciles_to test
          idempotent: "yes: <how>"                              # Transformation idempotent? -> materialization / incremental config
    data_tests:
      - dbt_utils.unique_combination_of_columns:
          arguments: {combination_of_columns: [<col>, <col>]}
      - reconciles_to:                                          # measure "1" = row count; required when rows_multiplied is "no"
          arguments: {compare_model: "ref('<upstream>')", measures: ["1", "<amount>"], group_by: [<col>]}
    columns:
      - name: <col>
        data_type: <type>
        data_tests: [not_null]
```

Follow the repo's dbt version. Before 1.10, `freshness` and `meta` sit at the top level of the entry and test arguments go directly under the test name, without `arguments:`. Before 1.8, use `tests` instead of `data_tests`.

`compare_model` is the nearest relation upstream of the logic that can drop, multiply, or filter rows: usually the staging model at the driving grain. Never use a parent the model only selects from; that reconciliation proves nothing. Use `compare_where` when rows are dropped intentionally.

## Procedure

1. Read the model SQL and its upstream models (or the supplied query). Record the grain, the join types and cardinality, filter placement, `distinct`/`qualify`/window functions, unions, aggregation, dedup logic, and incremental behavior. These decide row counts.
2. Fill in every key. Write anything you cannot confirm from the code as `TODO: <proposed answer>`. Ask the human the open questions together in one short list. Record reasoning that will matter later in `DECISIONS.md`.
3. Add the tests and config the template calls for.
4. Write `analyses/proof_<model>.sql` for what tests cannot show before deployment. It should hold a duplicate check on `unique_key`, row counts before and after each join or filter that can drop or multiply rows, and the reconciliation by `group_by`. If you started from a working query, add an `except` in both directions between it and the model (the adapter's form, e.g. `except distinct`, `minus`). Use `ref()`. Each query should return nothing, or an obvious number, when the contract holds.
