# Market Narrative Intelligence Platform — CI/CD Pipeline

## Overview

CI/CD is handled by **GitHub Actions** deploying to a **Hetzner or Oracle Cloud VPS** over SSH. The pipeline runs tests on every push, and deploys only when changes land on `main`.

```
GitHub repo
   │ push / PR
   ▼
GitHub Actions
   │
   ├─ CI: run tests (every push & PR)
   │
   └─ CD: deploy to VPS (only on push to main, only if tests pass)
        │ SSH into server
        │ git pull
        │ docker compose up -d --build
        │ alembic upgrade head
        ▼
   Hetzner / Oracle VPS  →  app running
```

**Cost:** Free. GitHub Actions provides 2,000 minutes/month on the free tier; this project uses a small fraction of that.

---

## Required GitHub Secrets

Set under: repo **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Purpose |
|---|---|
| `SSH_PRIVATE_KEY` | Private key for SSH access to the VPS |
| `VPS_HOST` | Server IP address or hostname |
| `VPS_USER` | SSH username (e.g. `deploy`) |

> `ANTHROPIC_API_KEY` and `DATABASE_URL` are **not** GitHub secrets. They live in a `.env` file on the server itself, read by Docker Compose at runtime. This keeps API credentials off the CI platform and avoids re-injecting them on every deploy.

---

## SSH Key Setup

Generate a dedicated deploy key (do this once, locally):

```bash
# Generate a keypair specifically for deployment
ssh-keygen -t ed25519 -f deploy_key -C "github-actions-deploy" -N ""

# Copy the PUBLIC key to the server's authorized_keys
ssh-copy-id -i deploy_key.pub deploy@your-vps-ip
# (or manually append deploy_key.pub to ~/.ssh/authorized_keys on the server)

# Copy the PRIVATE key contents into the GitHub secret SSH_PRIVATE_KEY
cat deploy_key
```

> Use a dedicated key for deployment, not your personal SSH key. If it's ever compromised, you can revoke just this one.

---

## Workflow File

Save as `.github/workflows/deploy.yml` in the repo root.

```yaml
name: CI/CD

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  # ───────────────────────────────────────────────
  # CI: Run tests on every push and pull request
  # ───────────────────────────────────────────────
  test:
    runs-on: ubuntu-latest

    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
          POSTGRES_DB: test_market_narrative
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install pytest

      - name: Run migrations against test DB
        env:
          DATABASE_URL: postgresql://test:test@localhost:5432/test_market_narrative
        run: alembic upgrade head

      - name: Run tests
        env:
          DATABASE_URL: postgresql://test:test@localhost:5432/test_market_narrative
          ANTHROPIC_API_KEY: dummy-key-for-tests
        run: pytest -v

  # ───────────────────────────────────────────────
  # CD: Deploy to VPS — only on push to main,
  #     and only if the test job passed
  # ───────────────────────────────────────────────
  deploy:
    needs: test
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'

    steps:
      - name: Deploy to VPS over SSH
        uses: appleboy/ssh-action@v1.0.3
        with:
          host: ${{ secrets.VPS_HOST }}
          username: ${{ secrets.VPS_USER }}
          key: ${{ secrets.SSH_PRIVATE_KEY }}
          script: |
            set -e
            cd /app
            git pull origin main
            docker compose up -d --build
            docker compose exec -T app alembic upgrade head
            docker image prune -f
```

---

## Workflow Explained

### Trigger rules

```yaml
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
```

Tests run on pushes to `main` **and** on pull requests targeting `main`. Deployment is gated separately (see below), so PRs run tests without deploying.

### The test job

- Spins up a **throwaway PostgreSQL 15 container** as a service, so tests run against a real database, not mocks.
- The `health-cmd` block ensures the test steps wait until Postgres is actually ready before running.
- Runs Alembic migrations first, then pytest — this also validates that your migrations apply cleanly to a fresh database, which catches a whole class of bugs.
- `ANTHROPIC_API_KEY` is a dummy value here — your tests should mock the Claude API rather than make real calls. (Real API calls in CI are slow, flaky, and cost money.)

