#!/usr/bin/env bash
# Dump the database to backups/ and keep the most recent 14 dumps.
# Schedule daily from the repo directory, e.g. in crontab:
#   0 3 * * * cd /opt/market-iq && ./deploy/backup.sh >> backups/backup.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p backups
file="backups/market_narrative_$(date +%Y%m%d_%H%M%S).sql.gz"
docker compose -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U market market_narrative | gzip > "$file"
ls -1t backups/market_narrative_*.sql.gz | tail -n +15 | xargs -r rm --
echo "wrote $file"
