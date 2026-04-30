from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_checkpoint(path: Path) -> dict:
    if not path.exists():
        return {
            "completed_work_units": 0.0,
            "history": [],
        }

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_checkpoint(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run one slot of simulated N-body work and update checkpoint."
    )
    parser.add_argument("--checkpoint-path", required=True, help="Path to JSON checkpoint file")
    parser.add_argument("--slot-index", type=int, required=True, help="Current slot index")
    parser.add_argument("--scale", type=int, required=True, help="Allocated scale for this slot")
    parser.add_argument(
        "--work-per-slot",
        type=float,
        required=True,
        help="How much work this slot should complete at the given scale",
    )
    parser.add_argument(
        "--remaining-work",
        type=float,
        required=True,
        help="Remaining work before this slot starts",
    )
    args = parser.parse_args()

    checkpoint_path = Path(args.checkpoint_path)
    state = load_checkpoint(checkpoint_path)

    actual_work = min(args.work_per_slot, max(args.remaining_work, 0.0))

    state["completed_work_units"] = float(state.get("completed_work_units", 0.0)) + actual_work
    state.setdefault("history", []).append(
        {
            "slot_index": args.slot_index,
            "scale": args.scale,
            "requested_work": args.work_per_slot,
            "remaining_work_before_slot": args.remaining_work,
            "actual_work_completed": actual_work,
        }
    )

    save_checkpoint(checkpoint_path, state)

    print(
        json.dumps(
            {
                "slot_index": args.slot_index,
                "scale": args.scale,
                "actual_work_completed": actual_work,
                "completed_work_units": state["completed_work_units"],
            }
        )
    )


if __name__ == "__main__":
    main()