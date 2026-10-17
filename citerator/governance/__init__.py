"""Governance layer: tamper-evident audit, document versioning, retention,
classification, GDPR erasure, and compliance-framework mapping.

Design principle: governance is not a feature bolted onto the product. It is
the product's ability to prove, after the fact, what it did and why. Every
audit record is hash-chained and HMAC-signed so that tampering is detectable
without trusting the storage layer.

Wiring: importing this package registers a hook on the document registry so
that every upsert (API or CLI) produces a version record. citerator.api.app
imports this package once at startup.
"""

from citerator.documents import registry
from citerator.governance.versioning import record_version

registry.register_upsert_hook(record_version)