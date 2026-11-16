"""Run CLI tests in a separate mutex namespace from the user's open app."""

from functools import partial
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from memcard.instance import single_instance

main.single_instance = partial(single_instance, name=f"Local\\MemCard.CliTest.{uuid4()}")

if __name__ == "__main__":
    raise SystemExit(main.main())
