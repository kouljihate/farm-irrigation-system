# Changelog

## 2.2.0 — 2026-10-03

### Geometry Operations
- Added the exact Sectors and Zones action toolbar: Add, Rename, Remove, Swap, Split, Merge and Smart Create / Smart Split.
- Added sector rename and swap operations with dependent zone/valve reference updates.
- Added zone add, rename, remove, swap, split and merge operations.
- Added deterministic Smart Create for sectors using the land boundary, water-point proximity and optional elevation data.
- Added deterministic Smart Split using the configured 3-zone-per-sector default.
- Derived hydraulic pipes are cleared when sector identity changes so Hydrology can rebuild from the new topology.
- Added core/smart_geometry.py as the deterministic geometry service boundary.

### Configuration
- Application version bumped to 2.2.0.
- Retained 1.0 ha sector target, 3 zones per sector and 90/63/32 mm pipe defaults.


## 2.1.0 — 2026-10-03

### UI / Domain Refactoring
- Reorganized primary workflow as Project → Geometry → Hydrology → Field → Report.
- Limited Geometry navigation to Sectors and Zones.
- Moved Valves into Hydrology alongside MainLine and SubLines.
- Added a dedicated Hydrology Valves view and generation workflow.
- Kept `/geometry/valves` as a compatibility redirect to Hydrology.
- Renamed the user-facing Export module to Report while preserving existing report/download endpoints.
- Standardized domain terminology to MainLine, SubLines and DripLine.

### Design Defaults
- Sector target area: 1.0 ha.
- Zones per sector: 3.
- MainLine: 90 mm.
- SubLine: 63 mm.
- DripLine: 32 mm.

### Documentation
- Updated README workflow, module structure and configuration documentation.
- Version remains synchronized at 2.1.0.
