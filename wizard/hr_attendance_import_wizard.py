# models/hr_attendance_import_wizard.py

import base64
import io
import logging
from datetime import datetime, timedelta

import pytz
from openpyxl import load_workbook
from odoo import models, fields

_logger = logging.getLogger(__name__)

class HrAttendanceImport(models.TransientModel):
    _name = "hr.attendance.import"
    _description = "Importar Asistencias desde Excel"

    file_data = fields.Binary("Archivo Excel", required=True)
    file_name = fields.Char("Nombre de archivo")

    def action_import(self):
        self.ensure_one()
        # 1) Abrir el Excel
        data = base64.b64decode(self.file_data)
        wb = load_workbook(filename=io.BytesIO(data), data_only=True)
        sheet = wb.active

        # 2) Parámetros de columnas
        IDX_TIEMPO = 0  # Columna A
        IDX_ID     = 6  # Columna G (ID/barcode)

        # 3) Timezone del usuario
        user_tz = self.env.user.tz or self.env.context.get('tz') or 'UTC'
        local_tz = pytz.timezone(user_tz)
        utc_tz   = pytz.utc

        # 4) Recolectar todos los timestamps por empleado (barcode)
        attend_list = {}
        for idx, row in enumerate(sheet.iter_rows(values_only=True), start=1):
            if idx == 1:
                continue  # salto encabezado
            raw   = row[IDX_TIEMPO]
            emp_id = row[IDX_ID]
            if not raw or not emp_id:
                continue

            # parseo a datetime
            if isinstance(raw, str):
                try:
                    tiempo = datetime.fromisoformat(raw)
                except ValueError:
                    tiempo = fields.Datetime.from_string(raw)
            else:
                tiempo = raw  # openpyxl ya lo entrega como datetime

            barcode = str(emp_id).strip()
            attend_list.setdefault(barcode, []).append(tiempo)

        # 5) Para cada empleado, emparejar timestamps en (check_in, check_out)
        for barcode, times in attend_list.items():
            # 5.1) ordenar
            times_sorted = sorted(times)

            # 5.2) filtrar duplicados dentro de 10 segundos
            umbral = timedelta(seconds=10)
            filtered = []
            for t in times_sorted:
                if not filtered or (t - filtered[-1]) > umbral:
                    filtered.append(t)
            times_sorted = filtered

            emp = self.env["hr.employee"].search([("barcode", "=", barcode)], limit=1)
            if not emp:
                _logger.warning("Empleado no encontrado para barcode %s", barcode)
                continue

            calendar = emp.resource_calendar_id

            # 5.3) iterar en pares: entrada → salida
            for i in range(0, len(times_sorted), 2):
                t_in_local = times_sorted[i]
                if i + 1 < len(times_sorted):
                    t_out_local = times_sorted[i + 1]
                else:
                    _logger.warning("Marca de salida faltante para %s @ %s", barcode, t_in_local)
                    continue

                # 5.4) turno nocturno: si la salida ≤ entrada, agrego un día
                if calendar.nocturna and t_out_local <= t_in_local:
                    t_out_local += timedelta(days=1)

                # 5.5) convertir de local a UTC
                dt_in_utc  = local_tz.localize(t_in_local).astimezone(utc_tz)
                dt_out_utc = local_tz.localize(t_out_local).astimezone(utc_tz)

                _logger.info("Import asist: %s IN=%s OUT=%s", barcode, dt_in_utc, dt_out_utc)

                # 5.6) crear registro de asistencia
                self.env["hr.attendance"].create({
                    "employee_id": emp.id,
                    "check_in":    dt_in_utc.strftime("%Y-%m-%d %H:%M:%S"),
                    "check_out":   dt_out_utc.strftime("%Y-%m-%d %H:%M:%S"),
                })

        # 6) cerrar wizard
        return {"type": "ir.actions.act_window_close"}
