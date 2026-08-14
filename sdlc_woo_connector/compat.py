import logging
from pathlib import Path


_logger = logging.getLogger(__name__)

CANONICAL_MODULE = "sdlc_woo_connector"
LEGACY_MODULE = "woo_connector"
CURRENT_MODULE = Path(__file__).resolve().parent.name


def is_canonical_runtime():
    return CURRENT_MODULE == CANONICAL_MODULE


def resolve_woo_xmlid(env, xmlid, raise_if_not_found=True):
    if not xmlid:
        if raise_if_not_found:
            raise ValueError("Missing XML ID")
        return None

    if "." in xmlid:
        module_name, record_name = xmlid.split(".", 1)
        if module_name not in {CANONICAL_MODULE, LEGACY_MODULE}:
            return env.ref(xmlid, raise_if_not_found=raise_if_not_found)
    else:
        record_name = xmlid

    for candidate in (
        f"{CANONICAL_MODULE}.{record_name}",
        f"{LEGACY_MODULE}.{record_name}",
    ):
        record = env.ref(candidate, raise_if_not_found=False)
        if record:
            return record

    if raise_if_not_found:
        raise ValueError(
            "External ID not found in the system: "
            f"{CANONICAL_MODULE}.{record_name} "
            f"(fallback {LEGACY_MODULE}.{record_name})"
        )

    _logger.debug(
        "XML ID %s could not be resolved under %s or %s",
        record_name,
        CANONICAL_MODULE,
        LEGACY_MODULE,
    )
    return None
