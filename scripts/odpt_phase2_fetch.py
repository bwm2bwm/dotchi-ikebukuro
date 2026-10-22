#!/usr/bin/env python3
"""Fetch a small, scoped ODPT Tokyo Metro JSON snapshot for local research."""

from pathlib import Path
import json
import socket
import ssl
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import certifi

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env.local"
OUT = ROOT / "local_data" / "odpt"
BASE = "https://api.odpt.org/api/v4/"
OPERATOR = "odpt.Operator:TokyoMetro"
RAILWAYS = (
    "odpt.Railway:TokyoMetro.Yurakucho",
    "odpt.Railway:TokyoMetro.Fukutoshin",
)


def read_key():
    try:
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return None
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        if k.strip() == "ODPT_API_KEY":
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            return v or None
    return None


def main():
    key = read_key()
    if not key:
        print("ODPT_API_KEY が .env.local にありません。通信していません。")
        return 2
    jobs = [("Railway", {"odpt:operator": OPERATOR}),
            ("Station", {"odpt:operator": OPERATOR})]
    for railway in RAILWAYS:
        jobs.extend([
            ("TrainTimetable", {"odpt:operator": OPERATOR, "odpt:railway": railway}),
            ("StationTimetable", {"odpt:operator": OPERATOR, "odpt:railway": railway}),
        ])
    OUT.mkdir(parents=True, exist_ok=True)
    context = ssl.create_default_context(cafile=certifi.where())
    failed = False
    for resource, filters in jobs:
        params = {**filters, "acl:consumerKey": key}
        request = Request(BASE + "odpt:" + resource + "?" + urlencode(params),
                          headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=30, context=context) as response:
                if response.status != 200:
                    print(f"{resource}: HTTPエラー ({response.status})")
                    failed = True
                    continue
                payload = json.load(response)
            if not isinstance(payload, list):
                print(f"{resource}: 想定外の応答形式。内容は保存しません")
                failed = True
                continue
            suffix = filters.get("odpt:railway", "all").rsplit(".", 1)[-1]
            path = OUT / f"{resource}_{suffix}.json"
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            try:
                path.chmod(0o600)
            except OSError:
                pass
            print(f"{path.relative_to(ROOT)}: {len(payload)} records")
        except HTTPError as e:
            category = "HTTP認証エラー" if e.code in (401, 403) else "HTTPエラー"
            print(f"{resource}: {category} ({e.code})")
            failed = True
        except ssl.SSLError:
            print(f"{resource}: TLS証明書エラー")
            failed = True
        except (TimeoutError, socket.timeout):
            print(f"{resource}: タイムアウト")
            failed = True
        except URLError as e:
            reason = e.reason
            if isinstance(reason, socket.gaierror): category = "DNSエラー"
            elif isinstance(reason, ssl.SSLError): category = "TLS証明書エラー"
            elif isinstance(reason, (TimeoutError, socket.timeout)): category = "タイムアウト"
            else: category = "ネットワークエラー"
            print(f"{resource}: {category}")
            failed = True
        except (OSError, ValueError, UnicodeError):
            print(f"{resource}: 保存またはJSON解析エラー")
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
