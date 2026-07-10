"""Workspace adapter binding configuration system.

Production-grade adapter configuration engine managing workspace-specific bindings
for capabilities and methods. Features:

- Workspace-level overrides of default bindings
- Multi-adapter fallback chains (by priority)
- Adapter-specific configuration with encryption for sensitive fields
- Versioned, audited configuration changes
- Multi-tenant safety with isolated access per workspace
- Adapter validation with connection testing
- Comprehensive audit trail (who, what, when, reason)

Each binding maps a capability (optionally scoped to a method) to a specific adapter
method, with priority-based selection and enable/disable control. Sensitive
configuration (API keys, credentials) is encrypted at rest and only decrypted
when needed.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import threading
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Optional

try:
    from ..secrets.vault import SecretVault
except ImportError:
    SecretVault = None

logger = logging.getLogger(__name__)


class AuditEventType(str, Enum):
    """Types of audit events for adapter binding changes."""
    BINDING_CREATED = "binding_created"
    BINDING_UPDATED = "binding_updated"
    BINDING_ENABLED = "binding_enabled"
    BINDING_DISABLED = "binding_disabled"
    PRIORITY_CHANGED = "priority_changed"
    CONFIG_UPDATED = "config_updated"
    VALIDATION_TESTED = "validation_tested"
    BINDING_DELETED = "binding_deleted"


@dataclass
class AuditEvent:
    """Audit trail record for a binding configuration change.

    Attributes:
        event_type: Type of event (created, updated, enabled, disabled, etc.)
        workspace_id: Workspace identifier
        capability_id: Capability identifier
        adapter_id: Adapter identifier
        actor_id: User/system identifier making the change
        actor_role: Role of the actor (admin, system, etc.)
        timestamp: ISO timestamp when event occurred
        reason: Optional reason for the change
        old_value: Previous configuration value (if applicable)
        new_value: New configuration value (if applicable)
        details: Additional context as a dictionary
    """
    event_type: AuditEventType
    workspace_id: str
    capability_id: str
    adapter_id: str
    actor_id: str
    actor_role: str = "system"
    timestamp: str = field(default_factory=lambda: datetime.datetime.now(datetime.UTC).isoformat())
    reason: Optional[str] = None
    old_value: Optional[Any] = None
    new_value: Optional[Any] = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary, serializing event_type."""
        data = asdict(self)
        data["event_type"] = self.event_type.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuditEvent:
        """Create from dictionary, converting event_type."""
        data_copy = data.copy()
        if isinstance(data_copy.get("event_type"), str):
            data_copy["event_type"] = AuditEventType(data_copy["event_type"])
        return cls(**data_copy)


class AdapterValidationError(RuntimeError):
    """Raised when adapter validation fails."""
    pass


