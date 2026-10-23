from random import randint

from odoo import fields, models


class ProductTag(models.Model):
    """Odoo 16's product.tag, which Odoo 15 does not have: the store's product
    tags the connector imports (woo.product.sync.tag_ids) and the AI content
    wizard suggests. Same fields, constraint and access as Odoo 16's model."""
    _name = 'product.tag'
    _description = 'Product Tag'

    def _get_default_color(self):
        return randint(1, 11)

    name = fields.Char('Tag Name', required=True, translate=True)
    color = fields.Integer('Color', default=_get_default_color)

    _sql_constraints = [
        ('name_uniq', 'unique (name)', "Tag name already exists !"),
    ]
