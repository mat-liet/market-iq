# Deploying to a server

`docker-compose.prod.yml` runs the whole stack on one Linux server (a small Hetzner
Cloud VM is plenty: 2 vCPU / 4 GB RAM). The setup:

- **Caddy** is the only service with a published port (80/443). It gets and renews
  an HTTPS certificate automatically, asks for the dashboard password, and proxies to
  the frontend. The frontend then proxies the API.
- **Postgres and the API have no published ports.** They can only be reached from
  other containers on the same server.
- **Data lives in named volumes** (`pgdata`, `caddy_data`), so the data survives
  container rebuilds and `docker compose down`. It only goes if you run `down -v`.
- **Every service restarts on its own** (`restart: unless-stopped`), including after
  a server reboot. Container logs rotate.

## 1. Server, firewall, DNS

1. Create an Ubuntu 24.04 server and add your SSH key.
2. Attach a firewall that allows inbound TCP **22, 80, 443** only.
3. Point a hostname at the server's IPv4 with a DNS `A` record, e.g.
   `narratives.example.com`. If you have no domain, `<ip-with-dashes>.sslip.io`
   (e.g. `203-0-113-10.sslip.io`) resolves to that IP and works with Caddy's
   automatic HTTPS.

## 2. Install Docker and get the code

```bash
ssh root@<server-ip>
curl -fsSL https://get.docker.com | sh
git clone https://github.com/<owner>/market-iq.git /opt/market-iq
cd /opt/market-iq
```

## 3. Configuration

The feed list, the taxonomy and `.env` are not in the repository. Copy your feeds and
taxonomy over from your machine:

```bash
# run locally, from the repo
scp config/feeds.json config/taxonomy.json root@<server-ip>:/opt/market-iq/config/
```

On the server, create `.env` from the example and fill in the production section:

```bash
cp .env.example .env
docker run --rm caddy:2.8 caddy hash-password --plaintext 'choose-a-password'
nano .env
```

```dotenv
DATABASE_URL=postgresql://market:<db-password>@postgres:5432/market_narrative
ANTHROPIC_API_KEY=<your key>
CLAUDE_MODEL=claude-sonnet-5
CLAUDE_EFFORT=low
POSTGRES_PASSWORD=<db-password>
SITE_ADDRESS=narratives.example.com
DASHBOARD_USER=admin
DASHBOARD_PASSWORD_HASH='<hash from the command above>'
```

Keep the single quotes around the hash. It contains `$`, and Compose would expand
it otherwise. `POSTGRES_PASSWORD` only takes effect the first time the database
volume is created. To change it later, change it inside Postgres too.

## 4. Check the feeds, then start

```bash
docker compose -f docker-compose.prod.yml run --rm app python -m scripts.check_feeds
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml logs -f app   # Ctrl-C to stop following
```

Open `https://<SITE_ADDRESS>` and sign in with the dashboard user.

On the first run, ingestion picks up everything currently in the feeds (several
hundred articles). Classification works through that backlog at 10 articles every 15
minutes, so it catches up within about a day. After that it keeps pace with new
articles.

## 5. Backups

`deploy/backup.sh` writes a compressed `pg_dump` to `backups/` and keeps the last 14
dumps. Schedule it daily:

```bash
crontab -e
# add:
0 3 * * * cd /opt/market-iq && ./deploy/backup.sh >> backups/backup.log 2>&1
```

Copy dumps off the server now and then (`scp root@<server-ip>:/opt/market-iq/backups/*.gz .`).
Hetzner's own server backups are a cheap second layer. To restore:

```bash
gunzip -c backups/<file>.sql.gz | docker compose -f docker-compose.prod.yml exec -T postgres psql -U market market_narrative
```

## Day-to-day

| Task | Command (from `/opt/market-iq`) |
|---|---|
| Follow logs | `docker compose -f docker-compose.prod.yml logs -f app` |
| Change feeds or taxonomy | edit `config/*.json`, then `docker compose -f docker-compose.prod.yml restart app` |
| Deploy new code | `git pull && docker compose -f docker-compose.prod.yml up -d --build` |
| Spot-check classifications | `docker compose -f docker-compose.prod.yml exec app python -m scripts.review_classifications` |
| Stop (data kept) | `docker compose -f docker-compose.prod.yml down` |

## Cost control

Classification is billed per token. Set a monthly spend limit for the API key's
workspace in the Claude Console, and check its usage page after the first day. At
that point the backlog has been processed and the daily rate is representative.
