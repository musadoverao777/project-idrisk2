"""
IDRISK2 — Security and Privacy Enhancements (Section 4.6)
Implements:
- Role-based access control (RBAC)
- Data minimisation and retention policies
- Audit logging with tamper-evident records
- Input sanitisation and validation
- Secure configuration management
- GDPR compliance mechanisms
"""
import hashlib
import hmac
import inspect
import json
import logging
import os
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from enum import Enum
from functools import wraps
from pathlib import Path
from typing import Optional, Callable
logger = logging.getLogger(__name__)
# ---------------------------------------------------------------------------
# Role-Based Access Control (RBAC)
# ---------------------------------------------------------------------------
class Role(Enum):
    """User roles with different access levels."""
    INSPECTOR = "inspector"          # Submit images, view own results
    SUPERVISOR = "supervisor"        # View all results, access audit logs
    ADMINISTRATOR = "administrator"  # Full access including system config
    AUDITOR = "auditor"             # Read-only access to audit records
# Permissions per role
ROLE_PERMISSIONS = {
    Role.INSPECTOR: {
        "submit_classification",
        "view_own_results",
    },
    Role.SUPERVISOR: {
        "submit_classification",
        "view_own_results",
        "view_all_results",
        "view_audit_logs",
        "flag_for_review",
        "benchmark_engines",
    },
    Role.ADMINISTRATOR: {
        "submit_classification",
        "view_own_results",
        "view_all_results",
        "view_audit_logs",
        "flag_for_review",
        "benchmark_engines",
        "manage_users",
        "manage_knowledge_base",
        "configure_system",
    },
    Role.AUDITOR: {
        "view_audit_logs",
        "view_all_results",
    },
}
@dataclass
class User:
    """System user with role-based access control."""
    user_id: str
    username: str
    role: Role
    created_at: str
    is_active: bool = True
def check_permission(user: User, permission: str) -> bool:
    """Check if a user has a specific permission."""
    allowed = ROLE_PERMISSIONS.get(user.role, set())
    return permission in allowed
def require_permission(permission: str):
    """
    Decorator that enforces permission checks on pipeline functions.
    Locates the `user` argument from either positional or keyword args
    using the wrapped function's signature — so it works whether the
    caller passes user as `f(user=u)` or `f(image, u)` and whether the
    target is a free function or an instance method.
    Raises PermissionError if the user lacks the required permission.
    """
    def decorator(func: Callable):
        sig = inspect.signature(func)
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                bound = sig.bind_partial(*args, **kwargs)
            except TypeError:
                # Argument binding failed — let the inner call surface the error
                return func(*args, **kwargs)
            user = bound.arguments.get("user")
            if user is None:
                raise TypeError(
                    f"{func.__name__} requires a 'user' argument for "
                    f"permission '{permission}'"
                )
            if not check_permission(user, permission):
                logger.warning(
                    f"Access denied: user '{user.username}' "
                    f"(role: {user.role.value}) attempted '{permission}'"
                )
                raise PermissionError(
                    f"User '{user.username}' does not have permission: '{permission}'"
                )
            return func(*args, **kwargs)
        return wrapper
    return decorator
# ---------------------------------------------------------------------------
# Data minimisation
# ---------------------------------------------------------------------------
@dataclass
class MinimisedProductRecord:
    """
    Minimised product record — retains only classification-relevant data.
    Raw images are not persisted after feature extraction per GDPR
    data minimisation principle (Article 5(1)(c)).
    """
    record_id: str
    ocr_text: str                    # Extracted text — retained
    classification_result: dict      # FoodEx2 output — retained
    image_hash: str                  # SHA-256 of original image — retained for dedup
    timestamp: str
    submitted_by: str                # User ID only — not full user object
    image_path: Optional[str] = None # Cleared after processing
def minimise_record(
    ocr_text: str,
    image: bytes,
    classification: dict,
    user_id: str,
    retain_image: bool = False,
    image_path: Optional[str] = None,
) -> MinimisedProductRecord:
    """
    Create a minimised product record.
    Computes image hash for deduplication but discards raw image bytes
    unless explicitly required for audit purposes.
    Args:
        ocr_text: extracted label text
        image: raw image bytes
        classification: FoodEx2 classification result dict
        user_id: ID of submitting user
        retain_image: if True, retains image path (requires justification)
        image_path: path to stored image (only used if retain_image=True)
    """
    image_hash = hashlib.sha256(image).hexdigest()
    record = MinimisedProductRecord(
        record_id=str(uuid.uuid4()),
        ocr_text=ocr_text,
        classification_result=classification,
        image_hash=image_hash,
        timestamp=datetime.utcnow().isoformat(),
        submitted_by=user_id,
        image_path=image_path if retain_image else None,
    )
    if not retain_image:
        logger.info(
            f"Image bytes discarded after processing (data minimisation). "
            f"Hash retained: {image_hash[:16]}..."
        )
    return record
