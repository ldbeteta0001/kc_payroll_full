# models/hr_employee.py
from odoo import api, fields, models, _


class HrEmployee(models.Model):
    """Extender modelo de empleado para integrar historial"""
    _inherit = 'hr.employee'

    schedule_history_ids = fields.One2many(
        'hr.employee.schedule.history',
        'employee_id',
        string='Historial de horarios'
    )
    current_schedule_history_id = fields.Many2one(
        'hr.employee.schedule.history',
        string='Horario actual',
        compute='_compute_current_schedule_history'
    )
    last_schedule_change = fields.Date(
        string='Último cambio de horario',
        help='Fecha del último cambio de horario'
    )

    @api.depends('schedule_history_ids.is_current')
    def _compute_current_schedule_history(self):
        for employee in self:
            current = employee.schedule_history_ids.filtered('is_current')
            employee.current_schedule_history_id = current[0] if current else False

    def create_schedule_history(self, calendar_id, date_from, reason=None):
        """Crea un registro de historial de horario"""
        # Obtener el horario anterior
        previous_calendar = self.resource_calendar_id

        # Cerrar el registro actual si existe
        current_history = self.schedule_history_ids.filtered('is_current')
        if current_history:
            from datetime import timedelta
            current_history.write({'date_to': date_from - timedelta(days=1)})

        # Crear nuevo registro con horario anterior guardado
        new_record = self.env['hr.employee.schedule.history'].create({
            'employee_id': self.id,
            'resource_calendar_id': calendar_id,
            'previous_calendar_id': previous_calendar.id if previous_calendar else False,
            'date_from': date_from,
            'reason': reason or _('Cambio de horario')
        })

        # Actualizar fecha de último cambio
        self.write({'last_schedule_change': date_from})

        return new_record