import argparse
import sys
from client.app.demo import run_design_demo
from client.app.local_entry import main as run_local_replay
from client.app.packaged_entry import main as run_institution_app
from scripts.run_dop4864_live_hardware_demo import main as run_live_hardware_demo


def main(argv: list[str] | None = None) -> int:
    """Start the institution application unless an explicit debug mode is chosen."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--replay", action="store_true")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--live-demo", action="store_true")
    mode, remaining = parser.parse_known_args(arguments)
    if mode.demo:
        if remaining or mode.replay or mode.live_demo:
            raise SystemExit("--demo cannot be combined with other runtime options")
        return run_design_demo()
    if mode.live_demo:
        if mode.replay:
            raise SystemExit("--live-demo cannot be combined with --replay")
        return run_live_hardware_demo(remaining)
    if mode.replay:
        return run_local_replay(remaining)
    if remaining:
        raise SystemExit("debug replay options require explicit --replay")
    return run_institution_app()


if __name__ == "__main__":
    raise SystemExit(main())
