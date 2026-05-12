"""Tests for deepseek_toolkit.balance — account balance query."""
from unittest.mock import patch, MagicMock
import pytest


class TestBalanceInfo:
    def test_balance_info_holds_all_fields(self):
        from deepseek_toolkit.balance import BalanceInfo
        info = BalanceInfo(
            total_balance="100.00",
            topped_up_balance="80.00",
            granted_balance="20.00",
            currency="CNY",
            is_available=True,
            queried_at=1700000000.0,
        )
        assert info.total_balance == "100.00"
        assert info.topped_up_balance == "80.00"
        assert info.granted_balance == "20.00"
        assert info.currency == "CNY"
        assert info.is_available is True
        assert info.queried_at == 1700000000.0

    def test_balance_info_default_values(self):
        from deepseek_toolkit.balance import BalanceInfo
        info = BalanceInfo()
        assert info.total_balance == "0.00"
        assert info.currency == "CNY"
        assert info.is_available is False


class TestGetBalance:
    def test_get_balance_returns_balance_info(self):
        from deepseek_toolkit.balance import get_balance, BalanceInfo

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "is_available": True,
            "balance_infos": [{
                "currency": "CNY",
                "total_balance": "100.00",
                "topped_up_balance": "80.00",
                "granted_balance": "20.00",
            }],
        }

        with patch("deepseek_toolkit.balance.requests.get", return_value=mock_resp):
            info = get_balance(api_key="sk-test")
            assert isinstance(info, BalanceInfo)
            assert info.total_balance == "100.00"
            assert info.is_available is True
            assert info.currency == "CNY"

    def test_get_balance_cache_returns_cached_value(self):
        from deepseek_toolkit.balance import get_balance
        from deepseek_toolkit.balance import _balance_cache

        _balance_cache.clear()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "is_available": True,
            "balance_infos": [{
                "currency": "CNY",
                "total_balance": "50.00",
                "topped_up_balance": "50.00",
                "granted_balance": "0.00",
            }],
        }

        with patch("deepseek_toolkit.balance.requests.get", return_value=mock_resp) as mock_get:
            info1 = get_balance(api_key="sk-test")
            info2 = get_balance(api_key="sk-test")
            assert mock_get.call_count == 1

        _balance_cache.clear()

    def test_get_balance_cache_expires(self):
        from deepseek_toolkit.balance import get_balance
        from deepseek_toolkit.balance import _balance_cache, CACHE_TTL

        _balance_cache.clear()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "is_available": True,
            "balance_infos": [{
                "currency": "CNY",
                "total_balance": "50.00",
                "topped_up_balance": "50.00",
                "granted_balance": "0.00",
            }],
        }

        with patch("deepseek_toolkit.balance.requests.get", return_value=mock_resp) as mock_get:
            with patch("deepseek_toolkit.balance.time.time", side_effect=[1000.0, 1000.0 + CACHE_TTL + 1]):
                get_balance(api_key="sk-test")
                get_balance(api_key="sk-test")
                assert mock_get.call_count == 2

        _balance_cache.clear()

    def test_get_balance_handles_401(self):
        from deepseek_toolkit.balance import get_balance
        from deepseek_toolkit.errors import AuthenticationError

        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {"error": "Invalid API key"}

        with patch("deepseek_toolkit.balance.requests.get", return_value=mock_resp):
            with pytest.raises(AuthenticationError):
                get_balance(api_key="sk-invalid")
