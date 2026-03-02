"""Codex CLI caller for family-office worker."""

import asyncio
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Optional

from src.config import settings
from src.models import AgentResponse

logger = logging.getLogger(__name__)


def parse_codex_jsonl(output: str) -> dict:
    """Parse Codex JSONL output into message text and session id."""
    lines = output.strip().split("\n")
    text_chunks = []
    session_id = None

    for line in lines:
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue

        event_type = data.get("type")
        if event_type in {"thread.started", "thread.resumed"}:
            session_id = data.get("thread_id") or session_id
        elif event_type == "item.completed":
            item = data.get("item", {})
            if item.get("type") == "agent_message":
                text_chunks.append(item.get("text", ""))
        elif event_type == "error":
            logger.warning("Codex error event: %s", data.get("message", ""))

    return {"text": "\n".join(text_chunks).strip(), "session_id": session_id}


async def call_codex(
    prompt: str,
    agent_config_dir: str,
    context: Optional[str] = None,
    session_id: Optional[str] = None,
) -> AgentResponse:
    """Invoke Codex CLI against a specific persona config directory."""
    codex_home = os.path.join(agent_config_dir, ".codex")
    if not os.path.isdir(codex_home):
        return AgentResponse(
            success=False,
            response_text="",
            error=f"CODEX_HOME directory missing: {codex_home}",
        )

    codex_bin = settings.codex_bin
    if not os.path.isfile(codex_bin):
        detected = shutil.which("codex")
        if detected:
            codex_bin = detected

    if not codex_bin or not os.path.exists(codex_bin):
        return AgentResponse(
            success=False,
            response_text="",
            error=f"Codex binary not found. Checked: {settings.codex_bin}",
        )

    full_prompt = prompt if not context else f"Context:\n{context}\n\nTask:\n{prompt}"

    if session_id:
        cmd = [
            codex_bin,
            "exec",
            "resume",
            "--skip-git-repo-check",
            "--full-auto",
            "--json",
            session_id,
            full_prompt,
        ]
    else:
        cmd = [
            codex_bin,
            "exec",
            "--skip-git-repo-check",
            "--full-auto",
            "--json",
            "-C",
            agent_config_dir,
            full_prompt,
        ]

    env = {**os.environ}
    env["CODEX_HOME"] = codex_home
    env["TMPDIR"] = settings.codex_scratch_dir
    env.pop("CLAUDECODE", None)

    Path(settings.codex_scratch_dir).mkdir(parents=True, exist_ok=True)

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=agent_config_dir,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=settings.codex_timeout_seconds,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return AgentResponse(
                success=False,
                response_text="",
                error=f"Codex timeout after {settings.codex_timeout_seconds}s",
            )

        if process.returncode != 0:
            err = (stderr.decode() or "Unknown error")[:1000]
            return AgentResponse(
                success=False,
                response_text="",
                error=f"Codex failed (rc={process.returncode}): {err}",
            )

        parsed = parse_codex_jsonl(stdout.decode())
        return AgentResponse(
            success=True,
            response_text=parsed["text"],
            metadata={"session_id": parsed.get("session_id"), "backend": "codex"},
        )
    except Exception as exc:
        logger.error("Codex call error: %s", exc, exc_info=True)
        return AgentResponse(success=False, response_text="", error=str(exc))
