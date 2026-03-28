import json
from pathlib import Path
from typing import Any

from export_utils import get_output_directory, sanitize_name
from loguru import logger


def main() -> None:
    input_file = Path("export.jsonl")
    output_root = "zpgeek-job-detail"

    with input_file.open(encoding="utf-8") as file:
        for line in file:
            try:
                item: dict[str, Any] = json.loads(line)
            except json.JSONDecodeError:
                continue
            job_info = item.get("jobInfo", {})
            brand_info = item.get("brandComInfo", {})
            job_name = sanitize_name(job_info.get("jobName", "_"))
            position_name = sanitize_name(job_info.get("positionName", "_"))
            brand_name = sanitize_name(brand_info.get("brandName", "_"))
            directory = get_output_directory(
                output_root, position_name, job_name, brand_name
            )
            item_id = item.pop("_id", job_info.get("encryptId"))
            if not item_id:
                continue
            file_path = directory / f"{item_id}.json"
            try:
                with file_path.open("w", encoding="utf-8") as f:
                    json.dump(item, f, sort_keys=True, indent=4, ensure_ascii=False)
            except OSError:
                logger.exception("Failed to write file")
                continue


if __name__ == "__main__":
    main()
