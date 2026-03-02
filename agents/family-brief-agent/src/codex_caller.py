"""Codex CLI subprocess caller for family brief agent.

Adapted from communication-agent's codex_specialist_caller.py. Calls Codex
in exec mode with a persona-specific config directory. The agent daemon itself
does NOT use --full-auto; the .codex/config.toml in each agent config dir
governs permissions via approval_policy = "never" (headless daemon — no terminal for prompts).
"""

import asyncio
import json
import logging
import os
from typing import Optional

from src.config import settings
from src.models import AgentResponse

logger = logging.getLogger(__name__)

# Map persona names to their config directories
_PERSONA_DIRS: dict[str, str] = {
    "family": settings.agent_config_dir_family,
    "personal-finance": settings.agent_config_dir_personal_finance,
    "personal-admin": settings.agent_config_dir_personal_admin,
}


def parse_codex_jsonl(output: str) -> dict:
    """Parse Codex CLI 'exec --json' JSONL stdout output.

    v0.101.0+ event types:
        thread.started  -> thread_id (session UUID)
        item.completed  -> item.type == "agent_message" -> item.text
        turn.completed  -> usage (logged, not returned)
        error           -> message (logged)
    """
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

        if event_type == "thread.started":
            session_id = data.get("thread_id")
        elif event_type == "item.completed":
            item = data.get("item", {})
            if item.get("type") == "agent_message":
                text_chunks.append(item.get("text", ""))
        elif event_type == "turn.completed":
            usage = data.get("usage", {})
            if usage:
                logger.info(
                    f"Codex usage: input={usage.get('input_tokens', 0)}, "
                    f"cached={usage.get('cached_input_tokens', 0)}, "
                    f"output={usage.get('output_tokens', 0)}"
                )
        elif event_type == "error":
            logger.warning(f"Codex error event: {data.get('message', '')}")

    return {"text": "\n".join(text_chunks), "session_id": session_id}


async def call_codex(
    prompt: str,
    agent_config_dir: str,
    context: Optional[str] = None,
    session_id: Optional[str] = None,
) -> AgentResponse:
    """Call a Codex agent via CLI subprocess.

    Args:
        prompt: The task prompt for the agent.
        agent_config_dir: Path to the persona's config directory (contains .codex/config.toml).
        context: Optional context to prepend to the prompt.
        session_id: Optional session ID to resume a previous conversation.

    Returns:
        AgentResponse with the agent's text output and metadata.
    """
    codex_home = os.path.join(agent_config_dir, ".codex")

    if not os.path.isdir(codex_home):
        logger.error(f"CODEX_HOME not found: {codex_home}")
        return AgentResponse(
            success=False,
            response_text="",
            error=f"CODEX_HOME directory missing: {codex_home}",
        )

    # Build full prompt with context if provided
    full_prompt = prompt
    if context:
        full_prompt = f"Context:\n{context}\n\nTask:\n{prompt}"

    # Build Codex CLI command — NO --full-auto (config.toml governs permissions)
    if session_id:
        cmd = [
            "codex", "exec", "resume",
            "--skip-git-repo-check", "--json",
            session_id, full_prompt,
        ]
    else:
        cmd = [
            "codex", "exec",
            "--skip-git-repo-check", "--json",
            "-C", agent_config_dir,
            full_prompt,
        ]

    # Environment: set CODEX_HOME, remove CLAUDECODE (prevents nested session issues)
    env = {**os.environ}
    env["CODEX_HOME"] = codex_home
    env.pop("CLAUDECODE", None)

    try:
        logger.info(f"Calling Codex agent: config_dir={agent_config_dir}")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=agent_config_dir,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=300
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            logger.error(f"Codex exec timed out after 300s: {agent_config_dir}")
            return AgentResponse(
                success=False,
                response_text="",
                error="Codex exec timed out after 300s",
            )

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            logger.error(
                f"Codex agent failed (rc={process.returncode}): {error_msg[:500]}"
            )
            return AgentResponse(
                success=False,
                response_text="",
                error=f"Agent execution failed (rc={process.returncode}): {error_msg[:500]}",
            )

        # Parse JSONL output
        result = parse_codex_jsonl(stdout.decode())

        logger.info(f"Codex agent completed successfully: {agent_config_dir}")

        return AgentResponse(
            success=True,
            response_text=result["text"],
            metadata={
                "session_id": result.get("session_id"),
                "config_dir": agent_config_dir,
                "backend": "codex",
            },
        )

    except asyncio.TimeoutError:
        logger.error(f"Unexpected timeout for agent: {agent_config_dir}")
        return AgentResponse(
            success=False,
            response_text="",
            error="Unexpected timeout",
        )
    except Exception as e:
        logger.error(
            f"Error calling Codex agent {agent_config_dir}: {e}", exc_info=True
        )
        return AgentResponse(
            success=False,
            response_text="",
            error=f"Exception: {str(e)}",
        )
