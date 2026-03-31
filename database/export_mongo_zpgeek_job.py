from pathlib import Path
from typing import Any

import orjson
from export_utils import get_output_directory, sanitize_name
from loguru import logger

ORJSON_OPTIONS = orjson.OPT_INDENT_2 | orjson.OPT_SORT_KEYS


def main() -> None:
    input_file = "export.jsonl"
    output_root = "zpgeek-job"

    created_dirs: set[Path] = set()
    total = 0
    skipped = 0
    errors = 0

    with Path(input_file).open("rb") as file:
        for line in file:
            try:
                item: dict[str, Any] = orjson.loads(line)
            except orjson.JSONDecodeError:
                errors += 1
                continue

            city_name = sanitize_name(item.get("cityName", "_"))
            job_name = sanitize_name(item.get("jobName", "_"))
            brand_name = sanitize_name(item.get("brandName", "_"))
            directory = get_output_directory(
                output_root, city_name, job_name, brand_name
            )

            if directory not in created_dirs:
                created_dirs.add(directory)

            item_id = item.pop("_id", item.get("encryptJobId"))
            if not item_id:
                skipped += 1
                continue

            file_path = directory / f"{item_id}.json"
            try:
                with file_path.open("wb") as f:
                    f.write(orjson.dumps(item, option=ORJSON_OPTIONS))
                total += 1
            except OSError:
                logger.exception("Failed to write file")
                errors += 1
                continue


if __name__ == "__main__":
    main()
