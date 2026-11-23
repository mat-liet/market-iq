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

## 6. Automatic deploys

Once the server runs, every push to `main` that passes CI is deployed by the
`deploy` job in `.github/workflows/ci.yml`. The job connects over SSH and runs
`deploy/deploy.sh` with the tested commit. That script:

- refuses anything that isn't a commit on `origin/main`;
- over SSH, refuses a commit older than the one running, so a leaked key can't roll
  the server back to an older release;
- rebuilds and restarts the stack, then waits for the app's healthcheck;
- if the app doesn't become healthy within two minutes, restores the previous
  commit and fails the job. GitHub emails you when that happens.

Actions logs are public on a public repository, so the script never prints
application logs. Read them on the server. Migrations run on container start, so a
rollback doesn't undo a schema change. The nightly backups cover that case.

One-time setup, from your machine, after the first manual start (step 4):

```bash
# A key used only by GitHub Actions
ssh-keygen -t ed25519 -f ~/.ssh/market_iq_deploy -N "" -C github-actions-deploy

# Install it on the server restricted to the deploy script: no shell, no
# forwarding. Whatever command the client sends arrives as the commit argument.
echo "command=\"/opt/market-iq/deploy/deploy.sh\",restrict $(cat ~/.ssh/market_iq_deploy.pub)" \
  | ssh root@<server-ip> 'cat >> ~/.ssh/authorized_keys'

# Hand GitHub the key, the host, and the server's host key, read over your
# existing (already trusted) SSH connection rather than scanned blind
gh secret set DEPLOY_SSH_KEY < ~/.ssh/market_iq_deploy
gh variable set DEPLOY_HOST --body "<server-ip>"
gh variable set DEPLOY_KNOWN_HOSTS --body \
  "<server-ip> $(ssh root@<server-ip> cut -d' ' -f1,2 /etc/ssh/ssh_host_ed25519_key.pub)"

# Check the restriction: the first command deploys main again, the second is refused
ssh -i ~/.ssh/market_iq_deploy root@<server-ip> "$(git rev-parse origin/main)"
ssh -i ~/.ssh/market_iq_deploy root@<server-ip> ls

# GitHub holds the only copy it needs; remove the local one
rm ~/.ssh/market_iq_deploy
```

The deploy job is skipped until `DEPLOY_HOST` is set. To approve each deploy by
hand instead, add a required reviewer to the `production` environment under
**Settings → Environments**. To pause deploys, delete the `DEPLOY_HOST` variable.

## Day-to-day

| Task | Command (from `/opt/market-iq`) |
|---|---|
| Follow logs | `docker compose -f docker-compose.prod.yml logs -f app` |
| Change feeds or taxonomy | edit `config/*.json`, then `docker compose -f docker-compose.prod.yml restart app` |
| Deploy new code | automatic on merge to `main` (or by hand: `./deploy/deploy.sh`) |
| Roll back | `./deploy/deploy.sh <older-commit-sha>` (by hand only; CI only deploys forward) |
| Spot-check classifications | `docker compose -f docker-compose.prod.yml exec app python -m scripts.review_classifications` |
| Sentiment vs. stock moves | `docker compose -f docker-compose.prod.yml exec app python -m scripts.sentiment_report` |
| Stop (data kept) | `docker compose -f docker-compose.prod.yml down` |

## Cost control

Classification is billed per token. Set a monthly spend limit for the API key's
workspace in the Claude Console, and check its usage page after the first day. At
that point the backlog has been processed and the daily rate is representative.
