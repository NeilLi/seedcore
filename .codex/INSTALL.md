# Installing Seedcore for Codex

Enable Seedcore skills in Codex via native skill discovery.

## Prerequisites

- Git
- Codex with native skill discovery enabled

## Installation

1. Clone this repository somewhere durable:

   ```bash
   git clone <your-seedcore-repo-url> ~/code/seedcore
   ```

2. Create the Codex skills symlink:

   ```bash
   mkdir -p ~/.agents/skills
   ln -s ~/code/seedcore/skills ~/.agents/skills/seedcore
   ```

3. Restart Codex so it rescans `~/.agents/skills`.

## Verify

```bash
ls -la ~/.agents/skills/seedcore
```

You should see a symlink pointing at this repository's `skills/` directory.

## Updating

```bash
cd ~/code/seedcore && git pull
```

The skills update through the existing symlink.

## Notes

- Codex skills are synchronized with the Gemini extension tool surface, including owner/creator authority tools:
  - `seedcore.identity.owner.*`
  - `seedcore.creator_profile.*`
  - `seedcore.delegation.*`
  - `seedcore.trust_preferences.*`
  - `seedcore.owner_context.get`
  - `seedcore.agent_action.preflight`
- Use write-capable authority tools only for explicit user requests and keep high-consequence decisions on governed preflight/evaluate flows.
- If the `seedcore.*` MCP server is not available, the skills fall back to documented local commands.
