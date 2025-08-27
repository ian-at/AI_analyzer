"""
Webhook模块 - 提供外部调用接口
用于根据patch_id和patch_set获取远端数据并进行智能分析
"""

from .handlers import WebhookHandler
from .models import SimplifiedWebhookResponse

__all__ = ['WebhookHandler', 'SimplifiedWebhookResponse']