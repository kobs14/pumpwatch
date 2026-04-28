# Deployment — Hetzner Cloud + docker-compose + Caddy

This guide deploys PumpWatch to a single Hetzner CX22 VPS (~€4.51/mo,
2 vCPU, 4 GB RAM, 20 TB traffic). The stack is the same `docker-compose.yml`
that runs locally, fronted by Caddy for automatic HTTPS. Postgres and
Redis run on the same box; the scheduler is single-instance by design,
so a single VPS is the right shape until volume forces a tier upgrade.

Why Hetzner: predictable flat cost, no metering surprises, and the
existing compose file works unchanged. Other platforms (Fly.io, Railway,
Render) are viable; their commands differ but the env-var contract is
identical.

> **Read-only deployment.** PumpWatch never holds private keys, never
> trades, and never sends financial advice. The bot's `/help` text says
> so; the README does too. Don't deploy this with the framing of an
> investment tool.

## 0. Prerequisites

- Hetzner Cloud account (or any VPS host that gives you a public IPv4
  + Ubuntu 24.04). Sign-up requires a credit card.
- A domain name with DNS you control. The bot's webhook needs an
  HTTPS URL; Caddy will fetch a Let's Encrypt cert at first boot.
- An SSH keypair on your local machine. Add the public key to your
  Hetzner account before provisioning.