### The deploy job

```yaml
needs: test
if: github.ref == 'refs/heads/main' && github.event_name == 'push'
```

- `needs: test` — deployment only runs if the test job passed. Broken code never reaches the server.
- The `if` condition — deploys only on a direct push to `main`, never on a pull request. A PR runs tests for safety but doesn't touch production.

### The deploy script

```bash
set -e                                          # stop on first error
cd /app
git pull origin main                            # fetch latest code
docker compose up -d --build                    # rebuild and restart containers
docker compose exec -T app alembic upgrade head # apply DB migrations
docker image prune -f                           # clean up old images to save disk
```

- `set -e` ensures a failure at any step aborts the deploy rather than leaving a half-updated server.
- `alembic upgrade head` ships schema changes alongside code, so a new column and the code expecting it arrive together.
- `docker image prune -f` matters on a small VPS — old image layers accumulate and fill the disk over time.

---

## One-Time Server Preparation

Before the first automated deploy, set the server up manually once:

```bash
# SSH into the VPS
ssh deploy@your-vps-ip

# Install Docker and Compose (Ubuntu)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # log out and back in after this

# Clone the repo to the expected path
sudo mkdir -p /app
sudo chown $USER:$USER /app
git clone https://github.com/your-username/market-narrative.git /app
cd /app

# Create the .env file with real secrets (never committed to git)
cat > .env << 'EOF'
ANTHROPIC_API_KEY=your_real_claude_api_key
DATABASE_URL=postgresql://user:password@postgres:5432/market_narrative
EOF

# First manual launch to confirm everything works
docker compose up -d --build
docker compose exec -T app alembic upgrade head
```

After this, every push to `main` deploys automatically.

---

## Oracle Cloud (ARM) Note

If using Oracle's Always Free tier, the instances are **ARM64** (Ampere), not x86. Two adjustments:

1. **Base images must support ARM.** Most official images (`python`, `postgres`, etc.) are multi-arch and work automatically. If you pin an x86-only image, the build will fail.

2. **Building on the server works fine** — since `docker compose up --build` runs on the ARM server itself, it builds ARM images natively. No cross-compilation needed with this SSH-based approach.

> If you later switch to building images in GitHub Actions and pushing to a registry, you'd need `docker buildx` for multi-arch builds. With the build-on-server approach in this workflow, that complexity doesn't apply.

Hetzner is x86 and has none of these considerations.

---

## Recommended Repo Structure Additions

```
market-narrative/
├── .github/
│   └── workflows/
│       └── deploy.yml          # the workflow above
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env                        # on server only — gitignored
├── .gitignore                  # must include .env
├── alembic/
└── app/
```

Make sure `.gitignore` contains:

```
.env
deploy_key
deploy_key.pub
__pycache__/
*.pyc
```

---

## Pipeline Behaviour Summary

| Event | Tests run? | Deploys? |
|---|---|---|
| Push to a feature branch | No | No |
| Pull request to `main` | Yes | No |
| Push / merge to `main` | Yes | Yes (if tests pass) |
| Tests fail on `main` push | Yes | No — deploy blocked |

---

## Future Enhancements (Not Phase 1)

- **Build images in Actions → push to `ghcr.io`** (GitHub Container Registry, free) instead of building on the server. Frees the VPS from build load. Needs `docker buildx` if targeting Oracle ARM.
- **Slack / email notification** on deploy success or failure.
- **Staging environment** — a second VPS that `develop` branch deploys to, before promoting to `main`.
- **Health check after deploy** — curl the `/health` endpoint and roll back if it fails.
- **Self-hosted deploy platform (Coolify)** — push-to-deploy with a web UI, if you outgrow the hand-written workflow.
