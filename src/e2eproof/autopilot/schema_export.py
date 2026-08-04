from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from .schemas import CycleInput, CycleOutput, ExecutionBrief


def write_json_schemas(output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    models: dict[str, type[BaseModel]] = {
        "autopilot-input.schema.json": CycleInput,
        "autopilot-output.schema.json": CycleOutput,
        "autopilot-execution-brief.schema.json": ExecutionBrief,
    }
    written: list[Path] = []
    for name, model in models.items():
        path = output_dir / name
        path.write_text(
            json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        written.append(path)
    return written
