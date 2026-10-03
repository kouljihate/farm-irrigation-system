# Farm Irrigation Workbench

Flask + MongoDB web application for orchard/farm irrigation system design.

## Version

**2.1.0** — UI/domain workflow refactoring for Project, Geometry, Hydrology, Field and Report, with 1 ha sector targets, 3 zones per sector, and 90/63/32 mm pipe defaults.

## Stack

- **Backend**: Flask 3.x, PyMongo 4.x
- **Geometry**: Shapely 2.x, NumPy
- **Report**: lxml (KML), ezdxf (DXF), GeoJSON, CSV
- **Frontend**: Bootstrap 5 (Bootswatch Journal), Leaflet 1.9, bilingual EN/AR
- **Database**: MongoDB (local or Atlas)
- **Validation**: Pydantic 2.x
- **Async**: ThreadPoolExecutor for long-running geometry operations
- **Auth**: Flask-Login with role-based access
- **Testing**: pytest

## Install

```bash
python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate       # macOS / Linux

pip install -r requirements.txt
```

## MongoDB

Install MongoDB Community Edition locally and start it as a service.
Default connection: `mongodb://localhost:27017`.

Copy `.env.example` to `.env` and adjust if needed:

```
MONGO_HOST=localhost
MONGO_PORT=27017
MONGO_DB=farm_irrigation
SECRET_KEY=your-secret-key
FLASK_DEBUG=1
LOG_LEVEL=INFO
```

**Indexes**: Auto-created on startup for all `project_id` fields + compound unique indexes.

## Run

```bash
python run.py
```

Open http://127.0.0.1:5000

## Domain Workflow

The application is organized around the following domain modules:

1. **Project** — create/load a project and import/link the land KML, water points and elevation data.
2. **Geometry**
   - **Sectors** — land sectors, targeting approximately 1 hectare per sector.
   - **Zones** — three irrigation zones per sector by default.
3. **Hydrology**
   - **MainLine** — main water distribution routing.
   - **SubLines** — distribution from mainline/valves to zones.
   - **Valves** — main and zone valve management.
4. **Field**
   - **Rows** — crop row layout.
   - **Trees** — tree placement.
   - **DripLine** — dripline layout.
5. **Report** — BOM and generated KML, DXF, GeoJSON and CSV outputs.

### Geometry actions

Sectors and Zones provide a consistent toolbar for:

`Add` · `Rename` · `Remove` · `Swap` · `Split` · `Merge` · `Smart Create/Split`

Smart geometry is intended to consider land boundary, elevation, water-point locations, area balance and practical pipe routing. Polygon construction remains deterministic and validation-driven.

### Design defaults

- Sector target area: **1.0 ha**
- Zones per sector: **3**
- MainLine diameter: **90 mm**
- SubLine diameter: **63 mm**
- DripLine diameter: **32 mm**
- Nominal emitter discharge: **2.0 L/h**

## Project Structure

| Folder/File | Purpose |
|---|---|
| `app.py` | Flask app factory and blueprint registration |
| `run.py` | Development server entry point |
| `config.py` / `config.yaml` | Configuration and validated domain defaults |
| `routes/` | Project, Geometry, Hydrology, Field, Report and supporting blueprints |
| `core/` | Domain logic: KML, geometry, piping, rows, trees, driplines, valves, BOM and validation |
| `db/` | MongoDB connection, repository, queries and models |
| `templates/` | Jinja2 templates grouped by domain module |
| `static/` | CSS and JavaScript |
| `imports/` | User-uploaded KML files |
| `exports/` | Generated report/export files |
| `tests/` | Unit and integration tests |

## Workflow

1. **Project** — create/open the project and import the source KML.
2. **Geometry → Sectors** — create or verify sectors; target approximately 1 ha each.
3. **Geometry → Zones** — split each sector into 3 zones by default.
4. **Hydrology → MainLine** — define mainline routing from water/basin infrastructure.
5. **Hydrology → SubLines** — route distribution lines to zones.
6. **Hydrology → Valves** — manage Main Valves (MV) and Zone Valves (ZV).
7. **Field → Rows** — generate/trace rows inside zones.
8. **Field → Trees** — place trees along rows.
9. **Field → DripLine** — generate dripline per row.
10. **Report** — generate BOM and download KML, DXF, GeoJSON and CSV outputs.
11. **Map** — inspect the complete design on the Leaflet map.

## Features

- Authentication with Flask-Login and role-based access
- Revision history for build steps
- Bilingual English/Arabic UI with RTL support
- Interactive Leaflet map
- Multiple deterministic zone split algorithms
- Pipe routing with direct and boundary-detour modes
- KML, DXF, GeoJSON and CSV reporting
- Pydantic input validation
- Async processing for long geometry operations
- MongoDB indexes
- Automated core algorithm tests

## API Endpoints

```
GET  /api/v1/summary      — Project summary counts
GET  /api/v1/geojson      — Full project as GeoJSON FeatureCollection
GET  /api/v1/bounds       — Property bounding box for map fit
GET  /api/v1/zones        — Zones only
GET  /geometry/tasks/<id> — Async task status
GET  /geometry/tasks      — All tasks for current project
```

## Configuration

Edit `config.yaml` for application version, MongoDB settings, import/export directories, geometry defaults, pipe diameters and hydraulic assumptions.

Environment variables in `.env` override YAML values for secrets and deployment-specific settings.

## Testing

```bash
python -m pytest tests/test_core.py -v
```

