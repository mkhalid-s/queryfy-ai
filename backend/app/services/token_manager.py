"""
QueryfyAI - OAuth Token Manager

Manages OAuth tokens with automatic refresh before expiry
"""

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings
from app.models.schemas import LLMConfig

logger = logging.getLogger(__name__)


class TokenManager:
    """
    OAuth token management with:
    - Automatic token caching
    - Refresh before expiry (configurable buffer)
    - Support for multiple OAuth configurations
    """

    def __init__(self) -> None:
        self.tokens: Dict[str, Dict[str, Any]] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    def _get_config_hash(self, config: LLMConfig) -> str:
        """Create a unique hash for the OAuth configuration"""
        key = (
            f"{config.client_id}:{config.token_url}:{config.auth_scope}:{config.tenant}"
        )
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    def _get_lock(self, config_hash: str) -> asyncio.Lock:
        """Get or create a lock for a specific configuration"""
        if config_hash not in self._locks:
            self._locks[config_hash] = asyncio.Lock()
        return self._locks[config_hash]

    async def get_token(self, config: LLMConfig) -> str:
        """
        Get a valid access token, refreshing if needed.
        Thread-safe with per-config locking.
        """
        config_hash = self._get_config_hash(config)
        lock = self._get_lock(config_hash)

        async with lock:
            # Check if we have a valid cached token
            if config_hash in self.tokens:
                token_data = self.tokens[config_hash]
                buffer_time = timedelta(seconds=settings.TOKEN_REFRESH_BUFFER_SECONDS)

                if datetime.now() < token_data["expires_at"] - buffer_time:
                    logger.debug(f"Using cached token for config {config_hash[:8]}...")
                    return token_data["access_token"]
                else:
                    logger.info(
                        f"Token expiring soon for config {config_hash[:8]}..., refreshing"
                    )

            # Fetch new token
            token_data = await self._fetch_token(config)
            self.tokens[config_hash] = token_data

            logger.info(
                f"Token refreshed for config {config_hash[:8]}..., expires in {token_data['expires_in']}s"
            )
            return token_data["access_token"]

    async def _fetch_token(self, config: LLMConfig) -> Dict[str, Any]:
        """Fetch a new OAuth token from the token endpoint"""

        # Build request data based on auth type
        data = {
            "grant_type": config.auth_type or "client_credentials",
            "client_id": config.client_id,
            "client_secret": config.client_secret,
        }

        # Add optional fields
        if config.auth_scope:
            data["scope"] = config.auth_scope
        if config.tenant:
            data["tenant"] = config.tenant
        if config.star:
            data["star"] = config.star

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }

        try:
            if not config.token_url:
                raise ValueError("token_url is required for OAuth token refresh")

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    config.token_url, data=data, headers=headers
                )
                response.raise_for_status()

                token_response = response.json()
                expires_in = token_response.get("expires_in", 3600)

                return {
                    "access_token": token_response["access_token"],
                    "token_type": token_response.get("token_type", "Bearer"),
                    "expires_in": expires_in,
                    "expires_at": datetime.now() + timedelta(seconds=expires_in),
                    "obtained_at": datetime.now(),
                    "scope": token_response.get("scope"),
                    "refresh_token": token_response.get("refresh_token"),
                }

        except httpx.HTTPStatusError as e:
            logger.error(
                f"OAuth token request failed: {e.response.status_code} - {e.response.text}"
            )
            raise Exception(f"OAuth token request failed: {e.response.status_code}")
        except Exception as e:
            logger.error(f"OAuth token request error: {str(e)}")
            raise Exception(f"OAuth token request failed: {str(e)}")

    def invalidate_token(self, config: LLMConfig):
        """Invalidate a cached token (e.g., after auth failure)"""
        config_hash = self._get_config_hash(config)
        if config_hash in self.tokens:
            del self.tokens[config_hash]
            logger.info(f"Token invalidated for config {config_hash[:8]}...")

    def get_token_info(self, config: LLMConfig) -> Optional[Dict[str, Any]]:
        """Get information about the cached token"""
        config_hash = self._get_config_hash(config)
        token_data = self.tokens.get(config_hash)

        if not token_data:
            return None

        now = datetime.now()
        expires_at = token_data["expires_at"]

        return {
            "expires_at": expires_at.isoformat(),
            "obtained_at": token_data["obtained_at"].isoformat(),
            "expires_in_seconds": max(0, int((expires_at - now).total_seconds())),
            "is_expired": now >= expires_at,
            "scope": token_data.get("scope"),
        }

    def clear_all_tokens(self):
        """Clear all cached tokens"""
        self.tokens.clear()
        logger.info("All cached tokens cleared")


# Global token manager instance
token_manager = TokenManager()
