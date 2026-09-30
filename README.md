# Data Quality Workbench for DHIS2

> ![Maturity: Validated](https://img.shields.io/badge/maturity-Validated-yellow)  
> Intended use: monitoring metadata and data quality issues in DHIS2
> Maintainers: HISP Centre implementation team.

A tool for monitoring data quality in DHIS2 by tracking validation rule violations,
outliers, and metadata integrity issues over time. Results are stored as regular data values
in DHIS2 data elements, making them available for analysis in maps, charts, and pivot tables.

## Quick start

### Windows installer

The easiest option for Windows users — no Python, Docker, or command line required.

Download `dq-workbench-X.Y.Z-windows-setup.exe` from the
[latest release](https://github.com/dhis2/tool-dq-workbench/releases/latest),
run the installer, and launch the app from the Start Menu. The browser opens
automatically and you are taken straight to the server setup page on first run.

> **SmartScreen warning:** Windows may warn that the installer is from an unknown
> publisher. Click **More info → Run anyway** to proceed.

### Docker

Docker works on Linux, macOS, and Windows (via WSL2). No Python installation required.

**Simplest start — configure via the web UI:**

```bash
docker run --rm -p 127.0.0.1:5001:5000 \
  -v $(pwd)/config:/app/config \
  ghcr.io/dhis2/tool-dq-workbench:latest
```

Open http://localhost:5001 — you will be taken straight to the server setup page.
Your credentials are saved to `./config/config.yml` for future runs.

**Or pass credentials directly:**

```bash
docker run --rm -p 127.0.0.1:5001:5000 \
  -e DHIS2_BASE_URL=https://your-dhis2-instance.org \
  -e DHIS2_API_TOKEN=d2p_your_token_here \
  -v $(pwd)/config:/app/config \
  ghcr.io/dhis2/tool-dq-workbench:latest
```

**Local DHIS2 (also running in Docker):**

```bash
docker run --rm -p 127.0.0.1:5001:5000 \
  --add-host=host.docker.internal:host-gateway \
  -e DHIS2_BASE_URL=http://host.docker.internal:8080 \
  -e DHIS2_API_TOKEN=d2p_your_token_here \
  -v $(pwd)/config:/app/config \
  ghcr.io/dhis2/tool-dq-workbench:latest
```

> **macOS/Windows:** `--add-host` is not needed — `host.docker.internal` works out of the box.

**Local DHIS2 (running directly on Linux, not in Docker):**

```bash
docker run --rm --network host \
  -e DHIS2_BASE_URL=http://localhost:8080 \
  -e DHIS2_API_TOKEN=d2p_your_token_here \
  -v $(pwd)/config:/app/config \
  ghcr.io/dhis2/tool-dq-workbench:latest
```

The web UI will be available at http://localhost:5000 when using `--network host`.

> **Note:** The web UI has no built-in authentication. Only run it on localhost or
> a trusted network, and stop it when you are done.

## How it works

The workbench has two components:

- **Web UI** — use it to create and edit your `config.yml`, then stop it.
- **CLI** (`dq-monitor`) — run this on a schedule (e.g. daily via cron) to collect
  data quality snapshots and post them to DHIS2.

A typical workflow:
1. A data manager runs the Web UI to build a `config.yml`.
2. The `config.yml` is handed to a system administrator.
3. The administrator schedules `dq-monitor --config config.yml` to run daily.

## Running the CLI

Once you have a `config.yml`, run the CLI directly (recommended for scheduled use):

```bash
pip install git+https://github.com/dhis2/tool-dq-workbench.git
dq-monitor --config config/my_config.yml
```

Or via Docker:

```bash
docker compose run --rm cli
```

## Documentation

Full documentation is published at **https://dhis2.github.io/tool-dq-workbench/**.

To build it locally:

```bash
cd docs && make html
```
