"""
updater.py のユニットテスト（ネットワーク非依存のユニットテスト）
"""

import pytest

from timereaper.updater import _parse_release_version


class TestParseReleaseVersion:
    """_parse_release_version() のテスト"""

    def test_simple_version(self):
        """v0.7.0 → (0, 7, 0)"""
        assert _parse_release_version("v0.7.0") == (0, 7, 0)

    def test_rc_suffix(self):
        """-rc サフィックスを無視"""
        assert _parse_release_version("v0.7.3-rc") == (0, 7, 3)

    def test_no_v_prefix(self):
        """v 接頭辞なしのタグ"""
        assert _parse_release_version("1.2.3") == (1, 2, 3)

    def test_four_part_version(self):
        """4部構成バージョン"""
        assert _parse_release_version("v1.2.3.4") == (1, 2, 3, 4)

    def test_two_part_version(self):
        """2部構成バージョン"""
        assert _parse_release_version("v1.0") == (1, 0)

    def test_build_suffix(self):
        """+build サフィックスを無視"""
        assert _parse_release_version("v1.0.0+build123") == (1, 0, 0)

    def test_empty_string(self):
        """空文字列は空タプル"""
        assert _parse_release_version("") == ()

    def test_whitespace(self):
        """前後の空白を除去"""
        assert _parse_release_version("  v1.2.3  ") == (1, 2, 3)

    def test_comparison(self):
        """バージョン比較が正しく動く"""
        v1 = _parse_release_version("v0.7.0")
        v2 = _parse_release_version("v0.7.3-rc")
        v3 = _parse_release_version("v1.0.0")
        assert v1 < v2
        assert v2 < v3
        assert v1 < v3

    def test_equal_versions(self):
        """同じバージョンの比較"""
        v1 = _parse_release_version("v0.7.3")
        v2 = _parse_release_version("v0.7.3-rc")
        assert v1 == v2

    def test_prerelease_ignored(self):
        """RC とリリースは同じバージョンタプル"""
        assert _parse_release_version("v1.0.0-rc") == _parse_release_version("v1.0.0")
