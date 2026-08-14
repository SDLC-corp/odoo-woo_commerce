import ast
import csv
import logging
from pathlib import Path
import xml.etree.ElementTree as ET

from .compat import CANONICAL_MODULE, LEGACY_MODULE, is_canonical_runtime


_logger = logging.getLogger(__name__)
_MODULE_ROOT = Path(__file__).resolve().parent


def _manifest_data_files():
    manifest = ast.literal_eval(
        _MODULE_ROOT.joinpath("__manifest__.py").read_text(encoding="utf-8")
    )
    return manifest.get("data", [])


def _module_xmlids():
    xmlids = set()
    for relative_path in _manifest_data_files():
        file_path = _MODULE_ROOT / relative_path
        if not file_path.exists():
            continue

        if file_path.suffix == ".csv":
            with file_path.open(newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    xmlid = (row.get("id") or "").strip()
                    if xmlid:
                        xmlids.add(xmlid)
            continue

        if file_path.suffix != ".xml":
            continue

        tree = ET.parse(file_path)
        for element in tree.iter():
            xmlid = element.attrib.get("id")
            if xmlid:
                xmlids.add(xmlid)
    return sorted(xmlids)


def pre_init_hook(env):
    if not is_canonical_runtime():
        _logger.info(
            "Skipping Woo XML-ID namespace migration because runtime module is %s",
            _MODULE_ROOT.name,
        )
        return

    xmlids = _module_xmlids()
    if not xmlids:
        return

    env.cr.execute(
        """
        UPDATE ir_model_data legacy
           SET module = %s
         WHERE legacy.module = %s
           AND legacy.name = ANY(%s)
           AND NOT EXISTS (
                SELECT 1
                  FROM ir_model_data canonical
                 WHERE canonical.module = %s
                   AND canonical.name = legacy.name
           )
        """,
        [CANONICAL_MODULE, LEGACY_MODULE, xmlids, CANONICAL_MODULE],
    )
    if env.cr.rowcount:
        _logger.info(
            "Migrated %s legacy XML IDs from %s to %s before module load.",
            env.cr.rowcount,
            LEGACY_MODULE,
            CANONICAL_MODULE,
        )


def post_init_hook(env):
    if not is_canonical_runtime():
        return

    xmlids = _module_xmlids()
    if not xmlids:
        return

    env.cr.execute(
        """
        INSERT INTO ir_model_data (
            module,
            name,
            model,
            res_id,
            noupdate,
            create_uid,
            write_uid,
            create_date,
            write_date
        )
        SELECT
            %s,
            canonical.name,
            canonical.model,
            canonical.res_id,
            canonical.noupdate,
            canonical.create_uid,
            canonical.write_uid,
            NOW() AT TIME ZONE 'UTC',
            NOW() AT TIME ZONE 'UTC'
          FROM ir_model_data canonical
         WHERE canonical.module = %s
           AND canonical.name = ANY(%s)
           AND NOT EXISTS (
                SELECT 1
                  FROM ir_model_data legacy
                 WHERE legacy.module = %s
                   AND legacy.name = canonical.name
           )
        """,
        [LEGACY_MODULE, CANONICAL_MODULE, xmlids, LEGACY_MODULE],
    )
    if env.cr.rowcount:
        _logger.info(
            "Created %s legacy XML-ID aliases under %s after module load.",
            env.cr.rowcount,
            LEGACY_MODULE,
        )
