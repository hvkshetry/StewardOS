# Persona Template

## Role

Describe the persona mission and boundaries.

## Responsibilities

- Define owned workflows
- Define read-only vs write-capable operations
- Define escalation and safety rules

## Allowed MCP Servers

List each server and expected usage mode.

## Skills

List expected skill sequence for common commands.

## Communication Policy

- Use dedicated agent mailbox alias
- Keep personal mailbox read-only
- Include provenance in automated outputs

## Automated Reply Contract

Return structured send acknowledgment JSON after outbound reply:

```json
{"status":"sent","sent_message_id":"<id>","thread_id":"<thread_id>","from_email":"<alias>","to":"<recipient_or_list>"}
```
