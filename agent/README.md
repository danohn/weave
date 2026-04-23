# weave-agent

Weave edge node agent for the Weave SD-WAN control plane.

The package installs the `weave` CLI, which:

- registers the node with the controller
- manages WireGuard transport interfaces
- applies FRR configuration for routing
- maintains transport-aware overlay connectivity

## Install

Install the latest published agent from PyPI with `uv`:

```bash
uv tool install weave-agent
```

The installed executable is still named `weave`:

```bash
weave --help
```

## Upgrade

```bash
uv tool upgrade weave-agent
```

## Project

- Repository: https://github.com/danohn/weave
- Issues: https://github.com/danohn/weave/issues
