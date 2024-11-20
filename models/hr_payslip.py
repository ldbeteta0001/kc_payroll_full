import logging
import random
import math
import pytz

from collections import defaultdict, Counter
from datetime import date, datetime, time
from dateutil.relativedelta import relativedelta

from odoo import api, Command, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.osv.expression import AND
from odoo.tools import float_round, date_utils, convert_file, format_amount
from odoo.tools.float_utils import float_compare
from odoo.tools.misc import format_date
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)

class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    def _get_worked_day_lines_values(self, domain=None):
        self.ensure_one()
        res = []
        hours_per_day = self._get_worked_day_lines_hours_per_day()
        work_hours = self.contract_id.get_work_hours(self.date_from, self.date_to,
                                                     domain=domain)
        work_hours_ordered = sorted(work_hours.items(), key=lambda x: x[1])
        biggest_work = work_hours_ordered[-1][0] if work_hours_ordered else 0
        add_days_rounding = 0

        # Buscar los tipos de entrada de trabajo por código
        attendance_work_entry_type = self.env['hr.work.entry.type'].search(
            [('code', '=', 'WORKED100')], limit=1)
        overtime_work_entry_type = self.env['hr.work.entry.type'].search(
            [('code', '=', 'OVERTIME')], limit=1)

        # Obtener asistencias para calcular las horas trabajadas dentro y fuera del horario laboral
        attendances = self.env['hr.attendance'].search([
            ('employee_id', '=', self.employee_id.id),
            ('check_in', '>=', self.date_from),
            ('check_out', '<=', self.date_to),
        ])

        # Sumar las horas dentro y fuera del horario laboral
        in_work_hours = sum(att.in_work_hours for att in attendances)
        out_work_hours = sum(att.out_work_hours for att in attendances)

        # Línea para WORKED100 (horas dentro del horario laboral)
        if in_work_hours > 0 and attendance_work_entry_type:
            in_work_days = round(in_work_hours / hours_per_day, 5) if hours_per_day else 0
            in_work_rounded = self._round_days(attendance_work_entry_type, in_work_days)
            res.append({
                'sequence': attendance_work_entry_type.sequence,
                'work_entry_type_id': attendance_work_entry_type.id,
                'number_of_days': in_work_rounded,
                'number_of_hours': in_work_hours,
            })

        # Línea para OVERTIME (horas fuera del horario laboral)
        if out_work_hours > 0 and overtime_work_entry_type:
            out_work_days = round(out_work_hours / hours_per_day,
                                  5) if hours_per_day else 0
            out_work_rounded = self._round_days(overtime_work_entry_type, out_work_days)
            res.append({
                'sequence': overtime_work_entry_type.sequence,
                'work_entry_type_id': overtime_work_entry_type.id,
                'number_of_days': out_work_rounded,
                'number_of_hours': out_work_hours,
            })

        # Lógica original para otras entradas de trabajo
        for work_entry_type_id, hours in work_hours_ordered:
            work_entry_type = self.env['hr.work.entry.type'].browse(work_entry_type_id)
            days = round(hours / hours_per_day, 5) if hours_per_day else 0
            if work_entry_type_id == biggest_work:
                days += add_days_rounding
            day_rounded = self._round_days(work_entry_type, days)
            add_days_rounding += (days - day_rounded)
            attendance_line = {
                'sequence': work_entry_type.sequence,
                'work_entry_type_id': work_entry_type_id,
                'number_of_days': day_rounded,
                'number_of_hours': hours,
            }
            res.append(attendance_line)

        # Ordenar las líneas por secuencia
        work_entry_type = self.env['hr.work.entry.type']
        return sorted(res, key=lambda d: work_entry_type.browse(
            d['work_entry_type_id']).sequence)

    def _get_worked_day_lines(self, domain=None, check_out_of_contract=True):
        """
        :returns: una lista de dict con los valores de días trabajados aplicables a la nómina
        """
        res = []
        self.ensure_one()
        contract = self.contract_id

        if contract.resource_calendar_id:
            # Llama a la función que calcula las líneas de días trabajados
            res = self._get_worked_day_lines_values(domain=domain)
            if not check_out_of_contract:
                return res

            # Manejar días fuera del contrato (si aplica)
            out_days, out_hours = 0, 0
            reference_calendar = self._get_out_of_contract_calendar()
            if self.date_from < contract.date_start:
                start = fields.Datetime.to_datetime(self.date_from)
                stop = fields.Datetime.to_datetime(contract.date_start) + relativedelta(
                    days=-1, hour=23, minute=59)
                out_time = reference_calendar.get_work_duration_data(
                    start, stop, compute_leaves=False,
                    domain=['|', ('work_entry_type_id', '=', False),
                            ('work_entry_type_id.is_leave', '=', False)]
                )
                out_days += out_time['days']
                out_hours += out_time['hours']
            if contract.date_end and contract.date_end < self.date_to:
                start = fields.Datetime.to_datetime(contract.date_end) + relativedelta(
                    days=1)
                stop = fields.Datetime.to_datetime(self.date_to) + relativedelta(hour=23,
                                                                                 minute=59)
                out_time = reference_calendar.get_work_duration_data(
                    start, stop, compute_leaves=False,
                    domain=['|', ('work_entry_type_id', '=', False),
                            ('work_entry_type_id.is_leave', '=', False)]
                )
                out_days += out_time['days']
                out_hours += out_time['hours']

            if out_days or out_hours:
                work_entry_type = self.env['hr.work.entry.type'].search(
                    [('code', '=', 'OUT_OF_CONTRACT')], limit=1)
                if work_entry_type:
                    res.append({
                        'sequence': work_entry_type.sequence,
                        'work_entry_type_id': work_entry_type.id,
                        'number_of_days': out_days,
                        'number_of_hours': out_hours,
                    })

        return res
