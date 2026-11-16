# Source adapters and project rules

## Configuration

JSON follows project conventions. `assets/project.example.json` is an adaptation example, not an engineering naming standard. Dictionary overrides merge with defaults; list overrides replace the entire list. Omitted keys retain defaults. Unknown top-level keys are refused. Do not narrow `tag_patterns` to the example's subset unless it matches the project.

| Setting | Meaning |
|---|---|
| tag_patterns | Regex patterns for drawing/specification candidate tags; explicit mapped schedule tags need not match them |
| tag_aliases, prefix_aliases | Explicit project identifier equivalences; do not remove leading zeroes implicitly |
| categories | Full configurable list of id, discipline, aliases, prefixes and optional description_patterns |
| category_aliases, discipline_aliases | Explicit labels to canonical project terms |
| building_aliases, floor_aliases | Only supplied naming equivalences, never inferred locations |
| parameter_aliases | Header/parameter names to canonical names |
| units | Unit to `[dimension, positive factor, canonical unit]`; multiplicative conversions only |
| type_required_parameters, type_required_by_category | Material fields required before type confirmation |
| unitless_parameters | Explicit dimensionless numeric parameters, e.g. phase/poles |
| match_context_fields | Comparison fields among building, floor, room, system, scope |
| numeric_relative_tolerance | Defined numeric comparison tolerance, default 0.000001; not a match probability |
| max_candidate_pairs, max_records | Visible relationship budget / hard import row limit |
| max_pdf_bytes, max_json_bytes, max_zip_uncompressed_bytes | Input resource bounds |
| max_regex_text | Per-line candidate search bound; truncated drawing search emits an issue |
| quantity_units | Explicit discrete-item unit spellings eligible for independent declared totals |
| auto_confirm | Must remain false in this release |

Default category families cover AHU/FAHU/FCU, chillers, CHW/condenser/heating pumps, fans, VRF/VRV/PAC; electric/diesel/jockey fire pumps and controllers; domestic/booster/transfer/sewage/sump pumps, heaters, tanks and water treatment; transformers/generators/MDB/SMDB/DB/MCC/ATS/UPS/capacitor banks; fire alarm panels/network cabinets/CCTV/access control; BMS/DDC/control panels. Unrecognized or ambiguous categories stay unknown. `FP` is deliberately not assumed to mean a particular pump discipline.

Whitespace, underscores and common dash variants normalize to hyphens, with uppercase preserved; numeric zero padding is retained. Original identifiers remain in raw evidence. Alias rules are supplied project assertions, not proof of physical identity.

Units retain original names/values and separate normalized fields. Built-in multiplicative conversions cover common volumetric flow, active/apparent power, voltage/current, length, pressure, frequency and speed. A plain numeric value without unit stays unconverted. A numeric string with an explicitly recognized unit suffix can be parsed without inventing a unit. kVA is not converted to kW; head is not converted to pressure without the required physical context. Formula text remains unresolved. Unsupported units, decimal conventions and text arrangements remain raw. No unspecified technical parameter is filled in.

## Mapped tables

Use `assets/schedule-map.example.json` or `assets/boq-map.example.json` after removing absent columns and setting actual sheet/header names. No universal headers are assumed. Valid columns include tag, description, category, discipline, system, building, floor, room, room_name, quantity, quantity_unit, item_number, section, drawing_number, revision, schedule_reference, equipment_type, identity_kind, related_tag, controller_tag, control_panel_tag, relation_type, spec_section and scope.

`parameters` names the original value column and either unit_column or fixed_unit. A fixed unit requires `unit_basis` describing its observed header or documented convention. Raw cells, headers and parameter mappings are retained. Constants are limited to explicit discipline/system/building/floor/scope/category/identity_kind/schedule_reference assertions and cannot contradict a mapped row. They carry mapping provenance, not automatic approval.

BOQ needs no tag. Preserve item number/description/unit/quantity/section and exact source row. A BOQ row defaults to a group; an item can represent several units, accessories or a package. A non-unit declared quantity is never promoted to one instance. Price/rate/cost fields are not mapped or analyzed; recognizable financial columns are omitted from copied raw table dictionaries. The original registered document bytes and existing upstream evidence remain retained independently.

PDF table maps also require an actual one-based `pdf_page`, helper-produced `table_id` (such as `p4-t1`), and actual table `header_row`. These are source locators selected from extraction evidence, not invented labels. Table-row bounding boxes and original page/row indices remain. Borderless/merged/scanned tables may need a verified external extraction instead.

Use a comparable explicit `scope` for quantity comparisons. Scope may be a scalar label or structured JSON; structured values are retained and canonicalized for equality. No floor/room is inferred from a nearby unrelated label. A broad package quantity must not be treated as comparable to a single-level drawing count.

## CAD exports

`import-cad` directly reuses `dwg-to-excel.ingest_export`. Adapt `assets/cad-map.example.json` to actual headers, coordinate system and attributes. Only INSERT rows are candidates. Exact workbook sheet/row, block, layer, handle, coordinates, units and same-row attributes remain. No adjacent ATTRIB rows are joined by proximity. The export XLSX is the actual registered source; the tool does not claim verified native-DWG lineage or transfer export facts onto the DWG.

Optional DXF uses real ezdxf INSERT attributes only. It preserves layout, handle/layer, insertion coordinates and native units code. It does not traverse XREFs, recognize equipment symbols or derive physical room assignments. No native DWG parser or converter is executed.

## Structured JSON and existing SQL

Accepted envelopes are `mep-evidence/1` and `mep-equipment-observations/1`. Both require:

```text
schema_version
document.sha256 = exact hash of original registered source
records[] = {kind, raw_text, source, data, review}
issues[]
```

This is a structural contract, not runnable sample project evidence. `source.method` is mandatory. Source PDF pages and table rows are actual positive one-based integers. PDF pages are checked against the archived PDF. Preserve applicable table_id, sheet, row, bbox, CAD handle/layer/attribute/coordinates and spec_section/clause. Missing fields stay null; caller-supplied references are unreviewed assertions until checked against the source.

Equipment records use `kind: equipment`. `data` can contain the mapped fields above plus `parameters: [{name,value,unit,...original-column-evidence}]`, block/attributes and explicit scope. `identity_kind` is instance/type/group/reference. Electrical/BMS/specification roles default to references; BOQ defaults to group. One occurrence's repeated appearances never prove multiple physical items.

Existing extracted specification records (`kind: specification`, paragraph or specification_clause) can be imported with role specification. Exact section/clause/page fragments remain; literal tags and configurable category patterns can propose applicability. A category/discipline or scope association remains a candidate. Generic paragraphs do not become confirmed requirements or compliance decisions.

An explicit `related_tag`, `controller_tag` or `control_panel_tag` permits a proposed documented relationship. `relation_type` may identify requires_electrical_supply, control_panel_association, bms_reference or cross_discipline_reference. It must be supported by the mapped source, not invented to complete a relationship. No wiring, loads or control sequence is synthesized.

`import-sql` selects a named existing extraction run whose byte hash and registered source identity match. It retains `core_record_id` and original records; it never accepts caller-supplied SQL. Multiple extraction outputs are not silently combined. Equipment corrections/approvals have their own target semantics and do not overwrite existing core/registry decisions.
