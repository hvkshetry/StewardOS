from __future__ import annotations

import json

from src.codex_caller import parse_codex_jsonl


def test_parse_codex_jsonl_captures_completed_items_and_mcp_tool_calls():
    output = "\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "thread-123"}),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item_1",
                        "type": "command_execution",
                        "command": "/bin/bash -lc pwd",
                        "status": "completed",
                    },
                }
            ),
            json.dumps(
                {
                    "type": "mcp_tool_call_end",
                    "invocation": {
                        "server": "google-workspace-agent-rw",
                        "tool": "reply_gmail_message",
                        "arguments": {"message_id": "gmail-1"},
                    },
                    "result": {
                        "message_id": "sent-1",
                        "thread_id": "thread-123",
                    },
                }
            ),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "id": "item_2",
                        "type": "agent_message",
                        "text": "DONE",
                    },
                }
            ),
        ]
    )

    parsed = parse_codex_jsonl(output)

    assert parsed["session_id"] == "thread-123"
    assert parsed["text"] == "DONE"
    assert parsed["completed_items"] == [
        {
            "id": "item_1",
            "type": "command_execution",
            "command": "/bin/bash -lc pwd",
            "status": "completed",
        },
        {
            "id": "item_2",
            "type": "agent_message",
            "text": "DONE",
        },
    ]
    assert parsed["mcp_tool_calls"] == [
        {
            "server": "google-workspace-agent-rw",
            "tool": "reply_gmail_message",
            "arguments": {"message_id": "gmail-1"},
            "result": {
                "message_id": "sent-1",
                "thread_id": "thread-123",
            },
        }
    ]
