from odoo import api, fields, models
from datetime import datetime, time, timedelta
import pytz


class HRAttendance(models.Model):
    _inherit = 'hr.attendance'

    he25 = fields.Float(string="Horas Extra 25%", compute="_compute_he_franjas",
                        store=True, readonly=True)
    he50 = fields.Float(string="Horas Extra 50%", compute="_compute_he_franjas",
                        store=True, readonly=True)
    he75 = fields.Float(string="Horas Extra 75%", compute="_compute_he_franjas",
                        store=True, readonly=True)
    sabado_acum = fields.Float(string="Horas Acumuladas Sábado",
                               compute="_compute_he_franjas",
                               store=True, readonly=True)
    dummy_total = fields.Float(string="Total HE", compute="_compute_he_total",
                               store=False)

    def _safe_time_from_float(self, base_date, hour_float):
        """Convertir hora flotante a datetime de forma segura, manejando valores >= 24."""
        hours, minutes = divmod(hour_float * 60, 60)
        hours = int(hours)
        minutes = int(minutes)

        # Si las horas son >= 24, agregar días
        days_offset = hours // 24
        hours = hours % 24

        target_date = base_date + timedelta(days=days_offset)
        return datetime.combine(target_date, time(hours, minutes))

    @api.depends('he25', 'he50', 'he75', 'sabado_acum')
    def _compute_he_total(self):
        for rec in self:
            rec.dummy_total = rec.he25 + rec.he50 + rec.he75

    @api.depends('check_in', 'check_out', 'employee_id')
    def _compute_he_franjas(self):
        for rec in self:
            rec.he25 = rec.he50 = rec.he75 = rec.sabado_acum = 0.0

            # Validar que tengamos check_in y check_out
            if not (rec.check_in and rec.check_out):
                continue

            # ——————————————————————————————
            # 1) Obtener contrato y calendario
            # ——————————————————————————————
            contract = rec.employee_id.contract_id
            if not contract:
                continue

            calendar = contract.resource_calendar_id or rec.employee_id.resource_calendar_id
            if not calendar:
                continue

            # Día de la semana como string '0'..'6' (lunes=0, domingo=6)
            dow = str(rec.check_in.weekday())

            # Filtrar TODAS las líneas de asistencia de ese día
            lines = calendar.attendance_ids.filtered(lambda l: l.dayofweek == dow).sorted(
                'hour_from')

            # EXCEPCIÓN: Para sábados en jornada 60h diurna, no requerir líneas de calendario
            full_req = contract.full_time_required_hours or 0
            nocturna = calendar.nocturna if hasattr(calendar, 'nocturna') else False
            weekday = rec.check_in.weekday()

            is_saturday_60h_day = (full_req == 60 and not nocturna and weekday == 5)

            if not lines and not is_saturday_60h_day:
                continue

            # ——————————————————————————————
            # 2) Construir horarios programados (todas las líneas)
            # ——————————————————————————————
            day = rec.check_in.date()

            # IMPORTANTE: Trabajar en la misma timezone que check_in y check_out
            # Si check_in tiene timezone, usar esa. Si no, asumir UTC y convertir a local
            user_tz = pytz.timezone(self.env.user.tz or 'America/Tegucigalpa')

            if rec.check_in.tzinfo:
                local_check_in = rec.check_in.astimezone(user_tz).replace(tzinfo=None)
                local_check_out = rec.check_out.astimezone(user_tz).replace(tzinfo=None)
            else:
                # Asumir que son UTC y convertir a local
                check_in_utc = pytz.UTC.localize(rec.check_in)
                check_out_utc = pytz.UTC.localize(rec.check_out)
                local_check_in = check_in_utc.astimezone(user_tz).replace(tzinfo=None)
                local_check_out = check_out_utc.astimezone(user_tz).replace(tzinfo=None)

            day = local_check_in.date()

            # Obtener configuraciones
            full_req = contract.full_time_required_hours or 0
            nocturna = calendar.nocturna if hasattr(calendar, 'nocturna') else False
            actual_out = local_check_out  # Usar la versión local

            # ——————————————————————————————
            # 3) Caso: 60h/semana DIURNO
            # ——————————————————————————————
            if full_req == 60 and not nocturna:
                # Obtener día de la semana (0=lunes, 5=sábado, 6=domingo)
                weekday = local_check_in.weekday()

                # DEBUG: Log para verificar
                import logging
                _logger = logging.getLogger(__name__)
                _logger.info(
                    f"DEBUG HE: Empleado {rec.employee_id.name}, fecha {local_check_in.date()}, weekday={weekday}, es_sabado={weekday == 5}")

                # SÁBADO (weekday == 5): Todo el tiempo trabajado es HE25
                if weekday == 5:  # Sábado
                    # En sábado, toda la jornada es HE25
                    total_hours = (actual_out - local_check_in).total_seconds() / 3600.0
                    rec.he25 = max(0, total_hours)

                # VIERNES (weekday == 4): Horario especial 06:00-18:00
                elif weekday == 4:  # Viernes
                    # Viernes: 06:00-14:00 ordinarias, 14:00-18:00 HE25
                    ordinary_end = datetime.combine(day, time(14, 0))  # 14:00
                    he25_end = datetime.combine(day, time(18, 0))  # 18:00

                    # HE25: desde 14:00 hasta cuando salga (máximo 18:00 para esta franja)
                    if actual_out > ordinary_end:
                        he25_hours = (min(actual_out,
                                          he25_end) - ordinary_end).total_seconds() / 3600.0
                        rec.he25 = max(0, he25_hours)

                    # Si trabaja después de las 18:00, aplicar franjas normales
                    if actual_out > he25_end:
                        # Desde 18:00 en adelante, usar lógica normal de HE
                        w50_end = datetime.combine(day,
                                                   time(23, 59, 59))  # he50: 18:00-00:00
                        w75_start = datetime.combine(day + timedelta(days=1),
                                                     time(0, 0))  # he75: 00:00-05:00
                        w75_end = datetime.combine(day + timedelta(days=1), time(5, 0))

                        # Agregar HE50: de 18:00 a 00:00
                        if actual_out > he25_end:
                            he50_hours = (min(actual_out,
                                              w50_end) - he25_end).total_seconds() / 3600.0
                            rec.he50 = max(0, he50_hours)

                        # HE75: de 00:00 a 05:00
                        if actual_out > w75_start:
                            he75_hours = (min(actual_out,
                                              w75_end) - w75_start).total_seconds() / 3600.0
                            rec.he75 = max(0, he75_hours)

                else:
                    # DÍAS NORMALES (lunes-jueves): Lógica original
                    # Para 60h diurno: las horas extra empiezan después de 8 horas trabajadas
                    # O a las 15:00 (8h después de las 06:00), lo que sea más tarde

                    # Tiempo cuando completó 8 horas desde check-in
                    eight_hours_from_checkin = local_check_in + timedelta(hours=8)

                    # Tiempo fijo: 15:00 (asumiendo jornada estándar desde 06:00)
                    fixed_overtime_start = datetime.combine(day, time(15, 0))

                    # Las HE empiezan cuando se complete el mayor de los dos
                    overtime_start = max(eight_hours_from_checkin, fixed_overtime_start)

                    # Si sale antes del inicio de overtime, no hay horas extra
                    if actual_out <= overtime_start:
                        continue

                    # Ventanas de horas extra
                    w25_end = datetime.combine(day, time(19,
                                                         0))  # he25: desde overtime_start hasta 19:00
                    w50_end = datetime.combine(day, time(23, 59, 59))  # he50: 19:00-00:00
                    w75_start = datetime.combine(day + timedelta(days=1),
                                                 time(0, 0))  # he75: 00:00-05:00
                    w75_end = datetime.combine(day + timedelta(days=1), time(5, 0))

                    # HE25: desde overtime_start hasta 19:00
                    if actual_out > overtime_start:
                        he25_hours = (min(actual_out,
                                          w25_end) - overtime_start).total_seconds() / 3600.0
                        rec.he25 = max(0, he25_hours)

                    # HE50: de 19:00 a 00:00
                    if actual_out > w25_end:
                        he50_hours = (min(actual_out,
                                          w50_end) - w25_end).total_seconds() / 3600.0
                        rec.he50 = max(0, he50_hours)

                    # HE75: de 00:00 a 05:00
                    if actual_out > w75_start:
                        he75_hours = (min(actual_out,
                                          w75_end) - w75_start).total_seconds() / 3600.0
                        rec.he75 = max(0, he75_hours)

            # ——————————————————————————————
            # 4) Caso: 60h/semana NOCTURNO
            # ——————————————————————————————
            elif full_req == 60 and nocturna:
                # Jornada esperada: 18:00-06:00 (cruza medianoche)
                # ORDINARIAS: 18:00-01:00 (7 horas normales)
                # HE75: 01:00-06:00 (5 horas extra al 75%)

                ordinary_start = datetime.combine(day, time(18, 0))  # 18:00
                ordinary_end = datetime.combine(day + timedelta(days=1),
                                                time(1, 0))  # 01:00
                he75_start = ordinary_end  # 01:00
                he75_end = datetime.combine(day + timedelta(days=1), time(6, 0))  # 06:00

                # Solo calcular HE75 si trabaja después de la 01:00
                if actual_out > he75_start:
                    rec.he75 = max(0, (min(actual_out,
                                           he75_end) - he75_start).total_seconds() / 3600.0)

                # No hay HE25 ni HE50 en jornada nocturna estándar
                # Las primeras 7 horas (18:00-01:00) son tiempo ordinario

            # ——————————————————————————————
            # 5) Caso: 44h/semana DIURNO
            # ——————————————————————————————
            elif full_req == 44 and not nocturna:
                # Solo procesar si hay líneas de calendario
                if not lines:
                    continue

                # Horario esperado: 07:30-16:30
                # 07:30-15:30 = 8h ordinarias
                # 15:30-16:30 = 1h acumulada para sábado
                # 16:30-19:00 = HE25
                # 19:00-22:00 = HE50
                # 22:00-06:00 = HE75

                # Puntos de tiempo importantes
                ordinary_end = datetime.combine(day, time(15, 30))  # Fin de 8h ordinarias
                saturday_acum_end = datetime.combine(day, time(16,
                                                               30))  # Fin de hora acumulada
                he25_end = datetime.combine(day, time(19, 0))  # Fin de HE25
                he50_end = datetime.combine(day, time(22, 0))  # Fin de HE50
                he75_end = datetime.combine(day + timedelta(days=1),
                                            time(6, 0))  # Fin de HE75

                # 1) Hora acumulada para sábado: 15:30-16:30
                if actual_out > ordinary_end:
                    sabado_hours = (min(actual_out,
                                        saturday_acum_end) - ordinary_end).total_seconds() / 3600.0
                    rec.sabado_acum = max(0, sabado_hours)

                # 2) HE25: 16:30-19:00
                if actual_out > saturday_acum_end:
                    he25_hours = (min(actual_out,
                                      he25_end) - saturday_acum_end).total_seconds() / 3600.0
                    rec.he25 = max(0, he25_hours)

                # 3) HE50: 19:00-22:00
                if actual_out > he25_end:
                    he50_hours = (min(actual_out,
                                      he50_end) - he25_end).total_seconds() / 3600.0
                    rec.he50 = max(0, he50_hours)

                # 4) HE75: 22:00-06:00 (cruza medianoche)
                if actual_out > he50_end:
                    he75_hours = (min(actual_out,
                                      he75_end) - he50_end).total_seconds() / 3600.0
                    rec.he75 = max(0, he75_hours)

            # ——————————————————————————————
            # 6) Redondeo final
            # ——————————————————————————————
            rec.he25 = round(rec.he25, 2)
            rec.he50 = round(rec.he50, 2)
            rec.he75 = round(rec.he75, 2)
            rec.sabado_acum = round(rec.sabado_acum, 2)

    def action_recompute_he(self):
        """Botón para forzar el recálculo de horas extra en este registro."""
        try:
            # Escribir directamente en la base de datos para forzar el reseteo
            for rec in self:
                # Reseteo directo en BD
                rec.write({
                    'he25': 0.0,
                    'he50': 0.0,
                    'he75': 0.0,
                    'sabado_acum': 0.0
                })

            # Invalidar caché y recalcular
            self.invalidate_recordset(['he25', 'he50', 'he75', 'sabado_acum'])
            self._compute_he_franjas()

            # Mensaje de confirmación
            message = f"Recálculo completado:\n"
            for rec in self:
                message += f"• HE25: {rec.he25:.2f}h\n"
                message += f"• HE50: {rec.he50:.2f}h\n"
                message += f"• HE75: {rec.he75:.2f}h\n"
                message += f"• Sábado Acum: {rec.sabado_acum:.2f}h"

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Horas Extra Recalculadas',
                    'message': message,
                    'type': 'success',
                    'sticky': False,
                }
            }

        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Error en Recálculo',
                    'message': f'Error: {str(e)}',
                    'type': 'danger',
                    'sticky': True,
                }
            }

    def debug_he_calculation(self):
        """Método de debug para verificar el cálculo paso a paso."""
        debug_info = []

        for rec in self:
            info = f"🔍 DEBUG: {rec.employee_id.name}\n"

            # Convertir a timezone del usuario para mostrar
            user_tz = pytz.timezone(self.env.user.tz or 'America/Tegucigalpa')

            # Convertir check_in y check_out a timezone local
            if rec.check_in.tzinfo:
                check_in_local = rec.check_in.astimezone(user_tz).replace(tzinfo=None)
            else:
                check_in_utc = pytz.UTC.localize(rec.check_in)
                check_in_local = check_in_utc.astimezone(user_tz).replace(tzinfo=None)

            if rec.check_out.tzinfo:
                check_out_local = rec.check_out.astimezone(user_tz).replace(tzinfo=None)
            else:
                check_out_utc = pytz.UTC.localize(rec.check_out)
                check_out_local = check_out_utc.astimezone(user_tz).replace(tzinfo=None)

            info += f"├── Check-in LOCAL: {check_in_local}\n"
            info += f"├── Check-out LOCAL: {check_out_local}\n"
            info += f"├── User TZ: {self.env.user.tz or 'America/Tegucigalpa'}\n"

            if not (rec.check_in and rec.check_out):
                info += "❌ FALTA check_in o check_out"
                debug_info.append(info)
                continue

            contract = rec.employee_id.contract_id
            if not contract:
                info += "❌ SIN CONTRATO ACTIVO"
                debug_info.append(info)
                continue

            calendar = contract.resource_calendar_id or rec.employee_id.resource_calendar_id
            if not calendar:
                info += "❌ SIN CALENDARIO"
                debug_info.append(info)
                continue

            info += f"├── Horas requeridas: {contract.full_time_required_hours}\n"
            info += f"├── Calendario: {calendar.name}\n"

            # Verificar campo nocturna
            nocturna = getattr(calendar, 'nocturna', False)
            info += f"├── Nocturna: {nocturna}\n"

            # Día de semana
            dow = str(check_in_local.weekday())
            lines = calendar.attendance_ids.filtered(lambda l: l.dayofweek == dow)

            full_req = contract.full_time_required_hours or 0

            if not lines:
                # Verificar si es caso especial de sábado 60h diurno
                if full_req == 60 and not nocturna and check_in_local.weekday() == 5:
                    info += f"├── ⚠️ SIN LÍNEAS PARA SÁBADO - Pero aplicando lógica especial\n"
                else:
                    info += f"❌ SIN LÍNEAS PARA DÍA {dow} (lunes=0)"
                    debug_info.append(info)
                    continue
            else:
                info += f"├── Líneas encontradas: {len(lines)}\n"
                for i, line in enumerate(lines):
                    info += f"├── Línea {i + 1}: {line.hour_from:.2f} - {line.hour_to:.2f}\n"

                # Mostrar cálculo detallado solo si hay líneas
                if lines:
                    day = check_in_local.date()
                    first_line = lines[0]
                    last_line = lines[-1]

                    # Usar función auxiliar para convertir horas de forma segura
                    sched_start = rec._safe_time_from_float(day, first_line.hour_from)
                    sched_end = rec._safe_time_from_float(day, last_line.hour_to)

                    info += f"├── Jornada COMPLETA: {sched_start.time()} - {sched_end.time()}\n"
                    info += f"├── Datos calendario: {first_line.hour_from:.2f} - {last_line.hour_to:.2f}\n"

                # Calcular duración real
                duration = (check_out_local - check_in_local).total_seconds() / 3600
                info += f"├── Duración real: {duration:.2f}h\n"

            # Mostrar ventanas de HE según el tipo
            if full_req == 60 and not nocturna:
                weekday = check_in_local.weekday()
                weekday_names = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes',
                                 'Sábado', 'Domingo']

                info += f"├── Día: {weekday_names[weekday]} (código: {weekday})\n"
                info += f"├── Modo: 60h DIURNO\n"

                if weekday == 5:  # Sábado
                    info += f"├── 🌟 SÁBADO DETECTADO - Todo es HE25\n"
                    duration = (check_out_local - check_in_local).total_seconds() / 3600
                    info += f"├── Duración total: {duration:.2f}h\n"
                    info += f"├── HE25 asignado: {duration:.2f}h (toda la jornada)\n"
                elif weekday == 4:  # Viernes
                    info += f"├── 🌟 VIERNES DETECTADO - Horario especial\n"
                    info += f"├── Ordinarias: 06:00-14:00 (8h normales)\n"
                    info += f"├── HE25: 14:00-18:00 (4h extra)\n"
                    info += f"├── Después 18:00: HE50 y HE75 normales\n"

                    day = check_in_local.date()
                    ordinary_end = datetime.combine(day, time(14, 0))
                    he25_end = datetime.combine(day, time(18, 0))

                    if check_out_local <= ordinary_end:
                        info += f"├── Solo tiempo ordinario (salió a las {check_out_local.time()})\n"
                    elif check_out_local <= he25_end:
                        he25_calc = (
                                                check_out_local - ordinary_end).total_seconds() / 3600
                        info += f"├── HE25 calculado: {he25_calc:.2f}h (desde 14:00 hasta {check_out_local.time()})\n"
                    else:
                        he25_calc = (
                                                he25_end - ordinary_end).total_seconds() / 3600  # 4h completas
                        info += f"├── HE25 calculado: {he25_calc:.2f}h (14:00-18:00 completo)\n"

                        if check_out_local > he25_end:
                            overtime_after_18 = (
                                                            check_out_local - he25_end).total_seconds() / 3600
                            info += f"├── Tiempo extra después 18:00: {overtime_after_18:.2f}h\n"
                else:
                    # Lógica normal para días de lunes a jueves
                    day = check_in_local.date()
                    eight_hours_from_checkin = check_in_local + timedelta(hours=8)
                    fixed_overtime_start = datetime.combine(day, time(15, 0))
                    overtime_start = max(eight_hours_from_checkin, fixed_overtime_start)

                    info += f"├── 8h desde check-in: {eight_hours_from_checkin.time()}\n"
                    info += f"├── Umbral fijo 15:00: {fixed_overtime_start.time()}\n"
                    info += f"├── HE empiezan desde: {overtime_start.time()}\n"

                    if check_out_local <= overtime_start:
                        info += f"├── Sin HE (salió a las {check_out_local.time()}, antes de {overtime_start.time()})\n"
                    else:
                        overtime_hours = (
                                                     check_out_local - overtime_start).total_seconds() / 3600
                        info += f"├── Tiempo en HE: {overtime_hours:.2f}h\n"

                        # Mostrar cálculo detallado de cada franja
                        w25_end = datetime.combine(day, time(19, 0))
                        if check_out_local <= w25_end:
                            he25_calc = (
                                                    check_out_local - overtime_start).total_seconds() / 3600
                            info += f"├── HE25 calculado: {he25_calc:.2f}h (desde {overtime_start.time()} hasta {check_out_local.time()})\n"
                        else:
                            he25_calc = (w25_end - overtime_start).total_seconds() / 3600
                            he50_calc = (check_out_local - w25_end).total_seconds() / 3600
                            info += f"├── HE25 calculado: {he25_calc:.2f}h (desde {overtime_start.time()} hasta 19:00)\n"
                            info += f"├── HE50 calculado: {he50_calc:.2f}h (desde 19:00 hasta {check_out_local.time()})\n"

                        info += f"├── Ventanas: HE25(hasta 19:00) | HE50(19:00-00:00) | HE75(00:00-05:00)\n"

            elif full_req == 44 and not nocturna:
                info += f"├── Modo: 44h DIURNO\n"
                info += f"├── Ordinarias: 07:30-15:30 (8h normales)\n"
                info += f"├── Sábado Acum: 15:30-16:30 (1h acumulada)\n"
                info += f"├── HE25: 16:30-19:00\n"
                info += f"├── HE50: 19:00-22:00\n"
                info += f"├── HE75: 22:00-06:00\n"

                # Mostrar cálculo detallado
                day = check_in_local.date()
                ordinary_end = datetime.combine(day, time(15, 30))
                saturday_acum_end = datetime.combine(day, time(16, 30))
                he25_end = datetime.combine(day, time(19, 0))
                he50_end = datetime.combine(day, time(22, 0))

                if check_out_local <= ordinary_end:
                    info += f"├── Solo tiempo ordinario (salió a las {check_out_local.time()})\n"
                elif check_out_local <= saturday_acum_end:
                    sabado_calc = (check_out_local - ordinary_end).total_seconds() / 3600
                    info += f"├── Sábado Acum: {sabado_calc:.2f}h (desde 15:30 hasta {check_out_local.time()})\n"
                elif check_out_local <= he25_end:
                    sabado_calc = (
                                              saturday_acum_end - ordinary_end).total_seconds() / 3600
                    he25_calc = (
                                            check_out_local - saturday_acum_end).total_seconds() / 3600
                    info += f"├── Sábado Acum: {sabado_calc:.2f}h (15:30-16:30)\n"
                    info += f"├── HE25: {he25_calc:.2f}h (desde 16:30 hasta {check_out_local.time()})\n"
                else:
                    # Cálculo completo con múltiples franjas
                    sabado_calc = 1.0  # Siempre 1h completa
                    he25_calc = (he25_end - saturday_acum_end).total_seconds() / 3600
                    info += f"├── Sábado Acum: {sabado_calc:.2f}h (15:30-16:30)\n"
                    info += f"├── HE25: {he25_calc:.2f}h (16:30-19:00)\n"

                    if check_out_local > he25_end:
                        he50_calc = (min(check_out_local,
                                         he50_end) - he25_end).total_seconds() / 3600
                        info += f"├── HE50: {he50_calc:.2f}h (desde 19:00)\n"

                    if check_out_local > he50_end:
                        he75_calc = (check_out_local - he50_end).total_seconds() / 3600
                        info += f"├── HE75: {he75_calc:.2f}h (desde 22:00)\n"

            elif full_req == 60 and nocturna:
                info += f"├── Modo: 60h NOCTURNO\n"
                info += f"├── Ordinarias: 18:00-01:00 (7h normales)\n"
                info += f"├── HE75: 01:00-06:00 (5h extra al 75%)\n"

                # Mostrar cálculo detallado
                day = check_in_local.date()
                ordinary_start = datetime.combine(day, time(18, 0))
                ordinary_end = datetime.combine(day + timedelta(days=1), time(1, 0))
                he75_start = ordinary_end
                he75_end = datetime.combine(day + timedelta(days=1), time(6, 0))

                if check_out_local <= he75_start:
                    info += f"├── Solo tiempo ordinario (salió a las {check_out_local.time()}, antes de 01:00)\n"
                else:
                    he75_calc = (min(check_out_local,
                                     he75_end) - he75_start).total_seconds() / 3600
                    info += f"├── HE75 calculado: {he75_calc:.2f}h (desde 01:00 hasta {min(check_out_local, he75_end).time()})\n"

            # Forzar recálculo y mostrar resultado
            rec._compute_he_franjas()
            info += f"└── RESULTADO: HE25={rec.he25:.2f} | HE50={rec.he50:.2f} | HE75={rec.he75:.2f} | Sábado Acum={rec.sabado_acum:.2f}"

            debug_info.append(info)

        # Mostrar en notificación
        full_message = "\n\n".join(debug_info)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Debug Horas Extra',
                'message': full_message,
                'type': 'info',
                'sticky': True,
            }
        }