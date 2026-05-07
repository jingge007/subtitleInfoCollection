from __future__ import annotations

from dataclasses import dataclass


class ErrorType:
    NETWORK_UNREACHABLE = "NETWORK_UNREACHABLE"
    RATE_LIMITED = "RATE_LIMITED"
    NO_MATCH = "NO_MATCH"
    PARSE_FAILED = "PARSE_FAILED"
    DOWNLOAD_BLOCKED = "DOWNLOAD_BLOCKED"
    DOWNLOAD_QUOTA_EXCEEDED = "DOWNLOAD_QUOTA_EXCEEDED"
    DOWNLOAD_FAILED = "DOWNLOAD_FAILED"
    PROVIDER_DISABLED = "PROVIDER_DISABLED"
    VERIFICATION_REQUIRED = "VERIFICATION_REQUIRED"
    INVALID_FORMAT = "INVALID_FORMAT"
    INVALID_LANGUAGE = "INVALID_LANGUAGE"
    DECODE_FAILED = "DECODE_FAILED"
    CONTENT_VALIDATION_FAILED = "CONTENT_VALIDATION_FAILED"


ERROR_TYPE_LABELS = {
    ErrorType.NETWORK_UNREACHABLE: "网络不可达",
    ErrorType.RATE_LIMITED: "访问频率受限",
    ErrorType.NO_MATCH: "没有匹配字幕",
    ErrorType.PARSE_FAILED: "解析失败",
    ErrorType.DOWNLOAD_BLOCKED: "下载被阻止",
    ErrorType.DOWNLOAD_QUOTA_EXCEEDED: "下载额度已用完",
    ErrorType.DOWNLOAD_FAILED: "下载失败",
    ErrorType.PROVIDER_DISABLED: "字幕源不可用",
    ErrorType.VERIFICATION_REQUIRED: "需要手动验证",
    ErrorType.INVALID_FORMAT: "字幕格式不符合要求",
    ErrorType.INVALID_LANGUAGE: "字幕语言不符合要求",
    ErrorType.DECODE_FAILED: "解码失败",
    ErrorType.CONTENT_VALIDATION_FAILED: "字幕内容校验失败",
}


@dataclass(slots=True)
class CollectorError(Exception):
    """采集错误基类"""
    message: str  # 错误消息
    error_type: str = ErrorType.PARSE_FAILED  # 错误类型
    provider: str = ""  # 字幕源提供商

    def __str__(self) -> str:
        prefix = f"[{self.provider}] " if self.provider else ""
        label = ERROR_TYPE_LABELS.get(self.error_type, "采集错误")
        return f"{prefix}{label}（{self.error_type}）：{self.message}"


@dataclass(slots=True)
class VerificationRequest:
    """验证请求数据类"""
    provider: str  # 字幕源提供商
    provider_subtitle_id: str  # 字幕源字幕ID
    subtitle_title: str  # 字幕标题
    detail_url: str  # 详情URL
    verification_html: str = ""  # 验证HTML


class VerificationRequiredError(CollectorError):
    """需要验证错误"""
    def __init__(self, request: VerificationRequest):
        super().__init__(
            message="字幕源需要手动验证",
            error_type=ErrorType.VERIFICATION_REQUIRED,
            provider=request.provider,
        )
        self.request = request


def classify_exception(error: Exception) -> str:
    if isinstance(error, CollectorError):
        return error.error_type

    message = str(error).lower()
    if any(token in message for token in ["quota", "remaining downloads", "download limit"]):
        return ErrorType.DOWNLOAD_QUOTA_EXCEEDED
    if any(token in message for token in ["429", "rate", "too many"]):
        return ErrorType.RATE_LIMITED
    if any(token in message for token in ["captcha", "verification", "login", "403", "forbidden"]):
        return ErrorType.DOWNLOAD_BLOCKED
    if any(token in message for token in ["timeout", "network", "connect", "dns", "unreachable"]):
        return ErrorType.NETWORK_UNREACHABLE
    if any(token in message for token in ["download", "zip", "archive", "save"]):
        return ErrorType.DOWNLOAD_FAILED
    if any(token in message for token in ["decode", "encoding"]):
        return ErrorType.DECODE_FAILED
    return ErrorType.PARSE_FAILED
