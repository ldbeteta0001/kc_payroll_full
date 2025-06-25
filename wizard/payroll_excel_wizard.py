# -*- coding: utf-8 -*-

from odoo import models, fields, api
import xlsxwriter
import base64
from io import BytesIO
import re


class PayrollExcelWizard(models.TransientModel):
    _name = 'payroll.excel.wizard'
    _description = 'Wizard para generar reporte de nómina en Excel'

    payslip_run_id = fields.Many2one(
        'hr.payslip.run',
        string='Lote de Nómina',
        required=True,
        help='Selecciona el lote de nómina para generar el reporte.'
    )
    excel_file = fields.Binary('Archivo Excel', readonly=True)
    excel_file_name = fields.Char('Nombre del Archivo', readonly=True,
                                  default='Planilla.xlsx')

    def action_generate_excel(self):
        """
        Método que genera el archivo Excel con los datos de la nómina
        según el formato solicitado, incluyendo encabezados agrupados para ingresos y deducciones.
        """
        # Preparar el buffer en memoria
        output = BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('Planilla')

        # Formatos de celda
        bold_format = workbook.add_format({'bold': True})
        center_format = workbook.add_format({'align': 'center'})
        bold_center_format = workbook.add_format({'bold': True, 'align': 'center'})
        currency_format = workbook.add_format({'num_format': 'L. #,##0.00'})

        # ------------------------------------------------------------
        # 1) ENCABEZADOS SUPERIORES
        # ------------------------------------------------------------
        row = 0

        # 1.1. Nombre de la compañía (desde A1 hasta Q1)
        worksheet.merge_range(row, 0, row, 16, self.env.company.name or '',
                              bold_center_format)

        # 1.2. RTN de la empresa (de G2 a L2)
        row += 1
        worksheet.merge_range(row, 6, row, 11, self.env.company.vat or '',
                              bold_center_format)

        # 1.3. Nombre del lote (de G3 a L3)
        row += 1
        worksheet.merge_range(row, 6, row, 11, self.payslip_run_id.name,
                              bold_center_format)

        # 1.4. Dejar dos filas vacías
        row += 2  # Ahora row es la fila donde empezarán los encabezados de detalle

        # ------------------------------------------------------------
        # 2) ENCABEZADOS DE DETALLES ESTÁTICOS
        # ------------------------------------------------------------
        # Esta fila contendrá los encabezados fijos (No., Nombre del empleado, etc.)
        static_header_row = row
        worksheet.write(static_header_row, 0, 'No.', bold_format)
        worksheet.write(static_header_row, 1, 'Nombre del empleado', bold_format)
        worksheet.write(static_header_row, 2, 'Nombre del puesto', bold_format)
        worksheet.write(static_header_row, 3, 'Sueldo Mensual', bold_format)
        worksheet.write(static_header_row, 4, 'Sueldo Ordinario', bold_format)
        worksheet.write(static_header_row, 5, 'Sueldo Diario', bold_format)

        # ------------------------------------------------------------
        # 3) ENCABEZADOS DE LAS REGLAS (AGRUPADO POR INGRESOS Y DEDUCCIONES)
        # ------------------------------------------------------------
        # Obtenemos todas las reglas utilizadas en el lote.
        all_rules = self.env['hr.salary.rule']
        for slip in self.payslip_run_id.slip_ids:
            for line in slip.line_ids:
                if line.salary_rule_id not in all_rules:
                    all_rules |= line.salary_rule_id

        # Ordenamos las reglas (puedes ajustar el criterio de ordenación).
        all_rules = all_rules.sorted(lambda r: r.id)

        # Separamos las reglas en dos grupos:
        income_rules = all_rules.filtered(lambda r: r.code and r.code.startswith('ING'))
        deduction_rules = all_rules.filtered(
            lambda r: not (r.code and r.code.startswith('ING')))

        # Creamos una lista con el orden deseado: ingresos primero y luego deducciones.
        ordered_rules = income_rules + deduction_rules

        # La posición inicial de las columnas de las reglas es la columna 6 (columna G).
        col_start_rules = 6

        # Fila para el encabezado de grupo (ingresos/deducciones)
        group_header_row = static_header_row + 1

        # Si existen ingresos, se fusionan las celdas correspondientes y se escribe "INGRESOS"
        income_count = len(income_rules)
        if income_count:
            col_income_start = col_start_rules
            col_income_end = col_income_start + income_count - 1
            worksheet.merge_range(group_header_row, col_income_start, group_header_row,
                                  col_income_end,
                                  "INGRESOS", bold_center_format)
        else:
            col_income_end = col_start_rules - 1

        # Para las deducciones, si existen, inician después de los ingresos
        deduction_count = len(deduction_rules)
        if deduction_count:
            col_deduction_start = col_income_end + 1
            worksheet.merge_range(group_header_row, col_deduction_start, group_header_row,
                                  col_deduction_start + deduction_count - 1,
                                  "DEDUCCIONES", bold_center_format)

        # Fila para escribir los nombres de cada regla
        rule_names_row = static_header_row + 2
        # Escribimos los encabezados para ingresos
        for idx, rule in enumerate(income_rules):
            worksheet.write(rule_names_row, col_start_rules + idx, rule.name, bold_format)
        # Escribimos los encabezados para deducciones
        for idx, rule in enumerate(deduction_rules):
            worksheet.write(rule_names_row, col_income_end + 1 + idx, rule.name,
                            bold_format)

        # La fila donde comienzan los datos es después de los encabezados estáticos y de las filas de reglas
        data_start_row = static_header_row + 3

        # ------------------------------------------------------------
        # 4) LLENAR LOS DATOS DE LOS EMPLEADOS
        # ------------------------------------------------------------
        current_row = data_start_row
        line_number = 1

        for slip in self.payslip_run_id.slip_ids:
            # Columna A: correlativo
            worksheet.write(current_row, 0, line_number, center_format)
            # Columna B: nombre del empleado
            worksheet.write(current_row, 1, slip.employee_id.name or '')
            # Columna C: nombre del puesto
            worksheet.write(current_row, 2, slip.contract_id.job_id.name or '')

            # Columna D: Sueldo Mensual formateado en moneda
            monthly_wage = slip.contract_id.wage or 0.0
            worksheet.write(current_row, 3, monthly_wage, currency_format)

            # Columna E: Sueldo Ordinario, obtenido de la regla con código 'ING001'
            base_rule = slip.line_ids.filtered(
                lambda ln: ln.salary_rule_id.code == 'ING001')
            base_salary = base_rule.total if base_rule else monthly_wage
            worksheet.write(current_row, 4, base_salary, currency_format)

            # Columna F: Sueldo Diario (mensual / 30)
            daily_wage = monthly_wage / 30.0 if monthly_wage else 0.0
            worksheet.write(current_row, 5, daily_wage, currency_format)

            # Escribir los montos para cada regla en el orden de ordered_rules
            for idx, rule in enumerate(ordered_rules):
                line_rule = slip.line_ids.filtered(
                    lambda ln: ln.salary_rule_id.id == rule.id)
                amount = line_rule.total if line_rule else 0.0
                worksheet.write(current_row, col_start_rules + idx, amount,
                                currency_format)

            current_row += 1
            line_number += 1

        # ------------------------------------------------------------
        # 5) COLUMNAS PARA FIRMAS
        # ------------------------------------------------------------
        firma_row = current_row + 1
        # Se posiciona, por ejemplo, en la columna de inicio de reglas
        firma_col = col_start_rules
        worksheet.write(firma_row, firma_col, 'Revisada por:', bold_format)
        worksheet.write(firma_row, firma_col + 2, 'Autorizada por:', bold_format)

        # Cerrar el workbook y obtener los bytes
        workbook.close()
        file_data = output.getvalue()
        output.close()

        # Función para sanitizar el nombre del archivo
        def sanitize_filename(name):
            return re.sub(r'[\\/*?:"<>|]', '_', name)

        self.excel_file = base64.b64encode(file_data)
        self.excel_file_name = "{}.xlsx".format(
            sanitize_filename(self.payslip_run_id.name))

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'payroll.excel.wizard',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }
