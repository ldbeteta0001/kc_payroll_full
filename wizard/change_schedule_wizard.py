from odoo import api, fields, models, _

class ChangeWorkScheduleWizard(models.TransientModel):
    _name = 'hr.change.work.schedule.wizard'
    _description = 'Cambiar horario de trabajo en contratos y empleados'

    old_calendar_id = fields.Many2one(
        'resource.calendar',
        string='Horario actual',
        required=True,
        help='Horario que queremos reemplazar'
    )
    employee_ids = fields.Many2many(
        'hr.employee',
        string='Empleados',
        help='Lista de empleados con el horario seleccionado. Puedes eliminar algunos antes de aplicar.'
    )
    new_calendar_id = fields.Many2one(
        'resource.calendar',
        string='Nuevo horario',
        required=True,
        help='Horario que se asignará a los empleados y contratos seleccionados'
    )

    @api.onchange('old_calendar_id')
    def _onchange_old_calendar_id(self):
        if self.old_calendar_id:
            empleados = self.env['hr.employee'].search([
                ('resource_calendar_id', '=', self.old_calendar_id.id)
            ])
            # comando (6) reemplaza el set completo con los IDs encontrados
            self.employee_ids = [(6, 0, empleados.ids)]
        else:
            # limpia la lista
            self.employee_ids = [(5, 0, 0)]

    def apply_changes(self):
        for wiz in self:
            if not wiz.employee_ids:
                continue
            for empleado in wiz.employee_ids:
                # 1) Actualizar en la ficha de empleado
                empleado.write({'resource_calendar_id': wiz.new_calendar_id.id})

                # 2) Buscar contrato activo (state='open') y actualizar
                contrato = self.env['hr.contract'].search([
                    ('employee_id', '=', empleado.id),
                    ('state', '=', 'open'),
                ], limit=1)
                if contrato:
                    contrato.write({'resource_calendar_id': wiz.new_calendar_id.id})

        # Cierra el wizard
        return {'type': 'ir.actions.act_window_close'}
