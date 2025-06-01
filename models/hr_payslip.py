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

    # MODIFICACIÓN PARA TU MÉTODO _get_worked_day_lines_values
    # Agregar filtro de días laborables

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
            [('code', '=', 'WORK100')], limit=1)

        # Buscar tipos de entrada para horas extras por franjas
        he25_work_entry_type = self.env['hr.work.entry.type'].search(
            [('code', '=', 'HE25')], limit=1)
        he50_work_entry_type = self.env['hr.work.entry.type'].search(
            [('code', '=', 'HE50')], limit=1)
        he75_work_entry_type = self.env['hr.work.entry.type'].search(
            [('code', '=', 'HE75')], limit=1)

        # Usar un conjunto para almacenar los tipos de trabajo ya procesados
        processed_entry_types = set()

        # FILTRAR ASISTENCIAS SOLO DE LUNES A VIERNES
        all_attendances = self.env['hr.attendance'].search([
            ('employee_id', '=', self.employee_id.id),
            ('check_in', '>=', self.date_from),
            ('check_out', '<=', self.date_to),
        ])

        # Filtrar solo días laborables (lunes=0 a viernes=4)
        weekday_attendances = []
        for att in all_attendances:
            if att.check_in:
                weekday = att.check_in.weekday()  # 0=lunes, 6=domingo
                if 0 <= weekday <= 4:  # lunes a viernes
                    weekday_attendances.append(att)

        print("Asistencias filtradas (lun-vie):", len(weekday_attendances))

        # Sumar las horas dentro del horario laboral (solo días laborables)
        in_work_hours = sum(att.worked_hours for att in weekday_attendances)
        print('HORAS DE ENTRADA (lun-vie):', in_work_hours)

        # Calcular totales de horas extras por franja (solo días laborables)
        total_he25 = sum(att.he25 for att in weekday_attendances)
        total_he50 = sum(att.he50 for att in weekday_attendances)
        total_he75 = sum(att.he75 for att in weekday_attendances)

        print('HORAS EXTRA 25% (lun-vie):', total_he25)
        print('HORAS EXTRA 50% (lun-vie):', total_he50)
        print('HORAS EXTRA 75% (lun-vie):', total_he75)

        # Línea para WORK100 (horas dentro del horario laboral - solo días laborables)
        if in_work_hours > 0 and attendance_work_entry_type:
            if attendance_work_entry_type.id not in processed_entry_types:
                in_work_days = round(in_work_hours / hours_per_day,
                                     5) if hours_per_day else 0
                in_work_rounded = self._round_days(attendance_work_entry_type,
                                                   in_work_days)
                res.append({
                    'sequence': attendance_work_entry_type.sequence,
                    'work_entry_type_id': attendance_work_entry_type.id,
                    'number_of_days': in_work_rounded,
                    'number_of_hours': in_work_hours,
                })
                processed_entry_types.add(attendance_work_entry_type.id)

        # Línea para Horas Extra 25% (solo días laborables)
        if total_he25 > 0 and he25_work_entry_type:
            if he25_work_entry_type.id not in processed_entry_types:
                he25_days = round(total_he25 / hours_per_day, 5) if hours_per_day else 0
                he25_rounded = self._round_days(he25_work_entry_type, he25_days)
                res.append({
                    'sequence': he25_work_entry_type.sequence,
                    'work_entry_type_id': he25_work_entry_type.id,
                    'number_of_days': he25_rounded,
                    'number_of_hours': total_he25,
                })
                processed_entry_types.add(he25_work_entry_type.id)

        # Línea para Horas Extra 50% (solo días laborables)
        if total_he50 > 0 and he50_work_entry_type:
            if he50_work_entry_type.id not in processed_entry_types:
                he50_days = round(total_he50 / hours_per_day, 5) if hours_per_day else 0
                he50_rounded = self._round_days(he50_work_entry_type, he50_days)
                res.append({
                    'sequence': he50_work_entry_type.sequence,
                    'work_entry_type_id': he50_work_entry_type.id,
                    'number_of_days': he50_rounded,
                    'number_of_hours': total_he50,
                })
                processed_entry_types.add(he50_work_entry_type.id)

        # Línea para Horas Extra 75% (solo días laborables)
        if total_he75 > 0 and he75_work_entry_type:
            if he75_work_entry_type.id not in processed_entry_types:
                he75_days = round(total_he75 / hours_per_day, 5) if hours_per_day else 0
                he75_rounded = self._round_days(he75_work_entry_type, he75_days)
                res.append({
                    'sequence': he75_work_entry_type.sequence,
                    'work_entry_type_id': he75_work_entry_type.id,
                    'number_of_days': he75_rounded,
                    'number_of_hours': total_he75,
                })
                processed_entry_types.add(he75_work_entry_type.id)

        # Resto de la lógica original...
        for work_entry_type_id, hours in work_hours_ordered:
            work_entry_type = self.env['hr.work.entry.type'].browse(work_entry_type_id)
            if work_entry_type.id not in processed_entry_types:
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
                processed_entry_types.add(work_entry_type.id)

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