#!/usr/bin/env python3

import json
from pathlib import Path


def main() -> None:
    directory = Path("/data01/erdong/data/mllm/for_distance/0725_pit_civil_tools_3000").resolve()
    if not directory.is_dir():
        raise SystemExit(f"Directory does not exist: {directory}")

    json_files = sorted(directory.rglob("*.json"))
    if not json_files:
        print(f"No JSON files found in {directory}")
        return

    updated_count = 0
    for json_file in json_files:
        with json_file.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            print(f"Skipping {json_file}: root JSON value is not an object")
            continue

        data["conversations"] = []

        with json_file.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")

        updated_count += 1
        print(f"Updated {json_file}")

    print(f"Done. Updated {updated_count} file(s).")


if __name__ == "__main__":
    main()
