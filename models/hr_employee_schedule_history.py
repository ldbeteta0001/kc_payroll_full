# models/hr_employee_schedule_history.py
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from datetime import date, datetime


class HrEmployeeScheduleHistory(models.Model):
    """Modelo para mantener historial de horarios por empleado"""
    _name = 'hr.employee.schedule.history'
    _description = 'Historial de horarios de empleados'
    _order = 'employee_id, date_from desc'
    _rec_name = 'display_name'

    employee_id = fields.Many2one(
        'hr.employee',
        string='Empleado',
        required=True,
        ondelete='cascade'
    )
    resource_calendar_id = fields.Many2one(
        'resource.calendar',
        string='Horario de trabajo',
        required=True
    )
    previous_calendar_id = fields.Many2one(
        'resource.calendar',
        string='Horario anterior',
        help='Horario que tenía el empleado antes de este cambio'
    )
    date_from = fields.Date(
        string='Fecha desde',
        required=True,
        default=fields.Date.today
    )
    date_to = fields.Date(
        string='Fecha hasta',
        help='Dejar vacío si es el horario actual'
    )
    is_current = fields.Boolean(
        string='Es actual',
        compute='_compute_is_current',
        store=True
    )
    reason = fields.Text(
        string='Motivo del cambio',
        help='Descripción del por qué se cambió el horario'
    )
    changed_by = fields.Many2one(
        'res.users',
        string='Cambiado por',
        default=lambda self: self.env.user,
        required=True
    )
    display_name = fields.Char(
        string='Nombre',
        compute='_compute_display_name'
    )

    @api.depends('date_to')
    def _compute_is_current(self):
        for record in self:
            record.is_current = not record.date_to

    @api.depends('employee_id', 'resource_calendar_id', 'date_from', 'date_to')
    def _compute_display_name(self):
        for record in self:
            if record.employee_id and record.resource_calendar_id:
                date_range = f"desde {record.date_from}"
                if record.date_to:
                    date_range = f"{record.date_from} - {record.date_to}"
                record.display_name = f"{record.employee_id.name} - {record.resource_calendar_id.name} ({date_range})"
            else:
                record.display_name = "Nuevo registro"

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for record in self:
            if record.date_to and record.date_from > record.date_to:
                raise ValidationError(
                    _('La fecha de inicio no puede ser mayor que la fecha de fin.'))

    @api.constrains('employee_id', 'date_from', 'date_to')
    def _check_overlapping_periods(self):
        for record in self:
            domain = [
                ('employee_id', '=', record.employee_id.id),
                ('id', '!=', record.id)
            ]

            if record.date_to:
                # Periodo con fecha fin definida
                domain.extend([
                    '|',
                    '&', ('date_from', '<=', record.date_from),
                    '|', ('date_to', '>=', record.date_from), ('date_to', '=', False),
                    '&', ('date_from', '<=', record.date_to),
                    '|', ('date_to', '>=', record.date_to), ('date_to', '=', False)
                ])
            else:
                # Periodo actual (sin fecha fin)
                domain.extend([
                    '|', ('date_to', '=', False), ('date_to', '>=', record.date_from)
                ])

            overlapping = self.search(domain)
            if overlapping:
                raise ValidationError(_(
                    'Ya existe un registro de horario para este empleado en el período seleccionado.'
                ))

    @api.model
    def create(self, vals):
        """Al crear registro, actualizar empleado y contrato automáticamente"""
        record = super().create(vals)

        # Si no tiene fecha_to (es actual), actualizar empleado y contrato
        if not record.date_to:
            employee = record.employee_id

            # Actualizar empleado
            employee.write({
                'resource_calendar_id': record.resource_calendar_id.id,
                'last_schedule_change': record.date_from
            })

            # Actualizar contratos activos
            contratos = self.env['hr.contract'].search([
                ('employee_id', '=', employee.id),
                ('state', '=', 'open'),
            ])
            if contratos:
                contratos.write({'resource_calendar_id': record.resource_calendar_id.id})

        return record

    def write(self, vals):
        """Al modificar registro, actualizar empleado y contrato si es necesario"""
        result = super().write(vals)

        for record in self:
            # Si se está marcando como actual (date_to = False), actualizar empleado
            if 'date_to' in vals and not vals['date_to'] and record.is_current:
                employee = record.employee_id

                # Actualizar empleado
                employee.write({
                    'resource_calendar_id': record.resource_calendar_id.id,
                    'last_schedule_change': fields.Date.today()
                })

                # Actualizar contratos activos
                contratos = self.env['hr.contract'].search([
                    ('employee_id', '=', employee.id),
                    ('state', '=', 'open'),
                ])
                if contratos:
                    contratos.write(
                        {'resource_calendar_id': record.resource_calendar_id.id})

        return result

    def get_schedule_at_date(self, employee_id, target_date):
        """Obtiene el horario de un empleado en una fecha específica"""
        record = self.search([
            ('employee_id', '=', employee_id),
            ('date_from', '<=', target_date),
            '|', ('date_to', '>=', target_date), ('date_to', '=', False)
        ], limit=1)
        return record.resource_calendar_id if record else False

    def apply_current_schedule(self):
        """Aplica ESTE registro como horario actual (para registros creados manualmente)"""
        self.ensure_one()

        # Cerrar otros registros actuales del mismo empleado
        current_records = self.env['hr.employee.schedule.history'].search([
            ('employee_id', '=', self.employee_id.id),
            ('is_current', '=', True),
            ('id', '!=', self.id)
        ])
        if current_records:
            current_records.write({'date_to': fields.Date.today()})

        # NO MODIFICAR las fechas de este registro - solo aplicar el horario
        # El registro mantiene sus fechas originales

        # Actualizar el empleado y contratos
        self.employee_id.write({
            'resource_calendar_id': self.resource_calendar_id.id,
            'last_schedule_change': fields.Date.today()
        })

        # Actualizar contratos activos
        contratos = self.env['hr.contract'].search([
            ('employee_id', '=', self.employee_id.id),
            ('state', '=', 'open'),
        ])
        if contratos:
            contratos.write({'resource_calendar_id': self.resource_calendar_id.id})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Registro aplicado'),
                'message': _(
                    'Se aplicó el horario "%s" a %s manteniendo las fechas del registro') % (
                               self.resource_calendar_id.name, self.employee_id.name
                           ),
                'type': 'success'
            }
        }

    def copy_and_create_schedule(self):
        """Crea un NUEVO registro basado en este histórico desde hoy"""
        self.ensure_one()

        # Cerrar el registro actual
        current_records = self.env['hr.employee.schedule.history'].search([
            ('employee_id', '=', self.employee_id.id),
            ('is_current', '=', True)
        ])
        if current_records:
            current_records.write({'date_to': fields.Date.today()})

        # Crear nuevo registro basado en este histórico
        new_record = self.env['hr.employee.schedule.history'].create({
            'employee_id': self.employee_id.id,
            'resource_calendar_id': self.resource_calendar_id.id,
            'previous_calendar_id': self.employee_id.resource_calendar_id.id,
            'date_from': fields.Date.today(),
            'date_to': False,  # Sin fecha fin = actual
            'reason': _('Copiado desde registro histórico del %s - %s') % (
                self.date_from,
                self.reason or 'Sin motivo especificado'
            )
        })

        # Actualizar el empleado y contratos
        self.employee_id.write({
            'resource_calendar_id': self.resource_calendar_id.id,
            'last_schedule_change': fields.Date.today()
        })

        # Actualizar contratos activos
        contratos = self.env['hr.contract'].search([
            ('employee_id', '=', self.employee_id.id),
            ('state', '=', 'open'),
        ])
        if contratos:
            contratos.write({'resource_calendar_id': self.resource_calendar_id.id})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Nuevo registro creado'),
                'message': _(
                    'Se creó nuevo registro desde hoy y se aplicó el horario "%s" a %s') % (
                               self.resource_calendar_id.name,
                               self.employee_id.name
                           ),
                'type': 'success'
            }
        }

    def create_and_apply_schedule(self):
        """Crea un NUEVO registro basado en este y lo aplica como actual"""
        self.ensure_one()

        # Crear nuevo registro basado en este
        reason = _('Copiado y aplicado desde registro del %s') % self.date_from

        new_record = self.employee_id.create_schedule_history(
            calendar_id=self.resource_calendar_id.id,
            date_from=fields.Date.today(),
            reason=reason
        )

        # Actualizar el empleado y contratos
        self.employee_id.write({
            'resource_calendar_id': self.resource_calendar_id.id,
            'last_schedule_change': fields.Date.today()
        })

        # Actualizar contratos activos
        contratos = self.env['hr.contract'].search([
            ('employee_id', '=', self.employee_id.id),
            ('state', '=', 'open'),
        ])
        if contratos:
            contratos.write({'resource_calendar_id': self.resource_calendar_id.id})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Horario aplicado'),
                'message': _(
                    'Se creó nuevo registro y se aplicó el horario "%s" a %s') % (
                               self.resource_calendar_id.name,
                               self.employee_id.name
                           ),
                'type': 'success'
            }
        }

    def action_apply_multiple_schedules(self):
        """Acción para aplicar múltiples horarios seleccionados"""
        if not self:
            raise ValidationError(_('Debe seleccionar al menos un registro.'))

        applied_count = 0
        errors = []

        for record in self:
            try:
                if record.is_current:
                    continue  # Saltar los que ya están activos

                # Aplicar el horario
                record.apply_schedule_from_history()
                applied_count += 1

            except Exception as e:
                errors.append(_('%s: %s') % (record.employee_id.name, str(e)))

        # Mostrar resultado
        if errors:
            message = _('Algunos horarios no pudieron aplicarse:\n%s') % '\n'.join(errors)
            if applied_count > 0:
                message += _('\n\nHorarios aplicados exitosamente: %d') % applied_count

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Aplicación parcial'),
                    'message': message,
                    'type': 'warning',
                    'sticky': True
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Éxito'),
                    'message': _(
                        'Se aplicaron %d horario(s) correctamente') % applied_count,
                    'type': 'success'
                }
            }

    def action_view_employee(self):
        """Acción para ver el empleado desde el historial"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Empleado'),
            'res_model': 'hr.employee',
            'res_id': self.employee_id.id,
            'view_mode': 'form',
            'target': 'current'
        }