# Changelog

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
