"""Spec adapters that normalize API descriptions into `Operation` objects."""

from universal_connector.adapters.base import SpecAdapter, detect_protocol, get_adapter

__all__ = ["SpecAdapter", "detect_protocol", "get_adapter"]
