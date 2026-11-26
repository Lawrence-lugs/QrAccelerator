"""Archive a completed LibreLane CI step and the files referenced by its state."""

import argparse
import json
from pathlib import Path
import tarfile

CONTAINER_ROOT = Path("/workspace")


def referenced_files(views):
    for view in views.values():
        if isinstance(view, dict):
            yield from referenced_files(view)
        elif view is not None:
            yield Path(view).relative_to(CONTAINER_ROOT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", type=Path)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()

    state = json.loads(args.state.read_text())
    del state["metrics"]
    files = set(referenced_files(state))
    files.add(args.state)
    with tarfile.open(args.archive, "w:gz", compresslevel=1, dereference=True) as archive:
        for file in sorted(files):
            if not file.is_file() or ".." in file.parts:
                raise ValueError(f"Missing or invalid checkpoint file {file}")
            archive.add(file, arcname=str(file), recursive=False)


if __name__ == "__main__":
    main()
