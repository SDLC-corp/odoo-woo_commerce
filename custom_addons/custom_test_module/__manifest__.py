# -*- coding: utf-8 -*-
{
    "name": "Custom Test Module",
    "summary": "Basic sample custom module for Odoo 19",
    "version": "19.0.1.0.0",
    "category": "Tools",
    "author": "Local",
    "license": "LGPL-3",
    "depends": ["base"],
    "data": [
        "security/ir.model.access.csv",
        "views/custom_test_module_views.xml"
    ],
    "application": True,
    "installable": True,
}
