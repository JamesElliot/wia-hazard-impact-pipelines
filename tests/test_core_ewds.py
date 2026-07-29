from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from wia_pipelines.core.ewds import (
    DEFAULT_EWDS_URL,
    download_ewds,
    read_ewds_credentials,
    resolve_ewds_credentials,
)


class ReadEwdsCredentialsTests(unittest.TestCase):
    def test_missing_file_returns_none(self) -> None:
        with TemporaryDirectory() as td:
            missing = Path(td) / "does_not_exist.rc"
            self.assertIsNone(read_ewds_credentials(missing))

    def test_reads_url_and_key(self) -> None:
        with TemporaryDirectory() as td:
            rc = Path(td) / ".ewdsapirc"
            rc.write_text("url: https://example.test/api\nkey: abc123\n", encoding="utf-8")
            creds = read_ewds_credentials(rc)
            self.assertEqual(creds, {"url": "https://example.test/api", "key": "abc123"})

    def test_missing_url_defaults_to_public_endpoint(self) -> None:
        with TemporaryDirectory() as td:
            rc = Path(td) / ".ewdsapirc"
            rc.write_text("key: abc123\n", encoding="utf-8")
            creds = read_ewds_credentials(rc)
            self.assertEqual(creds["url"], DEFAULT_EWDS_URL)

    def test_key_only_file_without_url_line(self) -> None:
        with TemporaryDirectory() as td:
            rc = Path(td) / ".ewdsapirc"
            rc.write_text("# comment\nkey: xyz\n", encoding="utf-8")
            creds = read_ewds_credentials(rc)
            self.assertEqual(creds["key"], "xyz")


class ResolveEwdsCredentialsTests(unittest.TestCase):
    def test_explicit_args_win(self) -> None:
        url, key = resolve_ewds_credentials(url="https://explicit", key="explicit-key")
        self.assertEqual(url, "https://explicit")
        self.assertEqual(key, "explicit-key")

    def test_falls_back_to_rc_file(self) -> None:
        with TemporaryDirectory() as td:
            rc = Path(td) / ".ewdsapirc"
            rc.write_text("url: https://rc-url\nkey: rc-key\n", encoding="utf-8")
            url, key = resolve_ewds_credentials(rc_path=rc)
            self.assertEqual(url, "https://rc-url")
            self.assertEqual(key, "rc-key")

    def test_no_credentials_anywhere_returns_none_key(self) -> None:
        with TemporaryDirectory() as td:
            missing = Path(td) / "nope.rc"
            _url, key = resolve_ewds_credentials(rc_path=missing)
            self.assertIsNone(key)


class DownloadEwdsTests(unittest.TestCase):
    def test_no_credentials_returns_explanatory_failure_without_network_call(self) -> None:
        with TemporaryDirectory() as td:
            out_zip = Path(td) / "out.zip"
            missing_rc = Path(td) / "nope.rc"
            ok, err = download_ewds("cems-glofas-historical", {"a": 1}, out_zip, rc_path=missing_rc)
            self.assertFalse(ok)
            self.assertIn("No EWDS credentials found", err)

    def test_download_ewds_maps_client_exception_to_failure_tuple(self) -> None:
        # Mirrors test_cds.py's equivalent for download_cds: the actual
        # network boundary (cdsapi.Client construction/retrieve) is never
        # exercised elsewhere in this suite, so this confirms a raised
        # exception is caught and returned as (False, message), not
        # propagated as a raw traceback.
        class _RaisingClient:
            def __init__(self, *args, **kwargs):
                raise ConnectionError("simulated EWDS network failure")

        fake_cdsapi = type("fake_cdsapi", (), {"Client": _RaisingClient})

        with TemporaryDirectory() as td:
            out_zip = Path(td) / "out.zip"
            with patch("wia_pipelines.core.ewds._require", return_value=fake_cdsapi):
                ok, err = download_ewds("cems-glofas-historical", {"a": 1}, out_zip, url="https://x", key="k")
            self.assertFalse(ok)
            self.assertIn("simulated EWDS network failure", err)


if __name__ == "__main__":
    unittest.main()
