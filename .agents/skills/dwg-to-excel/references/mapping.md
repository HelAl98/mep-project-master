# Explicit DWG export mapping

Inspect the real workbook before mapping. Header names below are examples, not a promised DwgExporter schema. All mapped headers must exist exactly once; duplicate headers are rejected.

```json
{
  "sheet": "Elements",
  "header_row": 1,
  "columns": {
    "entity_type": "EntityType",
    "tag": "EquipmentTag",
    "block": "BlockName",
    "layer": "Layer",
    "handle": "Handle",
    "x": "InsertX",
    "y": "InsertY",
    "units": "Units",
    "drawing_id": "DrawingID"
  },
  "attribute_columns": {"FLOW": "Attr_FLOW"},
  "discipline": "HVAC",
  "coordinate_system": "drawing WCS",
  "role": "drawing",
  "scope": "Building A Level 01",
  "parameters": [
    {"name":"electrical_power", "value_column":"Power", "unit_column":"PowerUnit"}
  ]
}
```

Delete unavailable fields rather than inventing values. Do not supply a coordinate system, comparison scope, discipline or fixed unit without a project basis. `attributes` can instead map an explicit JSON-object column; `tag_from_attribute` can name an attribute only when it belongs to that same row. `quantity` may map an explicit equipment quantity; a row or annotation occurrence is not a verified physical count. Preserve drawing and workbook identifiers separately.

Metadata can provide known document ID/revision/drawing number. Optional `original_dwg` has `path` and `sha256`; it is checked against real bytes. A matching hash is not proof of export-to-DWG correspondence. Both files need documented linkage before treating the XLSX as authoritative DWG evidence.
