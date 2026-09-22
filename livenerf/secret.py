"""Manage the frozen-panel secret.

    python -m livenerf.secret init     # create it (once, ever)
    python -m livenerf.secret commit   # print sha256(secret) for PREREGISTRATION.md
    python -m livenerf.secret hashes   # print per-item hashes of the frozen panel
"""

import sys

from .common import init_secret, load_secret, sha256


def main(argv: list[str]) -> None:
    cmd = argv[0] if argv else ""
    if cmd == "init":
        path = init_secret()
        print(f"wrote {path}\nBack this file up somewhere safe. Then run `python -m livenerf.secret commit`.")
    elif cmd == "commit":
        print(f"sha256(secret) = {sha256(load_secret())}")
    elif cmd == "hashes":
        from .generators import build_items

        for family, items in build_items("frozen").items():
            for it in items:
                print(f"{it['id']}\t{it['metadata']['item_hash']}")
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
