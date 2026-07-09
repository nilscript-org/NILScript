# Adapter Bindings: Production-Grade Configuration Engine

## Overview

`adapter_bindings.py` implements a secure, audited, multi-tenant adapter configuration system for the nilscript controlplane. It manages workspace-specific bindings between capabilities and adapters with comprehensive security, audit trail, and validation features.

## Architecture

### Core Components

#### 1. **AdapterBinding** (Dataclass)
Represents a single binding configuration between a capability/method and an adapter.

**Key Attributes:**
- `workspace_id`: Tenant isolation (required, validated)
- `capability_id`: Capability being configured (e.g., "communication", "approval")
- `method_name`: Optional specific method (e.g., "send_email"). `None` = applies to all methods
- `adapter_id`: Adapter to use (e.g., "whatsapp", "email", "odoo")
- `adapter_method`: Method name on the adapter
- `priority`: Lower number = higher priority (enables fallback chains)
- `enabled`: Boolean flag for enable/disable
- `configuration`: Dict of adapter-specific config
- `sensitive_fields`: List of config keys that contain sensitive data (encrypted at rest)
- `version`: Auto-incrementing version for audit trail
- `created_by`, `updated_by`: Actor who created/updated
- `last_validated_at`, `validation_status`: Connection test history

**Example:**
```python
binding = AdapterBinding(
    workspace_id="acme-corp",
    capability_id="communication",
    adapter_id="whatsapp",
    adapter_method="send_message",
    priority=1,
    configuration={
        "phone_number": "+1234567890",
        "api_key": "secret_key_here"
    },
    sensitive_fields=["api_key"],
    created_by="admin@acme.com"
)
```

#### 2. **AuditEvent** (Dataclass + Enum)
Records who changed what, when, and why.

**AuditEventType Enum:**
- `BINDING_CREATED`
- `BINDING_UPDATED`
- `BINDING_ENABLED`
- `BINDING_DISABLED`
- `PRIORITY_CHANGED`
- `CONFIG_UPDATED`
- `VALIDATION_TESTED`
- `BINDING_DELETED`

**AuditEvent Attributes:**
- `event_type`: Type of change
- `workspace_id`, `capability_id`, `adapter_id`: What changed
- `actor_id`, `actor_role`: Who made the change
- `timestamp`: When (ISO format, UTC)
- `reason`: Why (optional but recommended)
- `old_value`, `new_value`: Before/after values
- `details`: Additional context dict

**Example:**
```python
event = AuditEvent(
    event_type=AuditEventType.BINDING_UPDATED,
    workspace_id="acme-corp",
    capability_id="communication",
    adapter_id="whatsapp",
    actor_id="alice@acme.com",
    actor_role="admin",
    timestamp="2024-07-08T12:34:56+00:00",
    reason="Updated API key after rotation",
    old_value={"version": 1},
    new_value={"version": 2}
)
```

#### 3. **ValidationResult** (Dataclass)
Stores results of adapter connection validation.

**Attributes:**
- `is_valid`: Configuration is valid
- `success`: Connection test succeeded
- `error`: Error message (if failed)
- `details`: Validator-specific details dict
- `tested_at`: When validation occurred

#### 4. **AdapterBindingRegistry** (Main Class)
Thread-safe registry managing all bindings across workspaces.

## Key Features

### 1. Multi-Tenant Safety

✓ **Workspace Isolation:**
- All access scoped by `workspace_id`
- Cannot access another workspace's bindings
- Workspace ID validation prevents reserved names

```python
registry.set(
    binding,
    actor_id="user-123",
    actor_role="admin"
)
# Only workspace specified in binding is affected
```

✓ **Validation:**
```python
# These raise ValueError
registry.get("", "capability", None)  # Empty workspace
registry.get("__reserved__", "cap", None)  # Reserved prefix
```

### 2. Encrypted Configuration

✓ **Sensitive Field Encryption:**
- Integrates with existing `SecretVault` (Fernet-based)
- Only sensitive fields encrypted; bulk config stays plaintext for usability
- Automatic encrypt-at-write, decrypt-at-read

```python
binding = AdapterBinding(
    workspace_id="ws-1",
    capability_id="finance",
    adapter_id="sap",
    adapter_method="create_invoice",
    configuration={
        "endpoint": "https://sap.example.com",  # Public
        "client_id": "1000",                     # Public
        "api_key": "secret_...",                 # Sensitive
        "username": "sap_user"                   # Sensitive
    },
    sensitive_fields=["api_key", "username"]    # These get encrypted
)

registry.set(binding)
# In storage: api_key and username are encrypted
# When retrieved: automatically decrypted

retrieved = registry.get("ws-1", "finance")
print(retrieved.configuration["api_key"])  # Decrypted!
```

