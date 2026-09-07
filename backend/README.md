# Backend

This is a Python 3.12 FastAPI service. It does not need a `package.json`; that
file is for Node.js projects. Python dependencies are listed in
`requirements.txt`.

## Option 1: Docker Compose

From the repository root in PowerShell:

```powershell
Copy-Item backend/.env.example backend/.env
notepad backend/.env
docker compose up --build
```

Set `GEMINI_API_KEY` and `JWT_SECRET_KEY` in `backend/.env` before starting.
The stack starts ClickHouse, the API at <http://localhost:8080>, and the
dashboard at <http://localhost:3000>.

Docker Desktop must be installed and running for this option. Docker is only
needed when you want Compose to run a local ClickHouse instance for you. If you
already have ClickHouse running elsewhere, skip this section. If you are using
`cmd.exe` instead of PowerShell, use these equivalent commands:

```bat
copy backend\.env.example backend\.env
notepad backend\.env
docker compose up --build
```

## Option 2: Use an existing ClickHouse

Docker is not required when `CLICKHOUSE_HOST` points to your existing ClickHouse
server. Install Python 3.12, ffmpeg, and `uv` first. From the repository root,
run this in PowerShell:

```powershell
Set-Location backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
uvicorn app.main:app --reload --port 8080
```

The same setup in `cmd.exe` is:

```bat
cd backend
py -3.12 -m venv .venv
.venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
copy .env.example .env
notepad .env
python -m uvicorn app.main:app --reload --port 8080
```

For local development, `.env` must point at a reachable ClickHouse instance
and include `GEMINI_API_KEY` and a `JWT_SECRET_KEY` of at least 32 characters.
Install `uv` as well because the continuity agent launches the isolated
ClickHouse MCP server through it:

```powershell
pip install uv
```

The default Unix-style upload paths in `.env.example` can be replaced on
Windows, for example:

```dotenv
UPLOAD_DIR=C:/Users/User/Documents/continuity-agent/backend/uploads
FRAME_CACHE_DIR=C:/Users/User/Documents/continuity-agent/backend/frames
```

## Tests

With the virtual environment activated:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -v
```

The tests mock external ClickHouse, Gemini, and storage calls. The running
server itself still needs valid configuration for its startup migration.