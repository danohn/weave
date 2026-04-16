import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class NodeState:
    node_id: str
    auth_token: str
    vpn_ip: str


def load(path: str) -> NodeState | None:
    p = Path(path)
    if not p.exists():
        return None
    data = json.loads(p.read_text())
    return NodeState(**data)


def save(path: str, state: NodeState) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(asdict(state), indent=2))
    os.chmod(path, 0o600)
