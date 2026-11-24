"""PyInstaller entry point: runs the package as a script."""

from redmine_time_tracker.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
