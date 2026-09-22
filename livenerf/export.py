"""Write the public dev panel to data/public/<family>.jsonl (with the canary on every line).

    python -m livenerf.export
"""

import json

from .common import CANARY, REPO_ROOT
from .generators import build_items


def main() -> None:
    out_dir = REPO_ROOT / "data" / "public"
    out_dir.mkdir(parents=True, exist_ok=True)
    for family, items in build_items("public").items():
        path = out_dir / f"{family}.jsonl"
        with path.open("w") as f:
            for it in items:
                f.write(json.dumps({"canary": CANARY, **it}, sort_keys=True) + "\n")
        print(f"wrote {path} ({len(items)} items)")


if __name__ == "__main__":
    main()
