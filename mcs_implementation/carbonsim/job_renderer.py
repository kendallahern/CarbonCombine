from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SlotJobRenderRequest:
    cluster_name: str
    job_name: str
    nodes: int
    slot_minutes: int
    checkpoint_path: str
    output_path: str
    error_path: str
    rendered_script_path: str
    slot_index: int
    scale: int
    work_per_slot: float
    remaining_work: float
    template_path: str = "mcs_implementation/jobs/nbody.sbatch.j2"


def _render_template(template_text: str, values: dict[str, object]) -> str:
    rendered = template_text
    for key, value in values.items():
        rendered = rendered.replace(f"{{{{ {key} }}}}", str(value))
    return rendered


def _format_time_limit(slot_minutes: int) -> str:
    hours = slot_minutes // 60
    minutes = slot_minutes % 60
    return f"{hours:02d}:{minutes:02d}:00"


def render_slot_job_script(request: SlotJobRenderRequest) -> str:
    template_path = Path(request.template_path)
    if not template_path.exists():
        raise FileNotFoundError(f"Job template not found: {template_path}")

    template_text = template_path.read_text(encoding="utf-8")

    values = {
        "job_name": request.job_name,
        "cluster_name": request.cluster_name,
        "nodes": request.nodes,
        "slot_minutes": request.slot_minutes,
        "time_limit": _format_time_limit(request.slot_minutes),
        "output_path": request.output_path,
        "error_path": request.error_path,
        "checkpoint_path": request.checkpoint_path,
        "slot_index": request.slot_index,
        "scale": request.scale,
        "work_per_slot": request.work_per_slot,
        "remaining_work": request.remaining_work,
    }

    rendered = _render_template(template_text, values)

    output_path = Path(request.rendered_script_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")

    return str(output_path)