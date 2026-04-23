from __future__ import annotations

import json
from pathlib import Path


def write_evidence(artifact_dir: str, incident_id: str, payload: dict, summary: dict) -> str:
    out_dir = Path(artifact_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{incident_id}.json"

    data = {
        "incidentId": incident_id,
        "rawAlert": payload,
        "summary": summary,
    }

    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(out_path)
    return str(out_path)
