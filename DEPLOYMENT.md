# Deploying to a TierHive VPS (nd-media.top)

## 0. Before you deploy: rotate exposed secrets

Two secrets used by this project have already been committed to git history
at some point (visible to anyone with repo access, and permanently in
history even after being removed from the current file):

- The Supabase database password (two different ones, from two different
  points in this project's history).

Rotate the Supabase DB password from the Supabase dashboard
(Project Settings -> Database -> Reset database password) and update
`DATABASE_URL` in your `.env` everywhere it's used once you do. The Telegram
bot token is fine to leave as-is since it was never committed to git - just
don't paste it anywhere else.

## 1. Point the domain at the VPS

Once TierHive gives you the VPS's public IP, go to nd-media.top's registrar
DNS settings and add:

| Type | Name | Value          |
|------|------|----------------|
| A    | @    | <VPS_IP>       |
| A    | www  | <VPS_IP>       |

DNS can take a few minutes to a few hours to propagate.

## 2. Base server setup (Ubuntu 22.04/24.04)

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-venv python3-pip nginx git ufw

sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
```

## 3. Get the code onto the server

```bash
sudo mkdir -p /var/www/after-dark
sudo chown $USER:$USER /var/www/after-dark
git clone https://github.com/thecodeguy-eng/after-dark.git /var/www/after-dark
cd /var/www/after-dark

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 4. Create the production `.env`

Copy `.env.example` to `.env` on the server and fill in real values:

```bash
cp .env.example .env
nano .env
```

```
DATABASE_URL=postgresql://afterdark:<db-password>@127.0.0.1:5432/afterdark
TELEGRAM_BOT_TOKEN=<token from @BotFather>
TELEGRAM_CHANNEL_ID=-1002276869264
SECRET_KEY=<generate: python -c "from django.core.management.utils import get_random_secret_key as g; print(g())">
DEBUG=False
```

Never paste real secrets into this file - it's committed to git.

## 5. Migrate and collect static files

```bash
python manage.py migrate
python manage.py collectstatic --noinput
```

## 6. Gunicorn as a systemd service

`/etc/systemd/system/afterdark.service`:

```ini
[Unit]
Description=After Dark Gunicorn daemon
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/after-dark
EnvironmentFile=/var/www/after-dark/.env
ExecStart=/var/www/after-dark/venv/bin/gunicorn \
    --workers 3 \
    --bind unix:/var/www/after-dark/afterdark.sock \
    bangxxx.wsgi:application
# Without this, an OOM-kill (or any crash) leaves the site down until someone
# notices and restarts it by hand - which is exactly what happened once.
Restart=on-failure
RestartSec=5
# Headroom against any future file-descriptor leak (default is often 1024,
# which a leaking connection pool can exhaust under real traffic).
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

```bash
sudo chown -R www-data:www-data /var/www/after-dark
sudo systemctl daemon-reload
sudo systemctl enable --now afterdark
sudo systemctl status afterdark
```

## 7. Nginx reverse proxy

`/etc/nginx/sites-available/afterdark`:

```nginx
server {
    listen 80;
    server_name nd-media.top www.nd-media.top;

    location /static/ {
        alias /var/www/after-dark/staticfiles/;
    }

    location / {
        proxy_pass http://unix:/var/www/after-dark/afterdark.sock;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/afterdark /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

At this point `http://nd-media.top` should load the site.

## 8. HTTPS via Certbot

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d nd-media.top -d www.nd-media.top
```

Certbot edits the nginx config to add the SSL block and sets up
auto-renewal.

## 9. Cron: scraping and Telegram posting

```bash
crontab -e
```

```cron
# Nightly scrape across all categories (AI excluded). Note: no positional
# page args here - a bare number is read as a category slug and 404s.
0 3 * * * cd /var/www/after-dark && venv/bin/python manage.py scrape_xvideos --limit 300 >> /var/log/afterdark-scrape.log 2>&1

# Naija is the homepage's lead section and the only thing posted to Telegram
30 3 * * * cd /var/www/after-dark && venv/bin/python manage.py scrape_xvideos --search naija --limit 50 >> /var/log/afterdark-scrape.log 2>&1

# Telegram: 5 Naija link posts/day, no videos, every 4h48m around the clock.
00 00 * * * cd /var/www/after-dark && venv/bin/python manage.py post_telegram --type link >> /var/log/afterdark-telegram.log 2>&1
48 04 * * * cd /var/www/after-dark && venv/bin/python manage.py post_telegram --type link >> /var/log/afterdark-telegram.log 2>&1
36 09 * * * cd /var/www/after-dark && venv/bin/python manage.py post_telegram --type link >> /var/log/afterdark-telegram.log 2>&1
24 14 * * * cd /var/www/after-dark && venv/bin/python manage.py post_telegram --type link >> /var/log/afterdark-telegram.log 2>&1
12 19 * * * cd /var/www/after-dark && venv/bin/python manage.py post_telegram --type link >> /var/log/afterdark-telegram.log 2>&1
```

## 10. Deploying updates later

```bash
cd /var/www/after-dark
git pull
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
sudo systemctl restart afterdark
```
