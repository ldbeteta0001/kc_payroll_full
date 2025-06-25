# models/hr_attendance.py

from odoo import models, fields, api
from datetime import datetime


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    # Campo para guardar la hora del horario (para cálculos)
    check_in_schedule = fields.Datetime(
        string="Entrada según Horario",
        help="Hora de entrada ajustada según el horario de trabajo del empleado. Se usa para calcular las horas trabajadas."
    )

    # Campo para marcar asistencias parciales
    is_partial = fields.Boolean(
        string="Asistencia Parcial",
        default=False,
        help="Indica si esta asistencia está incompleta (solo entrada o solo salida)"
    )

    partial_type = fields.Selection([
        ('entry_only', 'Solo Entrada'),
        ('exit_only', 'Solo Salida'),
        ('complete', 'Completa')
    ], string="Tipo de Asistencia", default='complete')

    # Campo para mostrar la diferencia
    check_in_difference = fields.Float(
        string="Diferencia Entrada (min)",
        compute='_compute_check_in_difference',
        store=True,
        help="Diferencia en minutos entre la hora real de entrada y la hora del horario"
    )

    @api.depends('check_in', 'check_in_schedule')
    def _compute_check_in_difference(self):
        for record in self:
            if record.check_in and record.check_in_schedule:
                # Calcular diferencia en minutos
                real_time = fields.Datetime.from_string(record.check_in)
                schedule_time = fields.Datetime.from_string(record.check_in_schedule)
                diff = (real_time - schedule_time).total_seconds() / 60
                record.check_in_difference = round(diff, 2)
            else:
                record.check_in_difference = 0.0

    @api.depends('check_in', 'check_out', 'check_in_schedule')
    def _compute_worked_hours(self):
        """
        Sobrescribir el cálculo de horas trabajadas para usar check_in_schedule
        en lugar de check_in cuando esté disponible
        """
        for attendance in self:
            if attendance.check_out and (
                    attendance.check_in_schedule or attendance.check_in):
                # Usar check_in_schedule si está disponible, sino check_in
                start_time = attendance.check_in_schedule or attendance.check_in
                end_time = attendance.check_out

                delta = end_time - start_time
                attendance.worked_hours = delta.total_seconds() / 3600.0
            else:
                attendance.worked_hours = False

    def complete_partial_attendance(self, check_out_time, check_out_schedule=None):
        """
        Completa una asistencia parcial con la salida
        """
        self.ensure_one()
        if not self.is_partial or self.partial_type != 'entry_only':
            return False

        self.write({
            'check_out': check_out_time,
            'is_partial': False,
            'partial_type': 'complete'
        })
        return True

    def name_get(self):
        """
        Personalizar la visualización para mostrar estado parcial
        """
        result = []
        for attendance in self:
            name = f"{attendance.employee_id.name}"

            if attendance.is_partial:
                if attendance.partial_type == 'entry_only':
                    time_str = fields.Datetime.context_timestamp(attendance,
                                                                 attendance.check_in).strftime(
                        '%H:%M')
                    name += f" - Entrada: {time_str} (PARCIAL)"
                elif attendance.partial_type == 'exit_only':
                    time_str = fields.Datetime.context_timestamp(attendance,
                                                                 attendance.check_out).strftime(
                        '%H:%M')
                    name += f" - Salida: {time_str} (PARCIAL)"
            else:
                # Comportamiento normal para asistencias completas
                if attendance.check_in_schedule and attendance.check_in != attendance.check_in_schedule:
                    real_time = fields.Datetime.context_timestamp(attendance,
                                                                  attendance.check_in)
                    schedule_time = fields.Datetime.context_timestamp(attendance,
                                                                      attendance.check_in_schedule)
                    name += f" - Real: {real_time.strftime('%H:%M')} / Horario: {schedule_time.strftime('%H:%M')}"
                else:
                    check_time = fields.Datetime.context_timestamp(attendance,
                                                                   attendance.check_in or attendance.check_out)
                    name += f" - {check_time.strftime('%Y-%m-%d %H:%M')}"

            result.append((attendance.id, name))
        return result