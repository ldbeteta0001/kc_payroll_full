from odoo import fields, models, api



class ResourceCalendar(models.Model):
    _inherit = 'resource.calendar'

    nocturna = fields.Boolean(
        string='Turno Nocturno',
        help="Marcar si el horario abarca medianoche"
    )

    es_nomina_semanal = fields.Boolean(
        string='Nómina Semanal',
        help='Indica que este calendario se utiliza para nóminas semanales'
    )