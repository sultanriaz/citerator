"""FastAPI dependencies for Citerator with Tenant & User Identity Context.

Implements server-side tenant membership verification, role validation,
and default-deny authorization against forged headers.
"""

from __future__ import annotations

from typing import Any
import structlog
from fastapi import Depends, Header, HTTPException, status
from pydantic import BaseModel, Field

from citerator.config import Settings, get_settings

logger = structlog.get_logger(__name__)


class TenantContext(BaseModel):
    """Authenticated tenant and user identity context."""

    tenant_id: str = "global"
    user_id: str = "analyst_1"
    roles: list[str] = Field(default_factory=lambda: ["analyst"])
    is_admin: bool = False


# Server-side registry of known tenant API keys and their authorized scopes.
_SERVER_TENANT_KEYS: dict[str, dict[str, Any]] = {}


def register_tenant_key(
    api_key: str,
    tenant_id: str,
    *,
    is_admin: bool = False,
    allowed_tenants: list[str] | None = None,
) -> None:
    """Register or update an authorized API key with its server-side tenant binding."""
    _SERVER_TENANT_KEYS[api_key] = {
        "tenant_id": tenant_id,
        "is_admin": is_admin,
        "allowed_tenants": set(allowed_tenants or [tenant_id]),
    }


def clear_tenant_keys() -> None:
    """Clear registered tenant keys (used in tests)."""
    _SERVER_TENANT_KEYS.clear()


def get_tenant_context(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-Id"),
    x_user_id: str | None = Header(default=None, alias="X-User-Id"),
    x_user_role: str | None = Header(default=None, alias="X-User-Role"),
    settings: Settings = Depends(get_settings),
) -> TenantContext:
    if not x_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key",
        )

    # 1. Verify against server-side registered tenant keys or master key
    key_entry = _SERVER_TENANT_KEYS.get(x_api_key)
    is_master_key = (x_api_key == settings.api_key)

    if not key_entry and not is_master_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key",
        )

    # 2. Determine authorized tenant scope server-side
    requested_tenant = x_tenant_id.strip() if x_tenant_id else None

    if key_entry:
        authorized_tenant = key_entry["tenant_id"]
        allowed = key_entry.get("allowed_tenants", {authorized_tenant})
        key_is_admin = key_entry.get("is_admin", False)

        # Forgery check: client cannot assert a tenant outside its authorized set
        if requested_tenant and requested_tenant not in allowed:
            logger.warning(
                "tenant_forgery_detected",
                key_tenant=authorized_tenant,
                requested_tenant=requested_tenant,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Tenant forgery detected: API key is not authorized for tenant '{requested_tenant}'",
            )
        effective_tenant = requested_tenant or authorized_tenant
    else:
        # Master system API key (e.g. system administrator or internal service)
        key_is_admin = True
        effective_tenant = requested_tenant or "global"

    user_id = (x_user_id or "analyst_1").strip()
    role_str = (x_user_role or "analyst").strip().lower()
    roles = [r.strip() for r in role_str.split(",") if r.strip()]

    # Role forgery check: client cannot self-promote to admin unless authorized by key
    if "admin" in roles and not key_is_admin and effective_tenant != "global":
        logger.warning(
            "role_forgery_detected",
            user_id=user_id,
            tenant=effective_tenant,
            claimed_roles=roles,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Privilege escalation detected: unauthorized admin role claim",
        )

    is_admin = key_is_admin and ("admin" in roles or user_id == "admin" or effective_tenant == "global")

    return TenantContext(
        tenant_id=effective_tenant,
        user_id=user_id,
        roles=roles,
        is_admin=is_admin,
    )


def require_api_key(
    tenant: TenantContext = Depends(get_tenant_context),
) -> TenantContext:
    """Compatibility dependency that validates API key and returns TenantContext."""
    return tenant