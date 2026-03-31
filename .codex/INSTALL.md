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

- This V1 plugin is read-only and workflow-oriented.
- If the `seedcore.*` MCP server is not available, the skills fall back to documented local commands.
