"""
Daily agent scheduler with automatic final phase execution.

Uruchamia:
1. daily_agent --faza draft (08:00)
2. Czeka na czas z next_final.txt
3. daily_agent --faza final (automatycznie)
"""
import os
import sys
import time
import subprocess
from pathlib import Path
from datetime import datetime

DATA_DIR = Path(__file__).parent.parent.parent / "data"
LOG_DIR = DATA_DIR / "logs"


def run_draft_phase(stawka: int = 10, dni: int = 3) -> None:
    """Uruchom draft phase."""
    print(f"[{datetime.now()}] DRAFT PHASE STARTING...")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "footstats.daily_agent",
            "--stawka",
            str(stawka),
            "--dni",
            str(dni),
            "--faza",
            "draft",
        ],
        cwd=DATA_DIR.parent,
    )
    if result.returncode != 0:
        print(f"[ERROR] Draft phase failed with code {result.returncode}")
        return
    print(f"[{datetime.now()}] DRAFT PHASE COMPLETED")


def wait_and_run_final(stawka: int = 10, dni: int = 3) -> None:
    """Czekaj na czas z next_final.txt, potem uruchom final phase."""
    next_final_file = DATA_DIR / "next_final.txt"

    if not next_final_file.exists():
        print(f"[{datetime.now()}] next_final.txt nie istnieje — brak fazy final")
        return

    with open(next_final_file) as f:
        final_time_str = f.read().strip()

    try:
        final_time = datetime.strptime(final_time_str, "%H:%M").time()
    except ValueError:
        print(f"[ERROR] Invalid time format in next_final.txt: {final_time_str}")
        return

    print(f"[{datetime.now()}] Scheduled final phase at {final_time_str}")

    # Czekaj aż będzie czas
    while True:
        now = datetime.now().time()
        if now >= final_time:
            print(f"[{datetime.now()}] FINAL PHASE STARTING (scheduled for {final_time_str})")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "footstats.daily_agent",
                    "--stawka",
                    str(stawka),
                    "--dni",
                    str(dni),
                    "--faza",
                    "final",
                ],
                cwd=DATA_DIR.parent,
            )
            if result.returncode == 0:
                print(f"[{datetime.now()}] FINAL PHASE COMPLETED")
                # Cleanup
                try:
                    next_final_file.unlink()
                except FileNotFoundError:
                    pass
            else:
                print(f"[ERROR] Final phase failed with code {result.returncode}")
            break

        # Check every 5 minutes
        time.sleep(300)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Daily agent with auto final phase")
    parser.add_argument("--stawka", type=int, default=10, help="Stawka (PLN)")
    parser.add_argument("--dni", type=int, default=3, help="Dni do przodu")
    parser.add_argument(
        "--mode",
        choices=["draft-only", "draft-wait-final", "final-only"],
        default="draft-wait-final",
        help="Mode: draft only, or draft then wait for final",
    )

    args = parser.parse_args()

    if args.mode in ["draft-only", "draft-wait-final"]:
        run_draft_phase(args.stawka, args.dni)

    if args.mode in ["draft-wait-final", "final-only"]:
        wait_and_run_final(args.stawka, args.dni)
