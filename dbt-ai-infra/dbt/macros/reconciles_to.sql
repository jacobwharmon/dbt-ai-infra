{#-
    Generic test: the model's measures, summed by group_by, must match compare_model within tolerance.
    Returns one row per mismatched group. Measure "1" reconciles row counts.
    group_by are plain column names whose types match on both sides; use tolerance > 0 for float measures.
    Names that differ upstream go in compare_measures / compare_group_by (same order).
-#}
{% test reconciles_to(model, compare_model, measures, group_by=[], compare_measures=none, compare_group_by=none, compare_where=none, tolerance=0) %}
{%- set compare_measures = compare_measures or measures -%}
{%- set compare_group_by = compare_group_by or group_by -%}
with signed as (
    select
        {%- for col in group_by %}
        {{ col }} as group_{{ loop.index }},
        {%- endfor %}
        {%- for expr in measures %}
        {{ expr }} as measure_{{ loop.index }}{{ "," if not loop.last }}
        {%- endfor %}
    from {{ model }}
    union all
    select
        {%- for col in compare_group_by %}
        {{ col }},
        {%- endfor %}
        {%- for expr in compare_measures %}
        -({{ expr }}){{ "," if not loop.last }}
        {%- endfor %}
    from {{ compare_model }}
    {%- if compare_where %}
    where {{ compare_where }}
    {%- endif %}
)
select
    {%- for col in group_by %}
    group_{{ loop.index }} as {{ col }},
    {%- endfor %}
    {%- for expr in measures %}
    sum(measure_{{ loop.index }}) as diff_{{ loop.index }}{{ "," if not loop.last }}
    {%- endfor %}
from signed
{%- if group_by %}
group by {% for col in group_by %}group_{{ loop.index }}{{ ", " if not loop.last }}{% endfor %}
{%- endif %}
having
    {%- for expr in measures %}
    abs(coalesce(sum(measure_{{ loop.index }}), 0)) > {{ tolerance }}{{ " or" if not loop.last }}
    {%- endfor %}
{% endtest %}
