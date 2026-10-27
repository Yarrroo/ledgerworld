"""Exit 0 when a GET of URL answers 2xx within 10 seconds.

Usage: python checks/url_ok.py URL
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request

TIMEOUT_S = 10


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    url = argv[0]
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_S) as response:
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"url_ok: {url}: {exc}", file=sys.stderr)
        return 1
    if 200 <= status < 300:
        return 0
    print(f"url_ok: {url}: HTTP {status}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
