"""python -m budget_app 진입점 - CLI 호출만 한다."""

import sys

from budget_app.cli import main

if __name__ == "__main__":
    sys.exit(main())
