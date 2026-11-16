"""MEP orchestration entry point. No dependency installation or cloud calls."""
from master_project.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
