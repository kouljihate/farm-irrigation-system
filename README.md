# Farm Irrigation Workbench

Flask + MongoDB web application for farm irrigation system design, geometry editing, hydraulic planning, field layout, and reporting.

## Version

**2.3.0**

Version 2.3.0 reflects the current application architecture and design defaults:

- Configurable farm and irrigation geometry
- Configurable sector and zone design
- Configurable pipe diameter defaults
- Leaflet + Leaflet-Geoman map editing
- KML and KMZ import support
- MongoDB as the authoritative geometry store
- Shared GeoJSON map rendering across the application
- Bilingual English / Arabic UI
- Flaticon UIcons for application actions

## Application Architecture

The application uses MongoDB as the source of truth for farm geometry and exposes that geometry through Flask APIs as GeoJSON.

```text
MongoDB
   ↓
Flask / API
   ↓
GeoJSON
   ↓
Leaflet
   ↓
Leaflet-Geoman
   ↓
Flask geometry API
   ↓
MongoDB
```

Leaflet and Leaflet-Geoman are used throughout the web application for interactive map display and geometry editing. The Project Map, Sectors, Zones, and related geometry workflows use the shared map engine where applicable.

## Farm Design Model

Farm dimensions, sector sizing, zone configuration, pipe diameters, and hydraulic design parameters are configurable through the application configuration.

The farm water infrastructure supports a well and basin/water source. Elevation data can be supplied through the imported KML/KMZ geometry.

## Stack

- **Backend:** Flask 3.x, PyMongo 4.x
- **Database:** MongoDB (local or Atlas)
- **Geometry:** Shapely 2.x, NumPy
- **Frontend:** Bootstrap 5, Leaflet
- **Map editing:** Leaflet-Geoman
- **Import:** KML / KMZ
- **Export:** KML, DXF, GeoJSON, CSV
- **Validation:** Pydantic 2.x
- **Authentication:** Flask-Login with role-based access
- **Testing:** pytest

## Install

### Windows

```bash
python -m venv venv
venv\\Scripts\\activate
pip install -r requirements.txt
```

### macOS / Linux

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## MongoDB

Install MongoDB Community Edition locally or use MongoDB Atlas.

Default local connection:

```text
mongodb://localhost:27017
```

Copy `.env.example` to `.env` and configure the environment for your installation.

Example:

```text
MONGO_HOST=localhost
MONGO_PORT=27017
MONGO_DB=farm_irrigation
SECRET_KEY=your-secret-key
FLASK_DEBUG=1
LOG_LEVEL=INFO
```

Do not commit `.env` or secret keys.

## Run

```bash
python run.py
```

Then open:

```text
http://127.0.0.1:5000
```

## Domain Workflow

The application follows the irrigation design workflow:

1. **Project**
   - Create/open the farm project.
   - Import the source KML or KMZ.
   - Configure land, water source, basin, and elevation information.

2. **Geometry**
   - **Sectors** — create and edit configurable farm sectors.
   - **Zones** — split sectors into configurable irrigation zones.
   - Interactive geometry editing is performed with Leaflet-Geoman.

3. **Hydrology**
   - MainLine
   - SubLines
   - Valves
   - Hydraulic design checks

4. **Field**
   - Rows
   - Trees
   - DripLine

5. **Report**
   - BOM
   - KML
   - DXF
   - GeoJSON
   - CSV

## Geometry Editing

The map workflow supports interactive geometry operations including:

- Polygon
- Line
- Marker
- Edit
- Move
- Delete/remove where enabled
- Sector selection
- Multi-selection
- Sector split/merge workflows
- Shared map data loading
- GeoJSON persistence through the Flask API

The Sectors and Zones pages synchronize map selection with their corresponding tables.

## KML / KMZ Import

The Project → Initialize workflow accepts:

- `.kml`
- `.kmz`

KMZ files are ZIP archives containing KML data. The importer supports the standard `doc.kml` convention and falls back to another KML entry when necessary.

The imported geometry is converted into the application's GeoJSON/domain representation and stored in MongoDB.

## Project Structure

| Folder/File | Purpose |
|---|---|
| `app.py` | Flask application factory and blueprint registration |
| `run.py` | Development server entry point |
| `config.py` / `config.yaml` | Application and irrigation design configuration |
| `routes/` | Project, Geometry, Hydrology, Field, Report and API routes |
| `core/` | Domain logic for KML, geometry, piping, rows, trees, driplines, valves, BOM and validation |
| `db/` | MongoDB connection, repositories, queries and models |
| `templates/` | Jinja2 templates grouped by application module |
| `static/` | CSS and JavaScript, including the shared Leaflet map engine |
| `imports/` | Imported source files |
| `exports/` | Generated export/report files |
| `tests/` | Automated tests |

## API

The application exposes project and geometry APIs including:

```text
GET  /api/v1/summary
GET  /api/v1/geojson
GET  /api/v1/bounds
GET  /api/v1/zones
GET  /geometry/tasks/<id>
GET  /geometry/tasks
PUT  /api/geometry/<collection>/<object_id>
```

The geometry API persists edited GeoJSON geometry to the corresponding MongoDB collection.

## Configuration

The main design configuration is stored in `config.yaml`.

Farm dimensions, sector/zone rules, pipe diameters, hydraulic parameters, and other design defaults are configurable rather than fixed in the documentation.

Environment variables in `.env` override deployment-specific settings and secrets.

## Testing

Run the core test suite with:

```bash
python -m pytest tests/test_core.py -v
```

For the full test suite:

```bash
python -m pytest -v
```

## Security

- Keep `.env` out of source control.
- Never commit MongoDB passwords, Flask secret keys, or API credentials.
- Rotate any credential that has previously been exposed.
- Use HTTPS and secure cookie settings in production.
- Review authorization and CSRF protections before production deployment.

## License

No open-source license is currently declared for this repository.
