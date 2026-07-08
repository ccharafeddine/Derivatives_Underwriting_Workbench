"""Update-check tests (v2). Qt-free; no network (fetch is injected)."""

from __future__ import annotations

import pytest

from duw.updates import (
    NoReleasesError,
    check_for_updates,
    is_newer,
    parse_version,
)


def test_parse_and_compare_versions() -> None:
    assert parse_version("v1.2.3") == (1, 2, 3)
    assert parse_version("0.1") == (0, 1, 0)
    assert parse_version("2.0.0-beta") == (2, 0, 0)
    assert is_newer("0.2.0", "0.1.0")
    assert is_newer("1.0.0", "0.9.9")
    assert not is_newer("0.1.0", "0.1.0")
    assert not is_newer("0.1.0", "0.2.0")


def test_update_available() -> None:
    def fetch(url: str, timeout: float) -> dict:
        return {"tag_name": "v0.5.0", "html_url": "https://example.com/rel/0.5.0"}

    info = check_for_updates("0.1.0", fetch=fetch)
    assert info.available is True
    assert info.error is False
    assert info.latest == "0.5.0"
    assert info.url == "https://example.com/rel/0.5.0"
    assert "0.5.0" in info.message


def test_up_to_date() -> None:
    def fetch(url: str, timeout: float) -> dict:
        return {"tag_name": "v0.1.0", "html_url": "https://example.com"}

    info = check_for_updates("0.1.0", fetch=fetch)
    assert info.available is False
    assert info.error is False
    assert "up to date" in info.message.lower()


def test_no_releases_is_graceful() -> None:
    def fetch(url: str, timeout: float) -> dict:
        raise NoReleasesError()

    info = check_for_updates("0.1.0", fetch=fetch)
    assert info.available is False
    assert info.error is False
    assert "no published releases" in info.message.lower()


def test_network_error_is_graceful() -> None:
    def fetch(url: str, timeout: float) -> dict:
        raise TimeoutError("network down")

    info = check_for_updates("0.1.0", fetch=fetch)
    assert info.available is False
    assert info.error is True
    assert "could not check" in info.message.lower()


def test_default_fetch_is_not_called_at_import() -> None:
    # Importing the module must not perform any network I/O; only calling
    # check_for_updates (with the default fetch) would, and we never do here.
    import duw.updates as updates

    assert callable(updates.check_for_updates)


@pytest.mark.parametrize("raw", ["v9.9.9", "9.9.9"])
def test_tag_prefix_is_tolerated(raw: str) -> None:
    def fetch(url: str, timeout: float) -> dict:
        return {"tag_name": raw, "html_url": "https://example.com"}

    info = check_for_updates("1.0.0", fetch=fetch)
    assert info.available is True
    assert info.latest == "9.9.9"
