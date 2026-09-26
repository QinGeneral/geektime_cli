from __future__ import annotations

import json
from pathlib import Path

from selenium import webdriver

from geektime_dl.core import http_client as http_client_module
from geektime_dl.core.http_client import GeektimeHttpClient


class FakeDriver:
    def __init__(self, current_url: str, cookies: list[dict]):
        self.current_url = current_url
        self.cookies = cookies
        self.opened_url = ""
        self.maximized = False
        self.quit_called = False

    def maximize_window(self) -> None:
        self.maximized = True

    def get(self, url: str) -> None:
        self.opened_url = url

    def get_cookies(self) -> list[dict]:
        return self.cookies

    def quit(self) -> None:
        self.quit_called = True


def make_client(chrome_path: Path) -> GeektimeHttpClient:
    client = object.__new__(GeektimeHttpClient)
    client.header = {"Accept": "application/json", "Cookie": "old=value"}
    client.chrome_app_path = str(chrome_path)
    return client


def test_browser_login_saves_valid_browser_cookies(monkeypatch, tmp_path: Path) -> None:
    chrome_path = tmp_path / "Google Chrome.app"
    chrome_path.mkdir()
    client = make_client(chrome_path)
    driver = FakeDriver(
        "https://time.geekbang.org/dashboard/usercenter",
        [{"name": "session", "value": "abc"}, {"name": "uid", "value": "42"}],
    )
    saved: list[dict] = []

    monkeypatch.setattr(webdriver, "ChromeOptions", object)
    monkeypatch.setattr(webdriver, "Chrome", lambda *, options: driver)
    monkeypatch.setattr(client, "_validate_header_by_request", lambda: True)
    monkeypatch.setattr(http_client_module, "save_credentials", lambda header: saved.append(header))

    assert client.login_via_browser(max_wait=1, poll_interval=0) is True
    assert driver.maximized is True
    assert driver.opened_url == client.home_page_url
    assert driver.quit_called is True
    assert client.header["Cookie"] == "session=abc; uid=42"
    assert saved == [client.header]


def test_failed_cookie_validation_preserves_existing_credentials(
    monkeypatch, tmp_path: Path
) -> None:
    chrome_path = tmp_path / "Google Chrome.app"
    chrome_path.mkdir()
    client = make_client(chrome_path)
    original_header = dict(client.header)
    driver = FakeDriver(
        "https://time.geekbang.org/dashboard/usercenter",
        [{"name": "session", "value": "invalid"}],
    )
    clock = iter([0.0, 0.0, 2.0])
    saved: list[dict] = []

    monkeypatch.setattr(webdriver, "ChromeOptions", object)
    monkeypatch.setattr(webdriver, "Chrome", lambda *, options: driver)
    monkeypatch.setattr(client, "_validate_header_by_request", lambda: False)
    monkeypatch.setattr(http_client_module, "save_credentials", lambda header: saved.append(header))
    monkeypatch.setattr(http_client_module.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(http_client_module.time, "sleep", lambda _: None)

    assert client.login_via_browser(max_wait=1, poll_interval=0) is False
    assert client.header == original_header
    assert saved == []
    assert driver.quit_called is True


def test_login_validation_uses_authenticated_course_endpoint(monkeypatch, tmp_path: Path) -> None:
    chrome_path = tmp_path / "Google Chrome.app"
    chrome_path.mkdir()
    client = make_client(chrome_path)
    requests: list[tuple[str, dict]] = []

    def fake_post(url: str, data: dict) -> str:
        requests.append((url, data))
        return json.dumps({"code": 0, "data": {"list": []}})

    monkeypatch.setattr(client, "post", fake_post)

    assert client._validate_header_by_request() is True
    assert requests[0][0] == "https://time.geekbang.org/serv/v3/learn/product"
    assert requests[0][1]["size"] == 1


def test_cookie_header_and_redirect_host_are_strict() -> None:
    cookies = [
        {"name": "valid", "value": "one"},
        {"name": "", "value": "ignored"},
        {"name": "bad;name", "value": "ignored"},
        {"name": "newline", "value": "bad\nvalue"},
        {"name": "empty", "value": ""},
    ]

    assert GeektimeHttpClient._cookie_header(cookies) == "valid=one; empty="
    assert GeektimeHttpClient._is_geektime_page(
        "https://time.geekbang.org/dashboard/usercenter"
    )
    assert not GeektimeHttpClient._is_geektime_page(
        "https://time.geekbang.org.example.com/dashboard/usercenter"
    )