@dataclass
class ValidationResult:
    """Result of adapter validation/connection test.

    Attributes:
        is_valid: Whether the adapter configuration is valid
        success: Whether the connection test succeeded
        error: Error message if validation failed
        details: Additional validation details
        tested_at: ISO timestamp when test was performed
    """
    is_valid: bool
    success: bool
    error: Optional[str] = None
    details: dict[str, Any] = field(default_factory=dict)
    tested_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AdapterBinding:
    """Configuration binding between a capability/method and an adapter.

    Secure, audited binding for adapter selection and configuration per workspace.
    Sensitive fields (API keys, credentials) are marked and can be encrypted at rest.

    Attributes:
        workspace_id: Workspace identifier (tenant)
        capability_id: Capability identifier (e.g., "communication", "approval")
        method_name: Specific method within capability (e.g., "send_message").
                    None = all methods in capability
        adapter_id: Adapter identifier (e.g., "whatsapp", "email", "odoo")
        adapter_method: Method name on adapter (e.g., "send", "create_lead")
        priority: Lower number = higher priority (preferred)
        enabled: Whether this binding is active
        configuration: Adapter-specific configuration dict
        sensitive_fields: List of config keys that contain sensitive data (encrypted)
        version: Configuration version for auditing
        created_at: ISO timestamp
        updated_at: ISO timestamp
        created_by: User/system identifier who created this binding
        updated_by: User/system identifier who last updated this binding
        last_validated_at: ISO timestamp of last successful validation
        validation_status: Current validation status
    """
    workspace_id: str
    capability_id: str
    adapter_id: str
    adapter_method: str
    priority: int = 10
    enabled: bool = True
    configuration: dict[str, Any] = field(default_factory=dict)
    method_name: Optional[str] = None
    sensitive_fields: list[str] = field(default_factory=list)  # e.g., ['api_key', 'password']
    version: int = 1
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.UTC).isoformat())
    created_by: str = "system"
    updated_by: str = "system"
    last_validated_at: Optional[str] = None
    validation_status: Optional[str] = None  # 'valid', 'invalid', 'untested'

    def to_dict(self) -> dict[str, Any]:
        """Convert binding to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AdapterBinding:
        """Create binding from dictionary."""
        return cls(**data)

    def key(self) -> str:
        """Get unique key for this binding."""
        method_part = f":{self.method_name}" if self.method_name else ":*"
        return f"{self.workspace_id}:{self.capability_id}{method_part}:{self.adapter_id}"

    def get_sensitive_values(self) -> dict[str, Any]:
        """Extract sensitive configuration values for encryption."""
        return {
            field: self.configuration.get(field)
            for field in self.sensitive_fields
            if field in self.configuration
        }

    def set_sensitive_values(self, encrypted_values: dict[str, Any]) -> None:
        """Restore sensitive configuration values from decryption."""
        for field, value in encrypted_values.items():
            if field in self.sensitive_fields:
                self.configuration[field] = value


class AdapterBindingRegistry:
    """Production-grade adapter binding registry for multi-tenant workspaces.

    Manages the complete binding configuration with support for:
    - Workspace-level overrides (multi-tenant safe)
    - Priority-based adapter selection and fallback chains
    - Versioned configuration with comprehensive audit trail
    - Encrypted sensitive configuration at rest
    - Adapter validation and connection testing
    - Admin control over adapter selection per capability

    All changes are logged with actor ID, role, timestamp, and reason. Sensitive
    configuration fields are encrypted using a SecretVault when available.
    """

    # Default bindings (all workspaces, can be overridden per workspace)
    DEFAULT_BINDINGS = [
        # Communication: WhatsApp, Email, Slack (by method)
        AdapterBinding(
            workspace_id="_default",
            capability_id="communication",
            method_name="send_whatsapp",
            adapter_id="whatsapp",
            adapter_method="send_message",
            priority=1,
            configuration={"channel": "whatsapp"}
        ),
        AdapterBinding(
            workspace_id="_default",
            capability_id="communication",
            method_name="send_email",
            adapter_id="email",
            adapter_method="send_message",
            priority=1,
            configuration={"channel": "email"}
        ),
        AdapterBinding(
            workspace_id="_default",
            capability_id="communication",
            method_name="send_slack",
            adapter_id="slack",
            adapter_method="send_message",
            priority=1,
            configuration={"channel": "slack"}
        ),
        # Communication: fallback chain (no specific method)
        AdapterBinding(
            workspace_id="_default",
            capability_id="communication",
            adapter_id="whatsapp",
            adapter_method="send_message",
            priority=1,
            configuration={}
        ),
        AdapterBinding(
            workspace_id="_default",
            capability_id="communication",
            adapter_id="email",
            adapter_method="send_message",
            priority=2,
            configuration={}
        ),
        AdapterBinding(
            workspace_id="_default",
            capability_id="communication",
            adapter_id="slack",
            adapter_method="send_message",
            priority=3,
            configuration={}
        ),

        # Approval: Email, Slack
        AdapterBinding(
            workspace_id="_default",
            capability_id="approval",
            method_name="send_approval",
            adapter_id="email",
            adapter_method="send_approval",
            priority=1,
            configuration={}
        ),
        AdapterBinding(
            workspace_id="_default",
            capability_id="approval",
            method_name="send_approval",
            adapter_id="slack",
            adapter_method="send_approval",
            priority=2,
            configuration={}
        ),

        # Procurement: Odoo, SAP (configurable)
        AdapterBinding(
            workspace_id="_default",
            capability_id="procurement",
            method_name="create_purchase_order",
            adapter_id="odoo",
            adapter_method="create_purchase_order",
            priority=1,
            configuration={}
        ),
        AdapterBinding(
            workspace_id="_default",
            capability_id="procurement",
            method_name="create_purchase_order",
            adapter_id="sap",
            adapter_method="create_purchase_order",
            priority=2,
            configuration={}
        ),

        # Finance: SAP, Oracle (configurable)
        AdapterBinding(
            workspace_id="_default",
            capability_id="finance",
            method_name="create_invoice",
            adapter_id="sap",
            adapter_method="create_invoice",
            priority=1,
            configuration={}
        ),
        AdapterBinding(
            workspace_id="_default",
            capability_id="finance",
            method_name="create_invoice",
            adapter_id="oracle",
            adapter_method="create_invoice",
            priority=2,
            configuration={}
        ),
        AdapterBinding(
            workspace_id="_default",
            capability_id="finance",
            method_name="post_journal_entry",
            adapter_id="sap",
            adapter_method="post_journal_entry",
            priority=1,
            configuration={}
        ),

        # Inventory: Odoo, SAP
        AdapterBinding(
            workspace_id="_default",
            capability_id="inventory",
            method_name="update_stock",
            adapter_id="odoo",
            adapter_method="update_stock",
            priority=1,
            configuration={}
        ),
        AdapterBinding(
            workspace_id="_default",
            capability_id="inventory",
            method_name="update_stock",
            adapter_id="sap",
            adapter_method="update_stock",
            priority=2,
            configuration={}
        ),

        # CRM: Salesforce, Pipedrive, Odoo
        AdapterBinding(
            workspace_id="_default",
            capability_id="crm",
            method_name="create_lead",
            adapter_id="salesforce",
            adapter_method="create_lead",
            priority=1,
            configuration={}
        ),
        AdapterBinding(
            workspace_id="_default",
            capability_id="crm",
            method_name="create_lead",
            adapter_id="pipedrive",
            adapter_method="create_lead",
            priority=2,
            configuration={}
        ),
        AdapterBinding(
            workspace_id="_default",
            capability_id="crm",
            method_name="create_lead",
            adapter_id="odoo",
            adapter_method="create_lead",
            priority=3,
            configuration={}
        ),
        AdapterBinding(
            workspace_id="_default",
            capability_id="crm",
            method_name="update_contact",
            adapter_id="salesforce",
            adapter_method="update_contact",
            priority=1,
            configuration={}
        ),

        # Documents: SharePoint, Google Drive
        AdapterBinding(
            workspace_id="_default",
            capability_id="documents",
            method_name="store_document",
            adapter_id="sharepoint",
            adapter_method="upload_document",
            priority=1,
            configuration={}
        ),
        AdapterBinding(
            workspace_id="_default",
            capability_id="documents",
            method_name="store_document",
            adapter_id="google_drive",
            adapter_method="upload_document",
            priority=2,
            configuration={}
        ),
    ]

    def __init__(
        self,
        vault: Optional[SecretVault] = None,
        validator: Optional[Callable[[AdapterBinding], ValidationResult]] = None,
    ) -> None:
        """Initialize the adapter binding registry.

        Args:
            vault: Optional SecretVault for encrypting sensitive configuration.
                  If not provided, sensitive fields are stored in plaintext.
            validator: Optional callable to validate adapter connections.
                      Signature: (binding: AdapterBinding) -> ValidationResult
        """
        self._bindings: dict[str, list[AdapterBinding]] = {}
        self._lock = threading.RLock()
        self._version_counter: dict[str, int] = {}
        self._audit_trail: list[AuditEvent] = []
        self._vault = vault or self._init_vault_from_env()
        self._validator = validator
        self._workspace_configs: dict[str, dict[str, Any]] = {}  # workspace_id -> config

        # Load default bindings
        for binding in self.DEFAULT_BINDINGS:
            self._add_binding_internal(binding)

        logger.info("AdapterBindingRegistry initialized with %d default bindings", len(self.DEFAULT_BINDINGS))

    @staticmethod
    def _init_vault_from_env() -> Optional[SecretVault]:
        """Attempt to initialize vault from environment."""
        if SecretVault and os.environ.get("NIL_VAULT_KEY"):
            try:
                return SecretVault.from_env()
            except Exception as e:
                logger.warning("Failed to initialize SecretVault: %s", e)
        return None

    def _add_binding_internal(self, binding: AdapterBinding) -> None:
        """Internal method to add binding without version increment."""
        key = self._make_key(binding.workspace_id, binding.capability_id, binding.method_name)
        if key not in self._bindings:
            self._bindings[key] = []
        # Avoid duplicates
        existing = [b for b in self._bindings[key]
                   if b.adapter_id == binding.adapter_id]
        if not existing:
            self._bindings[key].append(binding)

    @staticmethod
    def _make_key(workspace_id: str, capability_id: str, method_name: Optional[str]) -> str:
        """Create a lookup key for bindings."""
        method_part = f":{method_name}" if method_name else ":*"
        return f"{workspace_id}:{capability_id}{method_part}"

    def get(
        self,
        workspace_id: str,
        capability_id: str,
        method_name: Optional[str] = None,
    ) -> Optional[AdapterBinding]:
        """Get the highest-priority enabled binding matching criteria.

        Resolves in order:
        1. Workspace-specific binding for (capability, method)
        2. Workspace-specific binding for capability (any method)
        3. Default binding for (capability, method)
        4. Default binding for capability (any method)

        Args:
            workspace_id: Workspace identifier
            capability_id: Capability identifier
            method_name: Optional specific method name

        Returns:
            The highest-priority enabled AdapterBinding, or None if not found
        """
        with self._lock:
            # Try workspace-specific with method
            key = self._make_key(workspace_id, capability_id, method_name)
            bindings = self._bindings.get(key, [])
            if bindings:
                sorted_bindings = sorted(
                    [b for b in bindings if b.enabled],
                    key=lambda b: b.priority
                )
                if sorted_bindings:
                    return sorted_bindings[0]

            # Try workspace-specific without method
            if method_name:
                key_any = self._make_key(workspace_id, capability_id, None)
                bindings = self._bindings.get(key_any, [])
                if bindings:
                    sorted_bindings = sorted(
                        [b for b in bindings if b.enabled],
                        key=lambda b: b.priority
                    )
                    if sorted_bindings:
                        return sorted_bindings[0]

            # Try defaults with method
            key_default = self._make_key("_default", capability_id, method_name)
            bindings = self._bindings.get(key_default, [])
            if bindings:
                sorted_bindings = sorted(
                    [b for b in bindings if b.enabled],
                    key=lambda b: b.priority
                )
                if sorted_bindings:
                    return sorted_bindings[0]

            # Try defaults without method
            if method_name:
                key_default_any = self._make_key("_default", capability_id, None)
                bindings = self._bindings.get(key_default_any, [])
                if bindings:
                    sorted_bindings = sorted(
                        [b for b in bindings if b.enabled],
                        key=lambda b: b.priority
                    )
                    if sorted_bindings:
                        return sorted_bindings[0]

            return None

    def get_all_matching(
        self,
        workspace_id: str,
        capability_id: str,
        method_name: Optional[str] = None,
    ) -> list[AdapterBinding]:
        """Get all enabled bindings matching criteria, sorted by priority.

        Includes both workspace-specific and default bindings.

        Args:
            workspace_id: Workspace identifier
            capability_id: Capability identifier
            method_name: Optional specific method name

        Returns:
            List of AdapterBindings sorted by priority (lowest first)
        """
        with self._lock:
            results = []

            # Collect workspace-specific with method
            key = self._make_key(workspace_id, capability_id, method_name)
            results.extend([b for b in self._bindings.get(key, []) if b.enabled])

            # Collect workspace-specific without method (if method given)
            if method_name:
                key_any = self._make_key(workspace_id, capability_id, None)
                results.extend([b for b in self._bindings.get(key_any, []) if b.enabled])

            # Collect defaults with method
            key_default = self._make_key("_default", capability_id, method_name)
            results.extend([b for b in self._bindings.get(key_default, []) if b.enabled])

            # Collect defaults without method (if method given)
            if method_name:
                key_default_any = self._make_key("_default", capability_id, None)
                results.extend([b for b in self._bindings.get(key_default_any, []) if b.enabled])

            # Deduplicate and sort
            seen = set()
            unique_results = []
            for b in sorted(results, key=lambda x: x.priority):
                binding_id = (b.workspace_id, b.capability_id, b.method_name, b.adapter_id)
                if binding_id not in seen:
                    seen.add(binding_id)
                    unique_results.append(b)

            return unique_results

    def _record_audit_event(self, event: AuditEvent) -> None:
        """Record an audit event to the trail."""
        with self._lock:
            self._audit_trail.append(event)
            logger.info(
                "Audit: %s for workspace=%s capability=%s adapter=%s by %s (%s)",
                event.event_type.value,
                event.workspace_id,
                event.capability_id,
                event.adapter_id,
                event.actor_id,
                event.actor_role,
            )

    def _encrypt_binding(self, binding: AdapterBinding) -> None:
        """Encrypt sensitive configuration fields if vault is available."""
        if not self._vault or not binding.sensitive_fields:
            return

        try:
            sensitive_values = binding.get_sensitive_values()
            if sensitive_values:
                # Store encrypted sensitive values in vault
                vault_key = f"{binding.workspace_id}:binding:{binding.capability_id}:{binding.adapter_id}"
                self._vault.put(vault_key, sensitive_values)
                # Remove from plaintext config
                for field in binding.sensitive_fields:
                    binding.configuration.pop(field, None)
        except Exception as e:
            logger.warning("Failed to encrypt binding config: %s", e)

    def _decrypt_binding(self, binding: AdapterBinding) -> None:
        """Decrypt sensitive configuration fields if vault is available."""
        if not self._vault or not binding.sensitive_fields:
            return

        try:
            vault_key = f"{binding.workspace_id}:binding:{binding.capability_id}:{binding.adapter_id}"
            encrypted_values = self._vault.get(vault_key)
            if encrypted_values:
                binding.set_sensitive_values(encrypted_values)
        except Exception as e:
            logger.warning("Failed to decrypt binding config: %s", e)

    def set(
        self,
        binding: AdapterBinding,
        actor_id: str = "system",
        actor_role: str = "system",
        reason: Optional[str] = None,
    ) -> None:
        """Set or update an adapter binding with audit logging.

        If a binding for the same (workspace, capability, method, adapter) exists,
        it is updated. Otherwise, a new binding is created with an incremented version.
        All changes are recorded in the audit trail.

        Args:
            binding: AdapterBinding to set
            actor_id: User/system identifier making the change
            actor_role: Role of the actor (admin, system, automation, etc.)
            reason: Optional reason for the change
        """
        with self._lock:
            # Validate workspace isolation
            if not binding.workspace_id or binding.workspace_id.startswith("__"):
                raise ValueError(f"Invalid workspace_id: {binding.workspace_id}")

            key = self._make_key(binding.workspace_id, binding.capability_id, binding.method_name)
            version_key = f"{key}:{binding.adapter_id}"

            # Find existing binding for audit purposes
            existing_binding = None
            if key in self._bindings:
                for b in self._bindings[key]:
                    if b.adapter_id == binding.adapter_id:
                        existing_binding = b
                        break

            # Increment version for new or updated bindings
            if version_key not in self._version_counter:
                self._version_counter[version_key] = 1
                event_type = AuditEventType.BINDING_CREATED
            else:
                self._version_counter[version_key] += 1
                event_type = AuditEventType.BINDING_UPDATED

            binding.version = self._version_counter[version_key]
            binding.updated_at = datetime.datetime.now(datetime.UTC).isoformat()
            binding.updated_by = actor_id

            # Encrypt sensitive fields
            self._encrypt_binding(binding)

            # Find and update existing, or append
            if key not in self._bindings:
                self._bindings[key] = []

            existing_idx = None
            for i, b in enumerate(self._bindings[key]):
                if b.adapter_id == binding.adapter_id:
                    existing_idx = i
                    break

            if existing_idx is not None:
                self._bindings[key][existing_idx] = binding
            else:
                self._bindings[key].append(binding)

            # Record audit event
            audit_event = AuditEvent(
                event_type=event_type,
                workspace_id=binding.workspace_id,
                capability_id=binding.capability_id,
                adapter_id=binding.adapter_id,
                actor_id=actor_id,
                actor_role=actor_role,
                reason=reason,
                new_value={"priority": binding.priority, "enabled": binding.enabled},
            )
            self._record_audit_event(audit_event)

    def validate_binding(self, binding: AdapterBinding) -> ValidationResult:
        """Test adapter connection and validate configuration.

        Runs the provided validator (if available) to test the adapter connection.
        Updates binding's validation status.

        Args:
            binding: AdapterBinding to validate

        Returns:
            ValidationResult with connection test outcome
        """
        try:
            # Decrypt sensitive fields for validation
            self._decrypt_binding(binding)

            if not self._validator:
                return ValidationResult(
                    is_valid=True,
                    success=False,
                    error="No validator registered",
                    details={"reason": "validator_not_configured"},
                )

            result = self._validator(binding)

            # Update binding with validation status
            if result.success:
                binding.validation_status = "valid"
                binding.last_validated_at = datetime.datetime.now(datetime.UTC).isoformat()
            else:
                binding.validation_status = "invalid"

            # Record audit event
            audit_event = AuditEvent(
                event_type=AuditEventType.VALIDATION_TESTED,
                workspace_id=binding.workspace_id,
                capability_id=binding.capability_id,
                adapter_id=binding.adapter_id,
                actor_id="system",
                details={
                    "success": result.success,
                    "error": result.error,
                    "validation_details": result.details,
                },
            )
            self._record_audit_event(audit_event)

            return result
        except Exception as e:
            logger.error("Validation failed for binding %s: %s", binding.key(), e)
            return ValidationResult(
                is_valid=False,
                success=False,
                error=str(e),
                details={"exception": type(e).__name__},
            )

    def list_for_workspace(self, workspace_id: str) -> dict[str, list[AdapterBinding]]:
        """List all bindings for a workspace (including defaults).

        Returns workspace-specific bindings with decrypted sensitive fields.

        Args:
            workspace_id: Workspace identifier

        Returns:
            Dictionary mapping capability keys to lists of bindings
        """
        with self._lock:
            # Verify workspace isolation
            if not workspace_id or workspace_id.startswith("__"):
                raise ValueError(f"Invalid workspace_id: {workspace_id}")

            result: dict[str, list[AdapterBinding]] = {}

            for key, bindings in self._bindings.items():
                # Include workspace-specific and defaults
                parts = key.split(":")
                if len(parts) >= 2:
                    key_workspace = parts[0]
                    if key_workspace == workspace_id or key_workspace == "_default":
                        # Decrypt sensitive fields before returning
                        decrypted_bindings = []
                        for b in bindings:
                            b_copy = AdapterBinding(**asdict(b))
                            self._decrypt_binding(b_copy)
                            decrypted_bindings.append(b_copy)
                        result[key] = sorted(decrypted_bindings, key=lambda b: b.priority)

            return result

    def list_for_capability(
        self,
        workspace_id: str,
        capability_id: str,
    ) -> list[AdapterBinding]:
        """List all bindings for a capability in a workspace.

        Includes both specific methods and all-methods bindings.

        Args:
            workspace_id: Workspace identifier
            capability_id: Capability identifier

        Returns:
            List of AdapterBindings sorted by priority
        """
        with self._lock:
            results = []

            # Find all keys matching this workspace and capability
            for key, bindings in self._bindings.items():
                parts = key.split(":")
                if len(parts) >= 2:
                    key_workspace = parts[0]
                    key_capability = parts[1]

                    if key_capability == capability_id and (
                        key_workspace == workspace_id or key_workspace == "_default"
                    ):
                        results.extend(bindings)

            return sorted(results, key=lambda b: b.priority)

    def disable(
        self,
        workspace_id: str,
        capability_id: str,
        adapter_id: str,
        method_name: Optional[str] = None,
        actor_id: str = "system",
        reason: Optional[str] = None,
    ) -> bool:
        """Disable a binding with audit logging.

        Args:
            workspace_id: Workspace identifier
            capability_id: Capability identifier
            adapter_id: Adapter identifier
            method_name: Optional specific method name
            actor_id: User/system identifier making the change
            reason: Optional reason for disabling

        Returns:
            True if binding was found and disabled, False otherwise
        """
        with self._lock:
            if not workspace_id or workspace_id.startswith("__"):
                raise ValueError(f"Invalid workspace_id: {workspace_id}")

            key = self._make_key(workspace_id, capability_id, method_name)
            if key in self._bindings:
                for binding in self._bindings[key]:
                    if binding.adapter_id == adapter_id:
                        binding.enabled = False
                        binding.updated_at = datetime.datetime.now(datetime.UTC).isoformat()
                        binding.updated_by = actor_id

                        # Record audit event
                        audit_event = AuditEvent(
                            event_type=AuditEventType.BINDING_DISABLED,
                            workspace_id=workspace_id,
                            capability_id=capability_id,
                            adapter_id=adapter_id,
                            actor_id=actor_id,
                            reason=reason,
                            old_value={"enabled": True},
                            new_value={"enabled": False},
                        )
                        self._record_audit_event(audit_event)
                        return True
            return False

    def enable(
        self,
        workspace_id: str,
        capability_id: str,
        adapter_id: str,
        method_name: Optional[str] = None,
        actor_id: str = "system",
        reason: Optional[str] = None,
    ) -> bool:
        """Enable a binding with audit logging.

        Args:
            workspace_id: Workspace identifier
            capability_id: Capability identifier
            adapter_id: Adapter identifier
            method_name: Optional specific method name
            actor_id: User/system identifier making the change
            reason: Optional reason for enabling

        Returns:
            True if binding was found and enabled, False otherwise
        """
        with self._lock:
            if not workspace_id or workspace_id.startswith("__"):
                raise ValueError(f"Invalid workspace_id: {workspace_id}")

            key = self._make_key(workspace_id, capability_id, method_name)
            if key in self._bindings:
                for binding in self._bindings[key]:
                    if binding.adapter_id == adapter_id:
                        binding.enabled = True
                        binding.updated_at = datetime.datetime.now(datetime.UTC).isoformat()
                        binding.updated_by = actor_id

                        # Record audit event
                        audit_event = AuditEvent(
                            event_type=AuditEventType.BINDING_ENABLED,
                            workspace_id=workspace_id,
                            capability_id=capability_id,
                            adapter_id=adapter_id,
                            actor_id=actor_id,
                            reason=reason,
                            old_value={"enabled": False},
                            new_value={"enabled": True},
                        )
                        self._record_audit_event(audit_event)
                        return True
            return False

    def update_priority(
        self,
        workspace_id: str,
        capability_id: str,
        adapter_id: str,
        new_priority: int,
        method_name: Optional[str] = None,
        actor_id: str = "system",
        reason: Optional[str] = None,
    ) -> bool:
        """Update the priority of a binding with audit logging.

        Args:
            workspace_id: Workspace identifier
            capability_id: Capability identifier
            adapter_id: Adapter identifier
            new_priority: New priority value (lower = preferred)
            method_name: Optional specific method name
            actor_id: User/system identifier making the change
            reason: Optional reason for priority change

        Returns:
            True if binding was found and updated, False otherwise
        """
        with self._lock:
            if not workspace_id or workspace_id.startswith("__"):
                raise ValueError(f"Invalid workspace_id: {workspace_id}")

            key = self._make_key(workspace_id, capability_id, method_name)
            if key in self._bindings:
                for binding in self._bindings[key]:
                    if binding.adapter_id == adapter_id:
                        old_priority = binding.priority
                        binding.priority = new_priority
                        binding.updated_at = datetime.datetime.now(datetime.UTC).isoformat()
                        binding.updated_by = actor_id

                        # Record audit event
                        audit_event = AuditEvent(
                            event_type=AuditEventType.PRIORITY_CHANGED,
                            workspace_id=workspace_id,
                            capability_id=capability_id,
                            adapter_id=adapter_id,
                            actor_id=actor_id,
                            reason=reason,
                            old_value={"priority": old_priority},
                            new_value={"priority": new_priority},
                        )
                        self._record_audit_event(audit_event)
                        return True
            return False

    def update_configuration(
        self,
        workspace_id: str,
        capability_id: str,
        adapter_id: str,
        config: dict[str, Any],
        method_name: Optional[str] = None,
        actor_id: str = "system",
        reason: Optional[str] = None,
    ) -> bool:
        """Update the configuration of a binding with audit logging.

        Sensitive fields are encrypted before storage.

        Args:
            workspace_id: Workspace identifier
            capability_id: Capability identifier
            adapter_id: Adapter identifier
            config: New configuration dictionary
            method_name: Optional specific method name
            actor_id: User/system identifier making the change
            reason: Optional reason for configuration change

        Returns:
            True if binding was found and updated, False otherwise
        """
        with self._lock:
            if not workspace_id or workspace_id.startswith("__"):
                raise ValueError(f"Invalid workspace_id: {workspace_id}")

            key = self._make_key(workspace_id, capability_id, method_name)
            if key in self._bindings:
                for binding in self._bindings[key]:
                    if binding.adapter_id == adapter_id:
                        old_config = binding.configuration.copy()
                        binding.configuration = config
                        binding.updated_at = datetime.datetime.now(datetime.UTC).isoformat()
                        binding.updated_by = actor_id

                        # Encrypt sensitive fields
                        self._encrypt_binding(binding)

                        # Record audit event (exclude full config values for security)
                        audit_event = AuditEvent(
                            event_type=AuditEventType.CONFIG_UPDATED,
                            workspace_id=workspace_id,
                            capability_id=capability_id,
                            adapter_id=adapter_id,
                            actor_id=actor_id,
                            reason=reason,
                            details={
                                "config_keys_changed": list(set(list(old_config.keys()) + list(config.keys()))),
                                "sensitive_fields": binding.sensitive_fields,
                            },
                        )
                        self._record_audit_event(audit_event)
                        return True
            return False

    def get_audit_trail(
        self,
        workspace_id: Optional[str] = None,
        capability_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        """Get audit trail events, optionally filtered.

        Args:
            workspace_id: Filter to specific workspace (None = all)
            capability_id: Filter to specific capability (None = all)
            limit: Maximum number of recent events to return

        Returns:
            List of AuditEvent objects, most recent first
        """
        with self._lock:
            events = [e for e in self._audit_trail]

            if workspace_id:
                events = [e for e in events if e.workspace_id == workspace_id]
            if capability_id:
                events = [e for e in events if e.capability_id == capability_id]

            # Return most recent first, limited
            return events[-limit:][::-1]

    def workspace_config_get(self, workspace_id: str, key: str) -> Any:
        """Get a workspace configuration value.

        Args:
            workspace_id: Workspace identifier
            key: Configuration key

        Returns:
            Configuration value, or None if not set
        """
        if not workspace_id or workspace_id.startswith("__"):
            raise ValueError(f"Invalid workspace_id: {workspace_id}")

        with self._lock:
            config = self._workspace_configs.get(workspace_id, {})
            return config.get(key)

    def workspace_config_set(
        self,
        workspace_id: str,
        key: str,
        value: Any,
        actor_id: str = "system",
    ) -> None:
        """Set a workspace configuration value.

        Args:
            workspace_id: Workspace identifier
            key: Configuration key
            value: Configuration value
            actor_id: User/system identifier making the change
        """
        if not workspace_id or workspace_id.startswith("__"):
            raise ValueError(f"Invalid workspace_id: {workspace_id}")

        with self._lock:
            if workspace_id not in self._workspace_configs:
                self._workspace_configs[workspace_id] = {}
            self._workspace_configs[workspace_id][key] = value

            logger.info(
                "Workspace config updated: %s[%s] = %s by %s",
                workspace_id,
                key,
                value,
                actor_id,
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialize registry to dictionary (without decryption).

        Returns:
            Dictionary representation of all bindings
        """
        with self._lock:
            return {
                key: [b.to_dict() for b in bindings]
                for key, bindings in self._bindings.items()
            }

    def to_json(self) -> str:
        """Serialize registry to JSON string (without decryption).

        Returns:
            JSON string representation of all bindings
        """
        return json.dumps(self.to_dict(), indent=2)

    def export_for_workspace(self, workspace_id: str, include_audit: bool = False) -> dict[str, Any]:
        """Export all effective bindings for a workspace with decrypted config.

        Resolves workspace-specific overrides and defaults to show the complete
        configuration a workspace actually uses. Sensitive fields are decrypted
        before export.

        Args:
            workspace_id: Workspace identifier
            include_audit: Whether to include audit trail in export

        Returns:
            Dictionary mapping (capability, method) keys to the effective binding
            with decrypted configuration
        """
        if not workspace_id or workspace_id.startswith("__"):
            raise ValueError(f"Invalid workspace_id: {workspace_id}")

        with self._lock:
            result = {}

            # Get all unique (capability, method) pairs
            unique_pairs = set()
            for key in self._bindings.keys():
                parts = key.split(":")
                if len(parts) >= 2:
                    cap = parts[1]
                    method = parts[2] if len(parts) > 2 and parts[2] != "*" else None
                    unique_pairs.add((cap, method))

            # For each pair, get the effective binding
            for capability_id, method_name in unique_pairs:
                binding = self.get(workspace_id, capability_id, method_name)
                if binding:
                    # Make a copy to avoid modifying the registry
                    binding_copy = AdapterBinding(**asdict(binding))
                    # Decrypt sensitive fields
                    self._decrypt_binding(binding_copy)
                    export_key = f"{capability_id}:{method_name}" if method_name else capability_id
                    result[export_key] = binding_copy.to_dict()

            # Optionally include audit trail
            if include_audit:
                result["_audit_trail"] = [e.to_dict() for e in self.get_audit_trail(workspace_id)]

            return result
