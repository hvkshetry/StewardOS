# Family Office Mail Ingress

Remote ingress service for home-server.

## What it does
- Receives Gmail Pub/Sub push notifications at `POST /webhooks/gmail`
- Acknowledges quickly
- Forwards payloads to worker webhook URL with shared-secret header
- Optionally verifies Pub/Sub push JWTs when `PUBSUB_AUDIENCE` is configured

## Ports
- Default bind: `127.0.0.1:8311`

## Setup on home-server
```bash
cd ~/personal/agents/family-office-mail-ingress
python3 -m venv .venv
.venv/bin/pip install -e .
cp .env.example .env
```

Set the ingress `.env` values:

```bash
SERVICE_HOST=127.0.0.1
SERVICE_PORT=8311
WORKER_WEBHOOK_URL=http://127.0.0.1:18312/internal/family-office/gmail
WORKER_SHARED_SECRET=<same-value-as-worker>
LOG_LEVEL=INFO
PUBSUB_AUDIENCE=https://agent-mail.stewardos.example.com/webhooks/gmail
PUBSUB_SERVICE_ACCOUNT_EMAIL=pubsub-push-ingress@stewardos-gcp-project.iam.gserviceaccount.com
```

`PUBSUB_AUDIENCE` enables Google-signed Pub/Sub push JWT verification. `PUBSUB_SERVICE_ACCOUNT_EMAIL`
locks the accepted token identity to the service account configured on the push subscription.

## systemd
```bash
sudo cp family-office-mail-ingress.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now family-office-mail-ingress
sudo systemctl status family-office-mail-ingress --no-pager
```

## Authenticated Pub/Sub Push

The live subscription is `projects/stewardos-gcp-project/subscriptions/family-gmail-push`.

Configure push auth with a dedicated service account:

```bash
gcloud iam service-accounts create pubsub-push-ingress \
  --project=stewardos-gcp-project \
  --display-name="Pub/Sub push ingress"

gcloud iam service-accounts add-iam-policy-binding \
  pubsub-push-ingress@stewardos-gcp-project.iam.gserviceaccount.com \
  --project=stewardos-gcp-project \
  --member="user:principal@example.com" \
  --role="roles/iam.serviceAccountUser"

gcloud projects add-iam-policy-binding stewardos-gcp-project \
  --member="serviceAccount:service-000000000000@gcp-sa-pubsub.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountTokenCreator"

gcloud pubsub subscriptions update family-gmail-push \
  --project=stewardos-gcp-project \
  --push-endpoint=https://agent-mail.stewardos.example.com/webhooks/gmail \
  --push-auth-service-account=pubsub-push-ingress@stewardos-gcp-project.iam.gserviceaccount.com \
  --push-auth-token-audience=https://agent-mail.stewardos.example.com/webhooks/gmail
```
