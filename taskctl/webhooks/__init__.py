"""Webhook notification providers (Discord, Slack, Generic JSON)."""

from .dispatcher import WebhookDispatcher

__all__ = ["WebhookDispatcher"]
