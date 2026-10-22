#!/usr/bin/env python3
"""Make one minimal, local-only authenticated ODPT API request."""

from pathlib import Path
import socket
import ssl
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ENV_FILE = Path(__file__).resolve().parent.parent / ".env.local"
API_URL = "https://api.odpt.org/api/v4/odpt:Railway"


def read_api_key():
    try:
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError):
        return None

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name.strip() == "ODPT_API_KEY":
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            return value or None
    return None


def main():
    api_key = read_api_key()
    if not api_key:
        print("認証情報がありません。通信せず終了しました。")
        return 2

    # The key is sent only as the API's required query parameter. Never print
    # the URL, request, response body, or exception details.
    url = f"{API_URL}?{urlencode({'acl:consumerKey': api_key})}"
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=15) as response:
            if response.status != 200:
                print("ODPT API検証に失敗しました（HTTPエラー）。")
                return 1
            response.read(1)
    except HTTPError as error:
        if error.code in (401, 403):
            print(f"ODPT API検証に失敗しました（HTTP認証エラー: {error.code}）。")
        else:
            print(f"ODPT API検証に失敗しました（HTTPエラー: {error.code}）。")
        return 1
    except (ssl.SSLError,):
        print("ODPT API検証に失敗しました（TLS/SSL証明書エラー）。")
        return 1
    except (socket.gaierror,):
        print("ODPT API検証に失敗しました（DNS名前解決エラー）。")
        return 1
    except (TimeoutError, socket.timeout):
        print("ODPT API検証に失敗しました（接続タイムアウト）。")
        return 1
    except URLError as error:
        reason = error.reason
        if isinstance(reason, ssl.SSLError):
            category = "TLS/SSL証明書エラー"
        elif isinstance(reason, socket.gaierror):
            category = "DNS名前解決エラー"
        elif isinstance(reason, (TimeoutError, socket.timeout)):
            category = "接続タイムアウト"
        else:
            category = "プロキシ・ネットワーク関連エラー"
        print(f"ODPT API検証に失敗しました（{category}）。")
        return 1
    except (OSError, ValueError):
        print("ODPT API検証に失敗しました（プロキシ・ネットワーク関連エラー）。")
        return 1

    print("ODPT APIへの認証付きリクエストに成功しました。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
