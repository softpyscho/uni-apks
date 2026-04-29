import os
import threading
from pathlib import Path
from typing import Self
from curl_cffi import requests
from curl_cffi.requests import exceptions as req_exc

from src.core.logger import epr, pr


class NetworkError(Exception):
    pass

class NetworkManager:
    _download_locks: dict[Path, threading.Lock] = {}
    _locks_mutex: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self.session = requests.Session(impersonate="firefox147")
        token = os.getenv("GITHUB_TOKEN")
        self._gh_headers: dict[str, str] = {"Authorization": f"token {token}"} if token else {}
        self._request_lock = threading.Lock()

    def get(self, url: str, headers: dict[str, str] | None = None) -> str:
        try:
            with self._request_lock:
                resp = self.session.get(url, timeout=10, allow_redirects=True, headers=headers)
            if (code := resp.status_code) >= 400:
                epr(f"HTTP {code} for {url}: {resp.text[:200].replace('\n', ' ')}")
                resp.raise_for_status()
            return resp.text
        except req_exc.RequestException as exc:
            raise NetworkError(f"Request failed: {url}") from exc

    def gh_get(self, url: str) -> str:
        return self.get(url, headers=self._gh_headers)

    def download(self, url: str, dest: Path, headers: dict[str, str] | None = None) -> None:
        if dest.exists():
            return

        with self._get_lock(dest):
            if dest.exists():
                return

            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(f"tmp.{dest.name}")
            tmp.unlink(missing_ok=True)
            try:
                with self._request_lock:
                    resp = self.session.get(url, timeout=10, stream=True, allow_redirects=True, headers=headers)
                resp.raise_for_status()
                with tmp.open("wb") as fh:
                    for chunk in resp.iter_content(chunk_size=131072):
                        if chunk:
                            fh.write(chunk)
                tmp.replace(dest)
            except Exception as exc:
                tmp.unlink(missing_ok=True)
                raise NetworkError(f"Download failed: {url}") from exc

    def gh_download(self, url: str, dest: Path) -> None:
        pr(f"Getting '{dest.name}' from '{url}'")
        self.download(url, dest, headers=self._gh_headers | {"Accept": "application/octet-stream"})

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self.session.close()

    @classmethod
    def _get_lock(cls, key: Path) -> threading.Lock:
        with cls._locks_mutex:
            return cls._download_locks.setdefault(key, threading.Lock())