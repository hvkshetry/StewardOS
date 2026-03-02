# Family Office Mail Ingress

Remote ingress service for HP ENVY.

## What it does
- Receives Gmail Pub/Sub push notifications at `POST /webhooks/gmail`
- Acknowledges quickly
- Forwards payloads to worker webhook URL with shared-secret header

## Ports
- Default bind: `127.0.0.1:8311`

## Setup on HP ENVY
```bash
cd ~/personal/agents/family-office-mail-ingress
python3 -m venv .venv
.venv/bin/pip install -e .
cp .env.example .env
```

## systemd
```bash
sudo cp family-office-mail-ingress.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now family-office-mail-ingress
sudo systemctl status family-office-mail-ingress --no-pager
```
