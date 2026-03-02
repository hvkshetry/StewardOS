"""HP ENVY ingress for Gmail Pub/Sub; forwards payloads to local worker."""

import logging

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request

from src.config import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Family Office Mail Ingress",
    description="Gmail webhook ingress that forwards notifications to worker",
    version="0.1.0",
)


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "family-office-mail-ingress",
        "worker_url_configured": bool(settings.worker_webhook_url),
    }


@app.post("/webhooks/gmail")
async def webhook_gmail(request: Request, background_tasks: BackgroundTasks):
    payload = await request.json()
    message = payload.get("message", {})
    if not message.get("data"):
        raise HTTPException(status_code=400, detail="Missing message.data")

    background_tasks.add_task(_forward_to_worker, payload)
    return {"status": "accepted"}


async def _forward_to_worker(payload: dict) -> None:
    if not settings.worker_webhook_url:
        logger.error("WORKER_WEBHOOK_URL not configured; dropping notification")
        return

    headers = {}
    if settings.worker_shared_secret:
        headers["X-Family-Office-Shared-Secret"] = settings.worker_shared_secret

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                settings.worker_webhook_url,
                json=payload,
                headers=headers,
            )
        if response.status_code >= 400:
            logger.error(
                "Worker forward failed: status=%s body=%s",
                response.status_code,
                response.text[:400],
            )
    except Exception as exc:
        logger.error("Worker forward exception: %s", exc, exc_info=True)
