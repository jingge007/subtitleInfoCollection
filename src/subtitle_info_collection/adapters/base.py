from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol

from ..errors import VerificationRequest, VerificationResult
from ..models import DownloadedPayload, MovieInfo, SubtitleCandidate


RequestVerificationCallback = Callable[[VerificationRequest], Awaitable[VerificationResult]]
LogCallback = Callable[[str], None]


@dataclass(slots=True)
class ProviderHealth:
    """字幕源健康状态数据类"""
    provider: str  # 字幕源提供商
    enabled: bool  # 是否启用
    healthy: bool  # 是否健康
    error_type: str = ""  # 错误类型
    message: str = ""  # 消息

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "enabled": self.enabled,
            "healthy": self.healthy,
            "errorType": self.error_type,
            "message": self.message,
        }


@dataclass(slots=True)
class DownloadContext:
    """下载上下文数据类"""
    request_interval_ms: int = 13_000  # 请求间隔（毫秒）
    request_verification: RequestVerificationCallback | None = None  # 验证请求回调
    log: LogCallback | None = None  # 日志回调
    captcha_ocr_enabled: bool = True
    captcha_auto_submit_min_confidence: float = 0.85


class ProviderAdapter(Protocol):
    """字幕源适配器协议"""
    id: str  # 字幕源ID
    download_supported: bool  # 是否支持下载

    async def health(self) -> ProviderHealth:
        """检查字幕源健康状态"""
        ...

    async def search(self, movie: MovieInfo) -> list[SubtitleCandidate]:
        """搜索字幕候选"""
        ...

    async def download(
        self, candidate: SubtitleCandidate, context: DownloadContext
    ) -> list[DownloadedPayload]:
        """下载字幕"""
        ...