✓ **Environment-Driven Setup:**
```python
# Vault auto-initialized from NIL_VAULT_KEY env var if present
registry = AdapterBindingRegistry()

# Or explicitly pass vault
from nilscript.secrets.vault import SecretVault
vault = SecretVault.from_env("MY_VAULT_KEY")
registry = AdapterBindingRegistry(vault=vault)
```

### 3. Comprehensive Audit Trail

✓ **Automatic Logging of All Changes:**
```python
# Every operation records who, what, when, why
registry.set(
    binding,
    actor_id="alice@acme.com",
    actor_role="admin",
    reason="Migrating from WhatsApp to Twilio for better reliability"
)

registry.update_priority(
    "ws-1", "communication", "email",
    new_priority=2,
    actor_id="bob@acme.com",
    reason="Lowering email priority due to high volume"
)

registry.disable(
    "ws-1", "communication", "slack",
    actor_id="charlie@acme.com",
    reason="Slack workspace suspended pending security audit"
)
```

✓ **Query Audit Trail:**
```python
# Get all events for a workspace
events = registry.get_audit_trail(workspace_id="ws-1")
for event in events:
    print(f"{event.timestamp}: {event.actor_id} ({event.actor_role}) "
          f"{event.event_type.value} - {event.reason}")

# Get events for a specific capability
events = registry.get_audit_trail(
    workspace_id="ws-1",
    capability_id="communication",
    limit=50
)

# Export with audit trail
export = registry.export_for_workspace("ws-1", include_audit=True)
audit_log = export["_audit_trail"]
```

### 4. Adapter Validation & Connection Testing

✓ **Custom Validator Support:**
```python
def my_adapter_validator(binding: AdapterBinding) -> ValidationResult:
    """Test connection to adapter."""
    try:
        # Example: test WhatsApp API connectivity
        if binding.adapter_id == "whatsapp":
            api_key = binding.configuration.get("api_key")
            response = requests.get(
                "https://graph.instagram.com/v18.0/me",
                headers={"Authorization": f"Bearer {api_key}"}
            )
            response.raise_for_status()
            return ValidationResult(
                is_valid=True,
                success=True,
                details={"account_status": "active"}
            )
    except requests.RequestException as e:
        return ValidationResult(
            is_valid=True,
            success=False,
            error=str(e),
            details={"error_type": "connection_failed"}
        )

# Register validator
registry = AdapterBindingRegistry(validator=my_adapter_validator)

# Test a binding
result = registry.validate_binding(binding)
print(f"Valid: {result.is_valid}, Success: {result.success}")
if result.error:
    print(f"Error: {result.error}")
```

✓ **Validation History:**
```python
binding.last_validated_at  # "2024-07-08T12:00:00+00:00"
binding.validation_status  # "valid" | "invalid" | "untested"

# Validation also recorded in audit trail
events = registry.get_audit_trail(workspace_id="ws-1")
validation_events = [e for e in events 
                     if e.event_type == AuditEventType.VALIDATION_TESTED]
```

### 5. Workspace Configuration

✓ **Admin-Controlled Settings:**
```python
# Admin sets workspace-wide defaults
registry.workspace_config_set(
    "ws-1",
    "default_communication_adapter",
    "whatsapp",
    actor_id="admin@acme.com"
)

registry.workspace_config_set(
    "ws-1",
    "timeout_seconds",
    30,
    actor_id="admin@acme.com"
)

# Later retrieve
default_adapter = registry.workspace_config_get(
    "ws-1",
    "default_communication_adapter"
)
```

### 6. Priority-Based Fallback Chains

✓ **Multi-Adapter Selection:**
```python
# Communication capability: try WhatsApp first, fall back to Email
bindings = [
    AdapterBinding(
        workspace_id="ws-1",
        capability_id="communication",
        adapter_id="whatsapp",
        adapter_method="send_message",
        priority=1,  # Try first
        configuration={}
    ),
    AdapterBinding(
        workspace_id="ws-1",
        capability_id="communication",
        adapter_id="email",
        adapter_method="send_message",
        priority=2,  # Fall back to this
        configuration={}
    ),
    AdapterBinding(
        workspace_id="ws-1",
        capability_id="communication",
        adapter_id="slack",
        adapter_method="send_message",
        priority=3,  # Last resort
        configuration={}
    ),
]

for binding in bindings:
    registry.set(binding, actor_id="system")

# Get highest-priority enabled binding
best = registry.get("ws-1", "communication")
print(f"Use: {best.adapter_id}")  # whatsapp

# Get all as fallback chain
all_chain = registry.get_all_matching("ws-1", "communication")
for adapter in all_chain:
    print(f"Try {adapter.adapter_id} (priority {adapter.priority})")
```

