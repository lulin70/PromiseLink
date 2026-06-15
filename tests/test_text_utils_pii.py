"""Tests for redact_pii_from_text() PII detection and masking."""

import pytest

from promiselink.core.text_utils import redact_pii_from_text


class TestPhoneRedaction:
    """手机号脱敏测试"""

    def test_standard_phone(self):
        assert redact_pii_from_text("我的手机号是13812341234") == "我的手机号是138****1234"

    def test_phone_with_prefix_15(self):
        assert redact_pii_from_text("号码15900001111") == "号码159****1111"

    def test_phone_with_prefix_18(self):
        assert redact_pii_from_text("电话18600001234") == "电话186****1234"

    def test_phone_with_prefix_13(self):
        assert redact_pii_from_text("手机13000001234") == "手机130****1234"

    def test_phone_not_match_12_prefix(self):
        """12开头的不是手机号，不应匹配"""
        text = "号码12000001234"
        assert redact_pii_from_text(text) == text

    def test_phone_not_match_short(self):
        """不足11位不应匹配"""
        text = "号码1381234123"
        assert redact_pii_from_text(text) == text


class TestEmailRedaction:
    """邮箱脱敏测试"""

    def test_simple_email(self):
        assert redact_pii_from_text("邮箱是user@example.com") == "邮箱是u***@example.com"

    def test_email_with_dots_in_local(self):
        assert redact_pii_from_text("联系first.last@company.cn") == "联系f***@company.cn"

    def test_email_with_plus(self):
        assert redact_pii_from_text("邮箱test+tag@gmail.com") == "邮箱t***@gmail.com"

    def test_email_with_subdomain(self):
        assert redact_pii_from_text("邮箱admin@mail.company.com") == "邮箱a***@mail.company.com"


class TestIDCardRedaction:
    """身份证号脱敏测试"""

    def test_standard_id_card(self):
        result = redact_pii_from_text("身份证310101199001011234")
        assert result == "身份证310***********1234"

    def test_id_card_ending_with_x(self):
        result = redact_pii_from_text("身份证11010120001231234X")
        assert result == "身份证110***********234X"

    def test_id_card_ending_with_lowercase_x(self):
        result = redact_pii_from_text("身份证44010119991231234x")
        assert result == "身份证440***********234x"


class TestBankCardRedaction:
    """银行卡号脱敏测试"""

    def test_16_digit_card(self):
        assert redact_pii_from_text("卡号6222021234561234") == "卡号********1234"

    def test_19_digit_card(self):
        assert redact_pii_from_text("卡号6222021234567891234") == "卡号********1234"

    def test_18_digit_card(self):
        assert redact_pii_from_text("卡号622202123456781234") == "卡号********1234"


class TestWeChatRedaction:
    """微信号脱敏测试"""

    def test_wechat_with_chinese_label(self):
        assert redact_pii_from_text("微信号：zhangsan123") == "微信号：wx_***23"

    def test_wechat_with_colon(self):
        assert redact_pii_from_text("微信：abc_def12") == "微信：wx_***12"

    def test_wechat_english_label(self):
        assert redact_pii_from_text("wechat: testuser1") == "wechat: wx_***r1"

    def test_wechat_mixed_case_label(self):
        assert redact_pii_from_text("WeChat: MyAccount99") == "WeChat: wx_***99"

    def test_wechat_not_matched_without_label(self):
        """没有微信标签的普通ID不应被匹配"""
        text = "我的ID是zhangsan123"
        assert redact_pii_from_text(text) == text

    def test_wechat_too_short(self):
        """太短的微信号不应匹配（需6-20位）"""
        text = "微信号：abc12"
        assert redact_pii_from_text(text) == text


class TestMixedPII:
    """混合PII脱敏测试"""

    def test_multiple_pii_types(self):
        text = "手机13812341234，邮箱user@example.com，身份证310101199001011234"
        result = redact_pii_from_text(text)
        assert "138****1234" in result
        assert "u***@example.com" in result
        assert "310***********1234" in result

    def test_all_five_types(self):
        text = (
            "手机13812341234，邮箱user@example.com，"
            "身份证310101199001011234，卡号6222021234561234，"
            "微信号：zhangsan123"
        )
        result = redact_pii_from_text(text)
        assert "138****1234" in result
        assert "u***@example.com" in result
        assert "310***********1234" in result
        assert "********1234" in result
        assert "wx_***23" in result


class TestNoPII:
    """无PII文本不应被修改"""

    def test_plain_text(self):
        text = "今天天气真好，适合出去散步"
        assert redact_pii_from_text(text) == text

    def test_empty_string(self):
        assert redact_pii_from_text("") == ""

    def test_numbers_not_pii(self):
        """普通短数字不应被误匹配"""
        text = "数量123个，价格456元"
        assert redact_pii_from_text(text) == text

    def test_partial_phone_not_matched(self):
        """不完整的手机号不应匹配"""
        text = "号码1381234"
        assert redact_pii_from_text(text) == text

    def test_15_digit_number_not_bank_card(self):
        """15位数字不应被银行卡号模式匹配"""
        text = "编号123456789012345"
        assert redact_pii_from_text(text) == text
