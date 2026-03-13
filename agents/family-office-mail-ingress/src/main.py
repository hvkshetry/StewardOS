"""home-server ingress for Gmail Pub/Sub and Plane webhooks; forwards payloads to local worker."""

import hashlib
import hmac
import logging

import httpx
from fastapi import FastAPI, HTTPException, Request
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from src.config import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Family Office Mail Ingress",
    description="Gmail and Plane webhook ingress that forwards notifications to worker",
    version="0.2.0",
)


@app.get("/health")
async def health_check():
    pubsub_audience = getattr(settings, "pubsub_audience", "")
    return {
        "status": "healthy",
        "service": "family-office-mail-ingress",
        "worker_url_configured": bool(settings.worker_webhook_url),
        "pubsub_auth_configured": bool(pubsub_audience),
        "plane_webhook_configured": bool(getattr(settings, "plane_webhook_secret", "")),
    }


def _verify_pubsub_jwt(request: Request) -> None:
    """Verify the Pub/Sub push JWT from the Authorization header."""
    pubsub_audience = getattr(settings, "pubsub_audience", "")
    pubsub_service_account_email = getattr(settings, "pubsub_service_account_email", "")

    if not pubsub_audience:
        logger.warning("pubsub_audience not configured — skipping JWT verification")
        return

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = auth_header[len("Bearer "):]
    try:
        claim = id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            audience=pubsub_audience,
        )
    except Exception as exc:
        logger.warning("JWT verification failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid JWT token")

    if pubsub_service_account_email:
        token_email = claim.get("email", "")
        if token_email != pubsub_service_account_email:
            logger.warning(
                "JWT email mismatch: got %s, expected %s",
                token_email,
                pubsub_service_account_email,
            )
            raise HTTPException(status_code=401, detail="Unauthorized service account")


@app.post("/webhooks/gmail")
async def webhook_gmail(request: Request):
    _verify_pubsub_jwt(request)

    payload = await request.json()
    message = payload.get("message", {})
    if not message.get("data"):
        raise HTTPException(status_code=400, detail="Missing message.data")

    await _forward_to_worker(payload)
    return {"status": "accepted"}


async def _forward_to_worker(payload: dict, *, path: str = "/internal/family-office/gmail", extra_headers: dict | None = None) -> None:
    if not settings.worker_webhook_url:
        raise HTTPException(status_code=500, detail="WORKER_WEBHOOK_URL not configured")

    # Derive worker base URL from the configured gmail webhook URL
    base_url = settings.worker_webhook_url.rsplit("/", 3)[0] if "/internal/" in settings.worker_webhook_url else settings.worker_webhook_url.rstrip("/")
    url = f"{base_url}{path}"

    headers = {}
    if settings.worker_shared_secret:
        headers["X-Family-Office-Shared-Secret"] = settings.worker_shared_secret
    if extra_headers:
        headers.update(extra_headers)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload, headers=headers)
        if response.status_code >= 400:
            logger.error(
                "Worker forward failed: status=%s body=%s",
                response.status_code,
                response.text[:400],
            )
            raise HTTPException(status_code=502, detail="Worker rejected notification")
    except Exception as exc:
        logger.error("Worker forward exception: %s", exc, exc_info=True)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=502, detail="Worker forward failed") from exc


# ─── Plane Webhook Ingress ───────────────────────────────────────────────────


def _verify_plane_signature(request: Request, body: bytes) -> None:
    """Verify Plane webhook HMAC-SHA256 signature from X-Plane-Signature header."""
    plane_secret = getattr(settings, "plane_webhook_secret", "")
    if not plane_secret:
        logger.warning("plane_webhook_secret not configured — skipping signature verification")
        return

    signature = request.headers.get("X-Plane-Signature", "")
    if not signature:
        raise HTTPException(status_code=401, detail="Missing X-Plane-Signature header")

    expected = hmac.new(
        plane_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Invalid Plane webhook signature")


@app.post("/webhooks/plane")
async def webhook_plane(request: Request):
    """Receive Plane webhook payloads and forward to local worker.

    This endpoint is a dumb forwarder — all dedupe happens at the worker.
    """
    body = await request.body()
    _verify_plane_signature(request, body)

    payload = await request.json()

    # Pass through delivery ID for worker-side idempotency
    delivery_id = request.headers.get("X-Plane-Delivery", "")
    extra_headers = {}
    if delivery_id:
        extra_headers["X-Plane-Delivery"] = delivery_id

    await _forward_to_worker(
        payload,
        path="/internal/family-office/plane-webhook",
        extra_headers=extra_headers,
    )
    return {"status": "accepted"}
