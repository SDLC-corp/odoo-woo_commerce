from odoo import models, fields
from .woo_sync_base import WooSyncBase
from ..services.woo_service import WooService


class WooSyncEngine(models.AbstractModel):
    _name = "woo.sync.engine"
    _inherit = "woo.sync.base"
    _description = "Woo Sync Engine"

    def sync_from_woo(self, instance=None):
        """
        Generic pull-from-Woo sync method.

        :param instance: woo.instance record (singleton)
        """
        # --------------------------------------------------
        # 1️⃣ DETERMINE INSTANCE SAFELY
        # --------------------------------------------------
        if instance:
            instance.ensure_one()
        else:
            # fallback for backward compatibility
            if not self.instance_id:
                raise ValueError("Woo Instance not provided for sync.")
            instance = self.instance_id

        # --------------------------------------------------
        # 2️⃣ INIT SERVICE
        # --------------------------------------------------
        service = WooService(instance)

        # --------------------------------------------------
        # 3️⃣ FETCH DATA FROM WOO
        # --------------------------------------------------
        data, _headers = service.get(
            self._woo_endpoint(),
            {"per_page": 100}
        )

        synced = 0
        Model = self.env[self._name]

        # --------------------------------------------------
        # 4️⃣ CREATE / UPDATE RECORDS
        # --------------------------------------------------
        for record in data:
            woo_id = record.get("id")
            if not woo_id:
                continue

            domain = [
                (self._woo_unique_field(), "=", str(woo_id)),
                ("instance_id", "=", instance.id),
            ]

            existing = Model.search(domain, limit=1)

            vals = self._prepare_vals(record)
            vals.update({
                "instance_id": instance.id,
                "state": "synced",
                "synced_on": fields.Datetime.now(),
            })

            if existing:
                existing.write(vals)
            else:
                Model.create(vals)

            synced += 1

        return synced