### 7. Workspace-Specific Overrides

✓ **Override Defaults Per Workspace:**
```python
# System default
default = AdapterBinding(
    workspace_id="_default",
    capability_id="communication",
    adapter_id="email",
    adapter_method="send_message",
    priority=1
)
registry.set(default, actor_id="system")

# Workspace override (higher priority)
override = AdapterBinding(
    workspace_id="acme-corp",
    capability_id="communication",
    adapter_id="twilio",
    adapter_method="send_message",
    priority=1
)
registry.set(override, actor_id="admin@acme.com")

# Retrieval resolution order:
# 1. Workspace-specific binding for (capability, method)
# 2. Workspace-specific binding for capability (any method)
# 3. Default binding for (capability, method)
# 4. Default binding for capability (any method)

retrieved = registry.get("acme-corp", "communication")
print(retrieved.adapter_id)  # twilio (workspace override)

retrieved = registry.get("other-corp", "communication")
print(retrieved.adapter_id)  # email (default)
```

## API Reference

### AdapterBindingRegistry Methods

**Read Operations:**
```python
# Get highest-priority enabled binding
binding = registry.get(workspace_id, capability_id, method_name=None)

# Get all enabled bindings matching criteria
bindings = registry.get_all_matching(workspace_id, capability_id, method_name=None)

# List all bindings for a workspace
all_bindings = registry.list_for_workspace(workspace_id)

# List bindings for a specific capability
bindings = registry.list_for_capability(workspace_id, capability_id)

# Get audit trail
events = registry.get_audit_trail(workspace_id=None, capability_id=None, limit=100)
```

**Write Operations:**
```python
# Set/create a binding
registry.set(
    binding,
    actor_id="user@example.com",
    actor_role="admin",
    reason="Optional reason"
)

# Enable a binding
success = registry.enable(
    workspace_id, capability_id, adapter_id,
    method_name=None,
    actor_id="user@example.com",
    reason="Optional reason"
)

# Disable a binding
success = registry.disable(
    workspace_id, capability_id, adapter_id,
    method_name=None,
    actor_id="user@example.com",
    reason="Optional reason"
)

# Update priority
success = registry.update_priority(
    workspace_id, capability_id, adapter_id,
    new_priority,
    method_name=None,
    actor_id="user@example.com",
    reason="Optional reason"
)

# Update configuration
success = registry.update_configuration(
    workspace_id, capability_id, adapter_id,
    config_dict,
    method_name=None,
    actor_id="user@example.com",
    reason="Optional reason"
)
```

**Validation & Export:**
```python
# Test adapter connection
result = registry.validate_binding(binding)
if result.success:
    print(f"Connected successfully: {result.details}")
else:
    print(f"Connection failed: {result.error}")

# Export all effective bindings for workspace (with decrypted config)
export = registry.export_for_workspace(
    workspace_id,
    include_audit=False
)
```

**Workspace Configuration:**
```python
# Get workspace config value
value = registry.workspace_config_get(workspace_id, key)

# Set workspace config value
registry.workspace_config_set(
    workspace_id, key, value,
    actor_id="user@example.com"
)
```

**Serialization:**
```python
# Export as dict (encrypted fields remain encrypted)
data = registry.to_dict()

# Export as JSON
json_str = registry.to_json()
```

## Security Considerations

### 1. **Sensitive Field Encryption**
- Configured via `sensitive_fields` list on binding
- Automatically encrypted/decrypted using SecretVault
- Vault key stored in `NIL_VAULT_KEY` environment variable
- Never logged or exposed in audit trail values

### 2. **Multi-Tenant Isolation**
- All operations scoped to `workspace_id`
- Cannot bypass workspace boundaries
- Workspace ID validation prevents reserved names (`__*`)
- Thread-safe with RLock for concurrent access

### 3. **Audit Trail Immutability**
- Events are append-only
- Full change history preserved
- Includes actor ID, role, timestamp, and reason
- Supports compliance and forensic analysis

### 4. **Actor Attribution**
- All changes include `actor_id` and `actor_role`
- Enables accountability tracking
- Integrates with authentication system
- Supports automated (role="automation") changes

### 5. **Configuration Versioning**
- Auto-incrementing `version` on each change
- Enables rollback/recovery procedures
- Tracks which config version is active

## Best Practices

### 1. **Always Specify Actor Information**
```python
# Good
registry.set(
    binding,
    actor_id="alice@acme.com",
    actor_role="admin",
    reason="Updating API key after security audit"
)

# Avoid default "system" when user initiated
# Default is only appropriate for automated/initialization operations
```

