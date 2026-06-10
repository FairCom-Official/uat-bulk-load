#!/usr/bin/env bash
# One-command runner for the FairCom vs MariaDB bulk-load benchmark.
set -euo pipefail
cd "$(dirname "$0")"

# Silence the Docker CLI "What's next:" promotional hints.
export DOCKER_CLI_HINTS=false

# 1. Config (.env is committed with the project; nothing to create)

# 2. Python dependencies (system Python — no virtualenv)
python3 -m pip install --quiet -r requirements.txt

# 3. Start both databases
echo "Starting FairCom Edge and MariaDB containers..."
docker compose up -d

# 4. Wait for both to report healthy
echo -n "Waiting for containers to become healthy"
for _ in $(seq 1 60); do
  faircom=$(docker inspect --format='{{.State.Health.Status}}' bulkload-faircom 2>/dev/null || echo starting)
  mariadb=$(docker inspect --format='{{.State.Health.Status}}' bulkload-mariadb 2>/dev/null || echo starting)
  if [[ "$faircom" == "healthy" && "$mariadb" == "healthy" ]]; then
    echo " ok"
    break
  fi
  echo -n "."
  sleep 2
done

# 5. Run the head-to-head benchmark (MariaDB vs FairCom)
echo "Running benchmark..."
python3 scripts/benchmark.py

# 6. Run the FairCom REST load diagnostics (where does the time go?)
echo
echo "Running FairCom load diagnostics..."
python3 scripts/diagnose_faircom.py

echo
echo "Done. Stop the databases with: docker compose down"