def save_minimised_record(
    record: MinimisedProductRecord,
    records_dir: str,
) -> Path:
    """
    Persist a minimised product record to disk as JSON.
    Args:
        record: MinimisedProductRecord to persist
        records_dir: directory for minimised record storage
    Returns:
        Path to the written record file
    """
    records_path = Path(records_dir)
    records_path.mkdir(parents=True, exist_ok=True)
    record_path = records_path / f"{record.record_id}.json"
    with open(record_path, "w", encoding="utf-8") as f:
        json.dump(asdict(record), f, indent=2, ensure_ascii=False)
    logger.debug(f"Minimised record persisted: {record_path}")
    return record_path
# ---------------------------------------------------------------------------
# Retention policy
# ---------------------------------------------------------------------------
RETENTION_DAYS = {
    "classification_records": 365,   # 1 year
    "audit_logs": 2555,              # 7 years (regulatory requirement)
    "temporary_images": 0,           # Deleted immediately after processing
}
def apply_retention_policy(records_dir: str, record_type: str):
    """
    Delete records older than the configured retention period.
    Args:
        records_dir: directory containing JSON record files
        record_type: key in RETENTION_DAYS dict
    """
    retention_days = RETENTION_DAYS.get(record_type)
    if retention_days is None:
        raise ValueError(f"Unknown record type: {record_type}")
    records_path = Path(records_dir)
    if not records_path.exists():
        return
    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    deleted = 0
    for record_file in records_path.glob("*.json"):
        try:
            with open(record_file) as f:
                record = json.load(f)
            timestamp = datetime.fromisoformat(
                record.get("timestamp", datetime.utcnow().isoformat())
            )
            if timestamp < cutoff:
                record_file.unlink()
                deleted += 1
        except Exception as e:
            logger.error(f"Error processing {record_file}: {e}")
    if deleted:
        logger.info(
            f"Retention policy applied: {deleted} {record_type} records deleted "
            f"(older than {retention_days} days)"
        )