### 2. **Use Specific Reasons for Changes**
```python
# Good
registry.disable(
    "ws-1", "communication", "slack",
    reason="Slack workspace suspended pending security audit",
    actor_id="security@acme.com"
)

# Avoid
registry.disable("ws-1", "communication", "slack")
```

### 3. **Mark All Sensitive Fields**
```python
# Good
binding.sensitive_fields = ["api_key", "password", "client_secret"]

# Avoid leaving credentials in plaintext
binding.sensitive_fields = []  # Don't do this
```

### 4. **Validate Adapters After Configuration**
```python
# Register your validator
def my_validator(binding):
    # Test connection, validate credentials, etc.
    pass

registry = AdapterBindingRegistry(validator=my_validator)

# Validate after setup
result = registry.validate_binding(binding)
if not result.success:
    logger.error(f"Adapter validation failed: {result.error}")
```

### 5. **Review Audit Trail Regularly**
```python
# Monitor changes
events = registry.get_audit_trail(workspace_id="ws-1", limit=100)
high_risk_events = [
    e for e in events 
    if e.event_type in [
        AuditEventType.CONFIG_UPDATED,
        AuditEventType.BINDING_DISABLED,
        AuditEventType.PRIORITY_CHANGED,
    ]
]
for event in high_risk_events:
    print(f"Change by {event.actor_id}: {event.reason}")
```

## Example: Complete Workspace Setup

```python
from nilscript.controlplane.adapter_bindings import (
    AdapterBinding,
    AdapterBindingRegistry,
)

# Initialize with validator
def validate_whatsapp(binding):
    # Test WhatsApp API connectivity
    import requests
    try:
        response = requests.get(
            "https://graph.instagram.com/v18.0/me",
            headers={"Authorization": f"Bearer {binding.configuration['api_key']}"}
        )
        return ValidationResult(
            is_valid=True,
            success=response.status_code == 200,
            error=None if response.status_code == 200 else response.text
        )
    except Exception as e:
        return ValidationResult(is_valid=True, success=False, error=str(e))

registry = AdapterBindingRegistry(validator=validate_whatsapp)

# Create binding for ACME Corp
binding = AdapterBinding(
    workspace_id="acme-corp",
    capability_id="communication",
    adapter_id="whatsapp",
    adapter_method="send_message",
    priority=1,
    configuration={
        "endpoint": "https://graph.instagram.com/v18.0",
        "api_key": "EABC...",
        "phone_number_id": "1234567890"
    },
    sensitive_fields=["api_key"],
    created_by="admin@acme.com"
)

# Set binding with audit trail
registry.set(
    binding,
    actor_id="admin@acme.com",
    actor_role="admin",
    reason="Initial WhatsApp setup for ACME Corp"
)

# Validate connectivity
result = registry.validate_binding(binding)
if result.success:
    print("WhatsApp adapter is ready")
else:
    print(f"Failed to validate: {result.error}")

# Configure workspace
registry.workspace_config_set(
    "acme-corp",
    "default_communication_adapter",
    "whatsapp",
    actor_id="admin@acme.com"
)

# Export full configuration
export = registry.export_for_workspace("acme-corp", include_audit=True)
print(f"Workspace configuration exported with audit trail")
```

## Integration Points

### With Capability Catalog
Use bindings to select which adapter executes each capability method.

### With Hermes (Message Router)
Query registry to determine which adapter to route messages to.

### With Admin UI
Expose binding management endpoints for workspace admins to:
- View current adapter configuration
- Add/update adapter credentials
- Adjust adapter priorities
- Enable/disable adapters
- View audit trail

### With Secrets Management
Integrates with `SecretVault` for credential encryption/decryption.

## Troubleshooting

**Issue: "Invalid workspace_id"**
- Workspace ID is empty or starts with `__`
- Ensure workspace ID is a valid tenant identifier

**Issue: Validation fails with "No validator registered"**
- Initialize registry with `validator=my_func` parameter
- Implement validator function that returns `ValidationResult`

**Issue: Sensitive fields not encrypted**
- Add field names to `sensitive_fields` list before calling `set()`
- Ensure `NIL_VAULT_KEY` environment variable is set

**Issue: Changes not showing in audit trail**
- Always pass `actor_id` and `actor_role` to mutation methods
- Check that workspace_id is correct

**Issue: Performance degradation with large audit trail**
- Use `limit` parameter on `get_audit_trail()`
- Consider archiving old events periodically
- Implement event pruning for very large deployments

## Future Enhancements

- [ ] Audit trail persistence to database
- [ ] Event-driven notifications on binding changes
- [ ] Binding templates for common patterns
- [ ] Rollback/restore capabilities
- [ ] Real-time validation health checks
- [ ] Performance metrics and alerting
- [ ] Bulk import/export with encryption
- [ ] Integration with RBAC for fine-grained permissions
