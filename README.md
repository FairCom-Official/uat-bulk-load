# Bulk Load Benchmark: FairCom Edge vs MariaDB

This tool measures how fast the same batch of data loads into two different
databases and shows the results next to each other.

- MariaDB loads the data using its built-in `LOAD DATA LOCAL INFILE` command.
- FairCom Edge loads the same data using its REST API (the `insertRecords`
  action), because FairCom is API-first and has no equivalent bulk-file command.

Both databases run in Docker on your own machine and load the identical file, so
the comparison is fair.

You don't need to know SQL, Python, or how either database works. If you can copy
and paste one command, you can run this.

## Before you start (one-time setup)

You need three things installed. If you already have them, skip ahead.

1. Docker Desktop, which runs the two databases. Download it from
   https://www.docker.com/products/docker-desktop/. After installing, open
   Docker Desktop and wait until it says "Running."
2. Python 3, which runs the loader scripts. Check by typing `python3 --version`
   in a terminal. If you get a version number, you're good. If not, install it
   from https://www.python.org/downloads/.
3. This project folder on your computer (you already have it).

You do not need to create a Python virtual environment. This tool uses your
system Python directly.

## How to run it

1. Open the Terminal app.
2. Go into this project folder. For example:
   ```bash
   cd ~/Desktop/work_git/bulk-load
   ```
3. Run this one command:
   ```bash
   ./run.sh
   ```

That single command does everything for you:

- installs the small Python helpers it needs,
- starts both databases in Docker,
- waits until they're ready,
- generates the sample data,
- runs the benchmark, and
- prints the results reports.

When it finishes, stop the databases with:

```bash
docker compose down
```

## What you will see

You get two reports.

### 1. The head-to-head result

```
==============================================================================
  BULK LOAD BENCHMARK RESULTS
==============================================================================
  MariaDB (LOAD DATA LOCAL INFILE)          300,000 rows      0.47s       633,472 rows/sec
  FairCom Edge (JSON insertRecords)         300,000 rows      5.23s        57,372 rows/sec
==============================================================================

  MariaDB finished 11.0x faster on this run.
```

- rows: how many records were loaded (the same for both).
- seconds: how long the load took.
- rows/sec: speed (higher is faster).

### 2. The FairCom diagnostics report

This second report helps the engineering team understand where FairCom spends
its time when loading over the REST API, so the loading process can be improved.
It breaks the load into phases and shows per-request timing:

```
  PHASE BREAKDOWN (wall-clock)
  1. setup (session+DDL)       0.078          1.4%
  2. read CSV                  0.214          3.9%
  3. insert (REST)             5.208         94.7%

  PER-REQUEST LATENCY (insertRecords round-trip)
         min      median         p95         max        mean
    266.1 ms    329.3 ms    376.2 ms    411.9 ms    333.3 ms

  CLIENT vs NETWORK
  JSON build (client CPU)          0.181s       0.9%
  round-trip (net+server)         19.997s      99.1%
```

In plain terms, almost all the time is the server processing each request, not
the network or the Python code. That tells engineering where to focus.

## Changing the settings

All settings live in a file called `.env` that ships with the project. Open it in
any text editor and change the values.

| Setting | What it does | Default |
| ------------------- | ------------------------------------------------------ | ------- |
| `ROW_COUNT` | How many rows of data to load into both databases. | 100000 |
| `FAIRCOM_BATCH_SIZE`| How many rows FairCom sends per REST request. | 5000 |
| `FAIRCOM_WORKERS` | How many requests FairCom sends at once (in parallel). | 4 |
| `MARIADB_PORT` | The port MariaDB listens on (change if 3306 is taken). | 3306 |

After changing `.env`, run `./run.sh` again. If you change `ROW_COUNT`, the tool
regenerates the data file to match.

## Running pieces individually (optional)

If you only want one part, you can run these directly after the databases are up
(`docker compose up -d`):

| Command | What it does |
| ----------------------------------------- | --------------------------------------------------- |
| `python3 scripts/benchmark.py` | The head-to-head comparison (both databases). |
| `python3 scripts/load_mariadb.py` | Load MariaDB only. |
| `python3 scripts/load_faircom.py` | Load FairCom only. |
| `python3 scripts/diagnose_faircom.py` | The detailed FairCom timing report. |
| `python3 scripts/sweep_faircom.py` | Try several batch sizes, report the fastest. |
| `python3 scripts/sweep_faircom_workers.py`| Try several parallel-request counts, report fastest.|

The two `sweep_*` scripts accept custom values, for example
`python3 scripts/sweep_faircom_workers.py 1 2 4 8`.

## Good to know

- FairCom evaluation license: the FairCom Edge container runs for 3 hours at a
  time on the free evaluation license. If a run fails because FairCom stopped,
  restart it with `docker compose up -d faircom-edge` and try again.
- FairCom login: the REST API is at `http://localhost:8080/api`, with
  username/password `ADMIN` / `ADMIN`.
- MariaDB image: by default this uses the public `mariadb:11.8` image so it works
  out of the box. To use the production
  [Docker Hardened Image (DHI)](https://hub.docker.com/hardened-images/catalog/dhi/mariadb)
  instead, set `MARIADB_IMAGE=<your-namespace>/dhi-mariadb:12.3` in `.env`.

## Project layout

```
run.sh                       One command to run everything
docker-compose.yml           Defines the two databases (FairCom + MariaDB)
.env                         All settings (rows, batch size, workers, ports)
requirements.txt             The small Python helpers this tool installs
sql/mariadb_schema.sql       The table definition for MariaDB
data/sample.csv              The generated sample data (created on first run)
scripts/
  generate_data.py           Creates the shared sample data file
  load_mariadb.py            Loads MariaDB via LOAD DATA LOCAL INFILE
  load_faircom.py            Loads FairCom via the REST insertRecords API
  benchmark.py               Runs both and prints the comparison
  diagnose_faircom.py        Detailed FairCom timing report (for engineering)
  sweep_faircom.py           Finds the best FairCom batch size
  sweep_faircom_workers.py   Finds the best FairCom parallel-request count
  config.py / progress.py    Shared internals
```
