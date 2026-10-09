"""One-time download from MobilityData's official GitHub release; no GTFS upload."""
import json
import urllib.request
from pathlib import Path
from .final_checks import DEFAULT_JAR


def main():
    request = urllib.request.Request("https://api.github.com/repos/MobilityData/gtfs-validator/releases/latest", headers={"User-Agent": "GTFS-Merge-Auditor-setup"})
    with urllib.request.urlopen(request, timeout=60) as response:
        release = json.load(response)
    asset = next(item for item in release["assets"] if item["name"].endswith("-cli.jar"))
    url = asset["browser_download_url"]
    if not url.startswith("https://github.com/MobilityData/gtfs-validator/releases/download/"):
        raise ValueError("Unexpected download source")
    DEFAULT_JAR.parent.mkdir(parents=True, exist_ok=True)
    stage = DEFAULT_JAR.with_suffix(".download")
    with urllib.request.urlopen(url, timeout=120) as response, stage.open("wb") as output:
        while block := response.read(1024 * 1024):
            output.write(block)
    stage.replace(DEFAULT_JAR)
    print(f"Installed {release['tag_name']} at {DEFAULT_JAR}")


if __name__ == "__main__":
    main()