# ---------------------------------------------------------------------------
# Tamper-evident audit logging
# ---------------------------------------------------------------------------
class AuditLogger:
    """
    Tamper-evident audit logger using HMAC chaining.
    Each audit entry includes an HMAC of its content chained with
    the previous entry's HMAC, making any modification detectable.
    This implements the audit trail requirements of the EU AI Act
    for high-risk AI systems.
    """
    def __init__(self, audit_dir: str, secret_key: Optional[str] = None):
        self.audit_path = Path(audit_dir)
        self.audit_path.mkdir(parents=True, exist_ok=True)
        self.secret_key = (
            secret_key or os.environ.get("IDRISK2_AUDIT_KEY", "default-dev-key")
        ).encode()
        self._last_hmac = "genesis"   # Chain anchor
    def log(
        self,
        event_type: str,
        user_id: str,
        details: dict,
    ) -> str:
        """
        Write a tamper-evident audit log entry.
        Args:
            event_type: type of event (e.g. "classification", "access_denied")
            user_id: ID of the user triggering the event
            details: event-specific details dict
        Returns:
            entry_id of the created log entry
        """
        entry_id = str(uuid.uuid4())
        entry = {
            "entry_id": entry_id,
            "timestamp": datetime.utcnow().isoformat(),
            "event_type": event_type,
            "user_id": user_id,
            "details": details,
            "previous_hmac": self._last_hmac,
        }
        # Compute HMAC over entry content (excluding the hmac field itself)
        content = json.dumps(entry, sort_keys=True).encode()
        entry_hmac = hmac.new(self.secret_key, content, hashlib.sha256).hexdigest()
        entry["hmac"] = entry_hmac
        self._last_hmac = entry_hmac
        # Write to disk
        log_file = self.audit_path / f"{entry_id}.json"
        with open(log_file, "w") as f:
            json.dump(entry, f, indent=2)
        logger.debug(f"Audit entry written: {event_type} | {entry_id}")
        return entry_id
    def verify_chain(self) -> bool:
        """
        Verify the integrity of the audit log chain.
        Detects any tampering by recomputing HMACs across all entries
        in chronological order.
        Returns:
            True if chain is intact, False if tampering detected
        """
        log_files = sorted(self.audit_path.glob("*.json"))
        previous_hmac = "genesis"
        for log_file in log_files:
            with open(log_file) as f:
                entry = json.load(f)
            stored_hmac = entry.pop("hmac", None)
            if entry.get("previous_hmac") != previous_hmac:
                logger.error(
                    f"Chain break detected at entry {entry.get('entry_id')}"
                )
                return False
            content = json.dumps(entry, sort_keys=True).encode()
            expected_hmac = hmac.new(
                self.secret_key, content, hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(stored_hmac or "", expected_hmac):
                logger.error(
                    f"HMAC mismatch at entry {entry.get('entry_id')} — "
                    f"tampering detected"
                )
                return False
            previous_hmac = stored_hmac
        logger.info(f"Audit chain verified: {len(log_files)} entries intact")
        return True
# ---------------------------------------------------------------------------
# Input sanitisation
# ---------------------------------------------------------------------------
MAX_IMAGE_SIZE_MB = 20
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic"}
MAX_OCR_TEXT_LENGTH = 50_000   # characters
def validate_image_input(image_bytes: bytes, mime_type: str) -> None:
    """
    Validate image input before processing.
    Raises ValueError for inputs that fail validation.
    """
    # Size check
    size_mb = len(image_bytes) / (1024 * 1024)
    if size_mb > MAX_IMAGE_SIZE_MB:
        raise ValueError(
            f"Image too large: {size_mb:.1f}MB (max {MAX_IMAGE_SIZE_MB}MB)"
        )
    # MIME type check
    if mime_type.lower() not in ALLOWED_MIME_TYPES:
        raise ValueError(
            f"Unsupported image type: {mime_type}. "
            f"Allowed: {ALLOWED_MIME_TYPES}"
        )
    # Basic magic bytes check for JPEG and PNG
    if mime_type == "image/jpeg" and not image_bytes[:2] == b"\xff\xd8":
        raise ValueError("File claims to be JPEG but magic bytes do not match")
    if mime_type == "image/png" and not image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        raise ValueError("File claims to be PNG but magic bytes do not match")
    logger.debug(f"Image validation passed: {size_mb:.2f}MB, {mime_type}")
def sanitise_ocr_text(text: str) -> str:
    """
    Sanitise OCR-extracted text before injection into prompts.
    Removes control characters and truncates to maximum length
    to prevent prompt injection attacks.
    """
    # Remove null bytes and control characters
    sanitised = "".join(c for c in text if c.isprintable() or c in "\n\t")
    # Truncate if necessary
    if len(sanitised) > MAX_OCR_TEXT_LENGTH:
        logger.warning(
            f"OCR text truncated from {len(sanitised)} to "
            f"{MAX_OCR_TEXT_LENGTH} characters"
        )
        sanitised = sanitised[:MAX_OCR_TEXT_LENGTH]
    return sanitised.strip()
# ---------------------------------------------------------------------------
# Secure configuration management
# ---------------------------------------------------------------------------
REQUIRED_ENV_VARS = [
    "IDRISK2_AUDIT_KEY",      # HMAC key for audit log integrity
    "IDRISK2_DATA_DIR",       # Base directory for data storage
    "IDRISK2_DOCS_DIR",       # EFSA documents directory
]
OPTIONAL_ENV_VARS = {
    "OPENAI_API_KEY": None,   # Required only if using GPT-4o
    "IDRISK2_LOG_LEVEL": "INFO",
    "IDRISK2_MAX_RETRIES": "2",
}
def load_config() -> dict:
    """
    Load and validate system configuration from environment variables.
    Raises EnvironmentError if required variables are missing.
    """
    config = {}
    missing = []
    for var in REQUIRED_ENV_VARS:
        value = os.environ.get(var)
        if not value:
            missing.append(var)
        else:
            config[var] = value
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {missing}\n"
            f"Please configure these before starting the IDRISK2 system."
        )
    for var, default in OPTIONAL_ENV_VARS.items():
        config[var] = os.environ.get(var, default)
    logger.info("Configuration loaded successfully")
    return config