- A Telegram bot token from [@BotFather](https://t.me/BotFather).
- Optional: `hcloud` CLI installed locally
  (`brew install hcloud` / `apt install hcloud`).
- The repo cloned and `docker compose up -d` already working locally.

## 1. Provision the server

Either via the Hetzner Cloud Console (click-ops) or:

```bash
hcloud server create \
  --name pumpwatch \
  --type cx22 \
  --image ubuntu-24.04 \
  --ssh-key "$(hcloud ssh-key list -o noheader -o columns=name | head -1)" \
  --location nbg1
```

Note the public IPv4 from `hcloud server list`. Point your domain
(e.g. `bot.example.com`) at it via an `A` record before continuing —
Caddy needs DNS to resolve before it can fetch a cert.

## 2. Initial hardening

SSH in as `root`, then create a sudo user and disable root password
login:

```bash
ssh root@<server-ip>

# Create a sudo user
adduser --gecos "" pumpwatch
usermod -aG sudo pumpwatch
mkdir -p /home/pumpwatch/.ssh
cp /root/.ssh/authorized_keys /home/pumpwatch/.ssh/
chown -R pumpwatch:pumpwatch /home/pumpwatch/.ssh
chmod 700 /home/pumpwatch/.ssh
chmod 600 /home/pumpwatch/.ssh/authorized_keys

# Disable root SSH and password auth
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart ssh

# Firewall
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# Unattended security updates
apt update && apt -y install unattended-upgrades fail2ban
dpkg-reconfigure -f noninteractive unattended-upgrades
systemctl enable --now fail2ban
```

Log out and back in as `pumpwatch@<server-ip>` to verify.

## 3. Install Docker

As `pumpwatch`:

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# Re-login or run `newgrp docker` so the group takes effect.
docker version
docker compose version
```

## 4. Pull the repo + secrets

```bash
cd ~
git clone https://github.com/<your-handle>/pumpwatch.git
cd pumpwatch

cp .env.example .env
# Edit .env. The deploy-only fields (compared to dev):
#   ENVIRONMENT=prod
#   BOT_MODE=webhook
#   BOT_WEBHOOK_URL=https://bot.example.com   (no trailing slash)
#   BOT_WEBHOOK_SECRET_TOKEN=<generate; 1–256 chars [A-Za-z0-9_-]>
#   TELEGRAM_BOT_TOKEN=<from @BotFather>
# Compose overrides DATABASE_URL/REDIS_URL via the per-service `environment:`
# block, so the localhost values from the template are fine.
nano .env
chmod 600 .env
```

`.env` lives only on the server. **Never commit it.**

Generate a strong webhook secret:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

## 5. Caddy reverse proxy

Caddy fronts the bot's webhook port and (optionally) Grafana. It
auto-fetches Let's Encrypt certs.

Install Caddy on the host (not in compose — it needs to listen on 80
and 443 directly):

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | \
  sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | \
  sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy
```

Replace `/etc/caddy/Caddyfile` with:

```caddy
bot.example.com {
    # Webhook receiver. Telegram POSTs to /<bot-token>; Caddy proxies
    # to the bot container's port (BOT_WEBHOOK_PORT, default 8443).
    reverse_proxy localhost:8443
}

# Optional: protected Grafana behind basic-auth. Skip this block if
# you prefer the SSH-tunnel access pattern below.
# grafana.example.com {
#     basicauth {
#         admin <bcrypt-hash>
#     }
#     reverse_proxy localhost:3000
# }
```

Generate the basic-auth hash with `caddy hash-password`. Reload:

```bash
sudo systemctl reload caddy
```

The bot container's webhook port must be host-bound for Caddy to reach
it. Add an override at `~/pumpwatch/docker-compose.override.yml` (this
file is *.gitignore*-d in the dev workflow but you create it locally
on the server):

```yaml
services:
  bot:
    ports:
      - "127.0.0.1:8443:8443"
```

Binding to `127.0.0.1` keeps the bot port off the public internet —
only Caddy can reach it.

## 6. First boot

Bring up the dependencies, run migrations, then everything else:

```bash
cd ~/pumpwatch
docker compose up -d postgres redis
# Wait for healthchecks to pass:
docker compose ps

# Run migrations once before the long-running services.
docker compose run --rm bot alembic upgrade head

docker compose up -d bot scheduler worker alerts
docker compose logs -f bot
```

You should see `bot.webhook.starting` and (after Telegram's first POST)
PTB processing updates.

## 7. Tell Telegram about the webhook

```bash
TOKEN=$(grep ^TELEGRAM_BOT_TOKEN .env | cut -d= -f2-)
SECRET=$(grep ^BOT_WEBHOOK_SECRET_TOKEN .env | cut -d= -f2-)
URL=$(grep ^BOT_WEBHOOK_URL .env | cut -d= -f2-)

curl -s "https://api.telegram.org/bot${TOKEN}/setWebhook" \
  --data-urlencode "url=${URL}/${TOKEN}" \
  --data-urlencode "secret_token=${SECRET}"

# Verify
curl -s "https://api.telegram.org/bot${TOKEN}/getWebhookInfo" | jq
```

`getWebhookInfo` should show your URL with `pending_update_count: 0`.

## 8. Observability access (do NOT expose publicly)

The opt-in stack:

```bash
docker compose --profile observability up -d
```

Prometheus binds to `:9090`, Grafana to `:3000`. **Do not expose either
to the public internet.** Two safe options:

### Option A — SSH tunnel (simplest)

From your laptop:

```bash
ssh -L 3000:localhost:3000 -L 9090:localhost:9090 pumpwatch@bot.example.com
# In a browser: http://localhost:3000 (Grafana, anonymous Viewer)
#               http://localhost:9090 (Prometheus)
```

### Option B — Caddy basic-auth subdomain

Uncomment the Grafana block in the Caddyfile (Step 5), set DNS for
`grafana.example.com`, generate a bcrypt password, reload Caddy. Same
for Prometheus on a different subdomain if needed. **Pick a non-obvious
subdomain** to reduce drive-by scans.

In production, also bind those compose service ports to localhost only:

```yaml
# docker-compose.override.yml
services:
  prometheus:
    ports:
      - "127.0.0.1:9090:9090"
  grafana:
    ports:
      - "127.0.0.1:3000:3000"
```

## 9. Backups

Hetzner snapshots are €1.20/mo and capture the whole disk. Enable in
the Cloud Console under the server's "Backups" tab. For finer-grained
DB backups, a daily `pg_dump`:

```bash
sudo mkdir -p /var/backups/pumpwatch
sudo chown pumpwatch:pumpwatch /var/backups/pumpwatch

cat > /home/pumpwatch/pg_backup.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
TS=$(date -u +%Y%m%dT%H%M%SZ)
cd /home/pumpwatch/pumpwatch
docker compose exec -T postgres pg_dump -U pumpwatch -d pumpwatch \
  | gzip -9 > /var/backups/pumpwatch/pumpwatch-${TS}.sql.gz
# Retain 14 days
find /var/backups/pumpwatch -name 'pumpwatch-*.sql.gz' -mtime +14 -delete
EOF
chmod +x /home/pumpwatch/pg_backup.sh
```

Schedule daily at 03:30 UTC via systemd:

```bash
sudo tee /etc/systemd/system/pumpwatch-backup.service <<'EOF'
[Unit]
Description=PumpWatch nightly pg_dump
[Service]
Type=oneshot
User=pumpwatch
ExecStart=/home/pumpwatch/pg_backup.sh
EOF

sudo tee /etc/systemd/system/pumpwatch-backup.timer <<'EOF'
[Unit]
Description=Run PumpWatch backup nightly
[Timer]
OnCalendar=*-*-* 03:30:00 UTC
Persistent=true
[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now pumpwatch-backup.timer
```

Periodically copy `/var/backups/pumpwatch/` somewhere off-box (rclone,
borg, S3-compatible object storage). On-host backups don't survive a
host compromise.

## 10. Updates

Pull the latest, rebuild only the app images, and restart:

```bash
cd ~/pumpwatch
git pull --ff-only
docker compose pull            # base images
docker compose build bot scheduler worker alerts
docker compose up -d --no-deps bot scheduler worker alerts

# If a migration shipped, run it before bringing services back up.
docker compose run --rm bot alembic upgrade head
docker compose up -d bot scheduler worker alerts
```

Beat's persistent-schedule file is `/tmp/celerybeat-schedule` inside
the scheduler container and rebuilds from `celery_app.py` on restart;
losing it across restarts is intentional.

## 11. Rollback

Schema-compatible rollback (most common):

```bash
git log --oneline -10        # find the previous SHA
git checkout <prev-sha>
docker compose build bot scheduler worker alerts
docker compose up -d --no-deps bot scheduler worker alerts
```

Schema rollback (if the previous deploy added a migration):

```bash
docker compose run --rm bot alembic downgrade -1
git checkout <prev-sha>
docker compose build bot scheduler worker alerts
docker compose up -d --no-deps bot scheduler worker alerts
```

Practice this on a staging box before relying on it. The Alembic
revisions in this repo are reversible.

## 12. Monitoring & day-to-day operations

Useful one-liners:

```bash
# Live logs
docker compose logs -f bot scheduler worker alerts

# Inspect the DLQ
docker compose exec postgres psql -U pumpwatch -d pumpwatch -c \
  "SELECT token_address, attempts, last_seen, error \
   FROM dlq_entries ORDER BY last_seen DESC LIMIT 20;"

# Recent alerts
docker compose exec postgres psql -U pumpwatch -d pumpwatch -c \
  "SELECT id, subscription_id, alert_type, delivered, delivery_error, created_at \
   FROM alerts_sent ORDER BY id DESC LIMIT 20;"

# Active dedup keys
docker compose exec redis redis-cli --scan --pattern 'pw:alert:*' | head

# Reload only one service
docker compose up -d --no-deps --build alerts

# Restart the whole stack
docker compose restart
```

The Grafana dashboard at `Dashboards → PumpWatch` covers the six
service-level metrics from [ADR-019](adr/019-prometheus-per-service.md).
Watch `pumpwatch_alerts_delivery_failed_total` and `pumpwatch_dlq_size`
for non-zero rates — both should be near zero in steady state.

## 13. Common failure modes

- **Bot logs `Conflict: terminated by other getUpdates request`.** A
  prior `BOT_MODE=polling` instance is still talking to Telegram. Either
  kill it or call `deleteWebhook` then `setWebhook` again.
- **Telegram returns `webhook is not HTTPS`.** Caddy hasn't fetched a
  cert yet — DNS may not have propagated, or the firewall blocks 80.
  `journalctl -u caddy -e` will show the ACME challenge result.
- **`celerybeat-schedule` permission denied.** The compose file already
  passes `--schedule /tmp/celerybeat-schedule`. If you see this, you've
  edited the scheduler `command:` away from the shipped value.
- **Worker `/metrics` shows zeros.** `PROMETHEUS_MULTIPROC_DIR` must be
  set in the worker container's environment (it is, in the shipped
  compose). Setting it at runtime via signal handler is too late
  (`tasks/lessons.md` Session 7).
- **Alerts fire repeatedly during testing.** Check
  `pw:alert:<user>:<token>:<type>` keys haven't been wiped on a Redis
  restart. Dev: just `redis-cli FLUSHDB`. Prod: rare, since Redis is
  persistent (AOF/RDB depending on config).

## 14. Cost summary

- Hetzner CX22: ~€4.51/mo (~$5/mo).
- Hetzner snapshots: €1.20/mo.
- Domain: typically $10–15/year.
- Telegram + Let's Encrypt: free.

Total: ~$6/mo. The lights stay on for as long as you want them to.
