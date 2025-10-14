import json
import re
from pathlib import Path
from typing import Any


def sanitize_name(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", name)


input_file = "export.jsonl"
output_root = "zpgeek-job"


with Path(input_file).open(encoding="utf-8") as file:
    for line in file:
        try:
            item: dict[str, Any] = json.loads(line)
        except json.JSONDecodeError:
            continue
        city_name = sanitize_name(item.get("cityName", "_"))
        job_name = sanitize_name(item.get("jobName", "_"))
        brand_name = sanitize_name(item.get("brandName", "_"))
        directory = Path(output_root) / city_name / job_name / brand_name
        directory.mkdir(parents=True, exist_ok=True)
        item_id = item.pop("_id", item.get("encryptJobId"))
        if not item_id:
            continue
        file_path = directory / f"{item_id}.json"
        try:
            with file_path.open("w", encoding="utf-8") as f:
                json.dump(item, f, sort_keys=True, indent=4, ensure_ascii=False)
        except Exception:
            continue
