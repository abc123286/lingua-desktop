"""Entry point used by the packaged app (LINGUA.exe / LINGUA.app)."""
import os
import sys


def _fix_streams():
    # Windowed apps have no console: send output to a log file so nothing crashes on print/progress bars.
    if sys.stdout is None or sys.stderr is None:
        home = os.path.join(os.path.expanduser("~"), ".lingua_desktop")
        os.makedirs(home, exist_ok=True)
        log = open(os.path.join(home, "lingua.log"), "a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = log
        if sys.stderr is None:
            sys.stderr = log


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    _fix_streams()
    if "--selftest" in sys.argv:
        from lingua.selftest import run
        sys.exit(run(full="--full" in sys.argv))
    from lingua.ui import main
    main()
