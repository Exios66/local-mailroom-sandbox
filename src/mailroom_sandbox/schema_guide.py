"""Align the specialist output-schema descriptions with the gold labeling guide (opt-in).

The specialists append a JSON schema to every request, and its field descriptions are
what the model reads for a field's convention. For the fields that now carry repaired
truth (near-gold and interim labels), the vendored descriptions are looser than the
convention the labels follow (``docs/gold-labels/LABELING_GUIDE.md``): ``party_roles``
names no role vocabulary, ``recipient`` says only "who received it", ``urgency`` gives
no definitions, ``demand_amount`` does not say *of the recipient*. A run scored against
those labels then measures the description gap, not the prompt.

``job.schema_guide: true`` rewrites those descriptions in place at activation (types,
required keys and every other field stay as vendored); ``false`` (the default) restores
the vendored text, so a baseline is never changed silently. The flag is hashed into the
run lock only when set. Like ``provider_pins`` this wraps vendored state instead of
editing ``vendor/``.
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

_log = logging.getLogger(__name__)

ROLES = ("licensor", "licensee", "supplier", "customer", "distributor", "reseller", "franchisor",
         "franchisee", "service_provider", "client", "sponsor", "agent", "principal", "partner",
         "lender", "borrower", "other")

#: Field descriptions in the labeling guide's terms, per specialist schema.
GUIDE_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "contract": {
        "party_roles": ("One '<party>: <role>' line per contracting party; role is exactly one of "
                        + ", ".join(ROLES) + " (other only when the text names no role)"),
        "signatories": "Persons who sign the contract, names as printed in the signature blocks",
        "agreement_date": "The 'dated as of' or signature date as YYYY-MM-DD",
        "expiration_date": "End of the initial term as YYYY-MM-DD, only when the text states it as a date; else null",
        "termination_notice_period": "Notice needed to terminate the contract or to stop a renewal, as stated",
        "dispute_forum": "Courts or arbitral seat for disputes, as stated; never the governing law",
        "contract_value": ("Monetary consideration copied as a plain currency phrase ('$2,000,000'); "
                           "$0 is a stated amount; never computed or summed"),
        "payment_terms": "How and when the consideration is paid, as stated",
        "territory": "The stated territory of the grant, distribution or service, as stated",
    },
    "corporate_record": {
        "entity_name": "The corporation or entity the record is about, full legal name as written",
        "effective_date": ("Date the record takes effect as YYYY-MM-DD; when none is stated, its "
                           "adoption or filing date"),
        "signatories": ("People who sign the record (officers, directors, incorporators, grantors), as "
                        "printed in the execution block; [] when there is no execution block"),
        "jurisdiction": ("State or country under whose law the entity is organised (e.g. 'Delaware'); "
                         "for an indenture, its governing-law state"),
    },
    "correspondence": {
        "sender": ("Who sent it: full name, title and entity as written; press or wire: the issuing "
                   "company or media-contact line; null only when no sender is named"),
        "recipient": ("The first To: entry as printed (a person, list or group), else a salutation naming "
                      "a person or defined group; a generic salutation ('Dear Friends', 'All') is null"),
        "additional_recipients": "Further To, cc'd or copied parties as written; [] when none",
        "communication_date": "Date the communication was SENT as YYYY-MM-DD; never a deadline, meeting or invoice date",
        "demand_amount": ("Exact dollars the sender demands THE RECIPIENT pay (218440.00 for '$218,440.00'); "
                          "null for an amount only reported, invoiced or owed by someone else"),
        "action_items": "At most 3 concrete actions the recipient is asked to take, with deadlines if stated; [] when none",
        "urgency": ("Never null: routine (neutral or unspecified), time-sensitive (a near deadline or dated "
                    "request), urgent (stated urgency: 'ASAP', 'immediately'), critical (legal, financial or "
                    "safety consequences stated as imminent)"),
    },
}

_ORIGINAL: dict[str, dict[str, Any]] = {}
_APPLIED = False


def _schemas() -> dict[str, dict[str, Any]]:
    from langchain_agents import specialist_agents as sa

    return sa.SPECIALIST_SCHEMAS


def _props(schema: dict[str, Any]) -> dict[str, Any]:
    return schema.get("properties") or {}


def apply_schema_guide(enabled: bool) -> int:
    """Set the guide descriptions (``enabled``) or restore the vendored ones; returns fields changed."""
    global _APPLIED
    schemas = _schemas()
    if not _ORIGINAL:
        for cls in GUIDE_DESCRIPTIONS:
            _ORIGINAL[cls] = {f: deepcopy(p) for f, p in _props(schemas[cls]).items()
                              if f in GUIDE_DESCRIPTIONS[cls]}
    changed = 0
    for cls, fields in GUIDE_DESCRIPTIONS.items():
        props = _props(schemas[cls])
        for field, text in fields.items():
            if field not in props:
                raise KeyError(f"vendored {cls} schema has no field {field!r}; refresh GUIDE_DESCRIPTIONS")
            want = text if enabled else _ORIGINAL[cls][field].get("description")
            if props[field].get("description") != want:
                props[field]["description"] = want
                changed += 1
    _APPLIED = enabled
    return changed


def schema_guide_active() -> bool:
    return _APPLIED
