#!/usr/bin/env python3
"""
Download Gaia DR3 gaia_source files from the ESA CDN.

Source: https://cdn.gea.esac.esa.int/Gaia/gdr3/gaia_source/

Usage:
    python download_gaia_dr3.py [OPTIONS]

Options:
    -o, --output-dir DIR    Directory to save downloaded files (default: gaia_dr3_data)
    -w, --workers N         Number of parallel download workers (default: 4)
    -n, --limit N           Maximum number of files to download (default: all)
    --dry-run               List files without downloading
    --resume                Skip files that already exist locally
"""

import argparse
import concurrent.futures
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urljoin

try:
    import requests
except ImportError:
    print("ERROR: 'requests' library is required. Install it with: pip install requests")
    sys.exit(1)

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False

BASE_URL = "https://cdn.gea.esac.esa.int/"
LIST_URL = "https://cdn.gea.esac.esa.int/?prefix=Gaia/gdr3/gaia_source/"
GCS_XML_NS = "http://doc.s3.amazonaws.com/2006-03-01"
CHUNK_SIZE = 1024 * 1024  # 1 MB
LIST_TIMEOUT = 60         # seconds to wait for the file-listing request
DOWNLOAD_TIMEOUT = 120    # seconds to wait for each file download request


def list_files(session: requests.Session, max_keys: int = 1000) -> list[str]:
    """
    Retrieve the list of file keys from the GCS-compatible CDN bucket listing.

    The endpoint returns S3/GCS-style XML with <Contents><Key> elements for
    each object whose prefix matches 'Gaia/gdr3/gaia_source/'.

    Returns a list of object keys (relative paths inside the bucket).
    """
    keys: list[str] = []
    next_marker: str | None = None

    while True:
        params: dict[str, str] = {
            "prefix": "Gaia/gdr3/gaia_source/",
            "max-keys": str(max_keys),
        }
        if next_marker:
            params["marker"] = next_marker

        response = session.get(BASE_URL, params=params, timeout=LIST_TIMEOUT)
        response.raise_for_status()

        root = ET.fromstring(response.text)
        ns = {"s3": GCS_XML_NS}

        for content in root.findall("s3:Contents", ns):
            key_elem = content.find("s3:Key", ns)
            if key_elem is not None and key_elem.text:
                key = key_elem.text
                # Skip the directory prefix itself
                if not key.endswith("/"):
                    keys.append(key)

        # Check if there are more pages
        is_truncated_elem = root.find("s3:IsTruncated", ns)
        if is_truncated_elem is None or is_truncated_elem.text.lower() != "true":
            break

        # Get the marker for the next page (last key in this page)
        next_marker_elem = root.find("s3:NextMarker", ns)
        if next_marker_elem is not None and next_marker_elem.text:
            next_marker = next_marker_elem.text
        elif keys:
            next_marker = keys[-1]
        else:
            break

    return keys


def download_file(
    session: requests.Session,
    key: str,
    output_dir: Path,
    resume: bool = True,
) -> tuple[str, bool, str]:
    """
    Download a single file identified by its bucket key.

    Returns (key, success, message).
    """
    filename = Path(key).name
    dest_path = output_dir / filename
    file_url = urljoin(BASE_URL, key)

    headers: dict[str, str] = {}
    existing_size = 0

    if resume and dest_path.exists():
        existing_size = dest_path.stat().st_size
        if existing_size > 0:
            headers["Range"] = f"bytes={existing_size}-"

    try:
        response = session.get(file_url, headers=headers, stream=True, timeout=DOWNLOAD_TIMEOUT)

        if response.status_code == 416:
            # Range not satisfiable – file is already complete
            return key, True, f"already complete ({dest_path})"

        if response.status_code == 206:
            # Partial content – resume download
            mode = "ab"
        elif response.status_code == 200:
            # Full download
            mode = "wb"
            existing_size = 0
        else:
            response.raise_for_status()  # unexpected status code

        total_size = int(response.headers.get("Content-Length", 0)) + existing_size

        with open(dest_path, mode) as fh:
            if HAS_TQDM:
                with tqdm(
                    total=total_size,
                    initial=existing_size,
                    unit="B",
                    unit_scale=True,
                    desc=filename,
                    leave=False,
                ) as progress:
                    for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                        if chunk:
                            fh.write(chunk)
                            progress.update(len(chunk))
            else:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        fh.write(chunk)

        return key, True, str(dest_path)

    except requests.RequestException as exc:
        return key, False, str(exc)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download Gaia DR3 gaia_source files from the ESA CDN.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-o", "--output-dir",
        default="gaia_dr3_data",
        help="Directory where downloaded files will be saved",
    )
    parser.add_argument(
        "-w", "--workers",
        type=int,
        default=4,
        help="Number of parallel download workers",
    )
    parser.add_argument(
        "-n", "--limit",
        type=int,
        default=None,
        help="Maximum number of files to download (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List available files without downloading them",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        default=True,
        help="Skip files already fully downloaded; resume partial downloads",
    )
    parser.add_argument(
        "--no-resume",
        action="store_false",
        dest="resume",
        help="Re-download files even if they already exist locally",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)

    with requests.Session() as session:
        session.headers.update({"User-Agent": "Gaia-DR3-Downloader/1.0"})

        # ── List available files ──────────────────────────────────────────────
        print(f"Listing files at: {LIST_URL}")
        try:
            keys = list_files(session)
        except requests.RequestException as exc:
            print(f"ERROR: Failed to retrieve file listing: {exc}", file=sys.stderr)
            sys.exit(1)
        except ET.ParseError as exc:
            print(f"ERROR: Failed to parse file listing XML: {exc}", file=sys.stderr)
            sys.exit(1)

        if not keys:
            print("No files found at the specified prefix.")
            sys.exit(0)

        if args.limit:
            keys = keys[: args.limit]

        print(f"Found {len(keys)} file(s).")

        if args.dry_run:
            print("\nFiles available for download:")
            for key in keys:
                print(f"  {urljoin(BASE_URL, key)}")
            return

        # ── Create output directory ───────────────────────────────────────────
        output_dir.mkdir(parents=True, exist_ok=True)
        print(f"Saving files to: {output_dir.resolve()}\n")

        # ── Download files in parallel ────────────────────────────────────────
        success_count = 0
        failure_count = 0
        start_time = time.monotonic()

        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(download_file, session, key, output_dir, args.resume): key
                for key in keys
            }

            completed = 0
            total = len(futures)
            width = len(str(total))

            for future in concurrent.futures.as_completed(futures):
                completed += 1
                key, ok, msg = future.result()
                filename = Path(key).name
                status = "OK" if ok else "FAIL"
                print(f"[{completed:>{width}}/{total}] [{status}] {filename}: {msg}")
                if ok:
                    success_count += 1
                else:
                    failure_count += 1

        elapsed = time.monotonic() - start_time
        print(f"\nFinished in {elapsed:.1f}s — {success_count} succeeded, {failure_count} failed.")

    if failure_count:
        sys.exit(1)


if __name__ == "__main__":
    main()
