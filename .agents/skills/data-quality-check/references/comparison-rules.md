# Scoped comparison configuration

Every rule is a project-supplied expectation, not a universal MEP standard. Explicit aliases and tag patterns must come from the project's naming conventions.

```json
{
  "tag_patterns": {"HVAC":"AHU-[0-9]{2}", "Electrical":"DB-[A-Z0-9-]+"},
  "tag_mapping": {"AHU/01":"AHU-01"},
  "required_parameters": {"HVAC":["airflow", "electrical_power"]},
  "cross_discipline_conditions": [
    {
      "from_tag":"AHU-01", "from_discipline":"HVAC",
      "requires_tag":"DB-M-01", "required_discipline":"Electrical",
      "scope":"Building A Level 01"
    }
  ]
}
```

These example requirements are not defaults. A BMS/Low Current dependency must also be explicitly configured and evidenced. Never turn an inferred connection or unverified equipment naming pattern into a project requirement.

Equipment facts should include tag, discipline, role, explicit scope, nullable quantity, and parameters with named units. Quantity unit can be supplied as `quantity_unit`. A physical equipment count and a tag-occurrence count are different facts. Parsed specification prose is not a numeric parameter until extraction/review establishes its meaning, unit, operator and equipment scope.

The script preserves raw units in findings; verified conversions include W/kW/MW, volumetric flow m3/s/m3/h/L/s, pressure Pa/kPa/bar, and simple dimensional units. It does not convert power to apparent power, pressure to head without fluid data, or reinterpret a minimum requirement as an equality. Unknown/non-comparable values produce review findings.

Cross-file checks require explicit identical scope/discipline/tag; the absence of a scope is not permission to merge projects/floors. Missing equipment comparisons require both drawing and schedule inventory roles to be supplied, with real equipment records rather than annotation-only occurrences. Findings include the inspected opposing inventory references and still require a completeness review.
