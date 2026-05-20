# LAS Well Log Viewer

Web app for uploading `.las` well log files, parsing Log ASCII Standard data, and plotting curves by depth.

## Domain Context

LAS means Log ASCII Standard. It is a common oil and gas format for well log measurements collected down a wellbore. Each row contains a depth and one or more measured curves at that depth.

This viewer plots common curves:

```text
DT    Sonic delta-time, used as a porosity/lithology indicator
RESD  Deep resistivity, often reviewed for fluid and reservoir interpretation
SP    Spontaneous potential, useful for bed boundaries and permeable zones
GR    Gamma ray, commonly used to distinguish shale from cleaner sands/carbonates
```

Depth is shown on the vertical axis and increases downward, matching how wells are interpreted. The GR track includes light background shading: lower GR intervals are treated as cleaner sand/reservoir candidates, while higher GR intervals are treated as shale-rich intervals. Resistivity is plotted on a logarithmic scale because resistivity values can span several orders of magnitude.

## Project Structure

```text
las_project/
  backend/     FastAPI API for parsing LAS files
  frontend/    Vue 3 + ECharts interface
  samples/     Example LAS files
  docs/        Original internship task PDF
```

## Backend

The backend exposes:

```text
GET  /health
POST /api/parse-las
```

`POST /api/parse-las` accepts a `.las` file and returns well metadata, depth values, curve metadata, and curve series.

The backend also:

- Cleans common LAS null values such as `-999.25`, `-9999`, `999.25`, and `NaN`.
- Uses gzip compression for larger JSON responses.
- Caches recently parsed uploads in memory by file hash.

### Run Locally

```bash
cd las_project/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8001
```

Open:

```text
http://localhost:8001/docs
```

### Railway Deploy

Deploy the `las_project/backend` folder as the Railway service root.

Set this variable after the Firebase frontend is deployed:

```text
ALLOWED_ORIGINS=https://your-firebase-project.web.app,https://your-firebase-project.firebaseapp.com
```

The backend start command is:

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

## Frontend

The frontend uploads LAS files to the backend and plots selected curves with inverted depth.

### Run Locally

```bash
cd las_project/frontend
npm install
cp .env.example .env
npm run dev
```

For local development, `.env` should contain:

```text
VITE_API_URL=http://localhost:8001
```

Open:

```text
http://localhost:5173
```

### Firebase Deploy

Install Firebase CLI:

```bash
npm install -g firebase-tools
firebase login
```

Build and initialize hosting:

```bash
cd las_project/frontend
npm run build
firebase init hosting
```

Use these Firebase answers:

```text
Public directory: dist
Single-page app: Yes
Overwrite index.html: No
```

Deploy:

```bash
firebase deploy --only hosting
```

For production, set the frontend API URL before building:

```bash
VITE_API_URL=https://your-railway-backend.up.railway.app npm run build
firebase deploy --only hosting
```

## Minimal Test Flow

1. Start backend locally.
2. Start frontend locally.
3. Upload one file from `samples/`.
4. Confirm well metadata appears.
5. Select curves such as `DT`, `RESD`, `SP`, `GR`.
6. Confirm the chart shows depth increasing downward.

## Notes

- The backend uses `lasio` for parsing and falls back to a simple parser for basic LAS 2.0 files.
- The chart uses ECharts with linked depth zoom, inverted depth, GR shading, and logarithmic resistivity tracks.
- Database storage is not included in the first version; parsed uploads use a small in-memory cache only.
