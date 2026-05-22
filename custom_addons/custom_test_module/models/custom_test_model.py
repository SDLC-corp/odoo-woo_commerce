# -*- coding: utf-8 -*-
from odoo import fields, models


class CustomTestModel(models.Model):
    _name = "custom.test.module"
    _description = "Custom Test Module"

    name = fields.Char(required=True)
    description = fields.Text()
    active = fields.Boolean(default=True)
