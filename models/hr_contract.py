# -*- coding:utf-8 -*-
from odoo import _, api, fields, models
from datetime import timedelta, datetime, date
from dateutil.relativedelta import relativedelta

class HrContract(models.Model):
    _inherit = 'hr.contract'

    # ISR
    apply_isr = fields.Boolean(string="Aplicar ISR Fijo", default=False, tracking=True)
    amount_fixed_isr = fields.Float(string='Cuota Fija ISR', tracking=True)

    # BONO EDUCATIVO
    apply_education = fields.Boolean(string="Aplicar Educativo Fijo", default=False, tracking=True)
    amount_fixed_education = fields.Float(string='Cuota Fija Educativo', tracking=True)

    # COLEGIATURA
    apply_colegiatura = fields.Boolean(string="Aplicar Colegiatura Fijo", default=False,
                                     tracking=True)
    amount_fixed_colegiatura = fields.Float(string='Cuota Fija Colegiatura', tracking=True)

    # Pension
    apply_pension = fields.Boolean(string="Aplicar Pensión Fijo", default=False,
                                     tracking=True)
    amount_fixed_pension = fields.Float(string='Cuota Fija Pensión', tracking=True)

