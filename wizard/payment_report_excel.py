from odoo import api, fields, models
import base64
import io
import xlsxwriter

class WizardPayslipExcel(models.TransientModel):
    _name = 'wizard.payslip.excel'
    _description = 'Wizard para generar boletas de pago en Excel'

    file_data = fields.Binary('Archivo Excel')
    file_name = fields.Char('Nombre del archivo', default='Boletas_de_Pago.xlsx')

    payslip_run_id = fields.Many2one(
        'hr.payslip.run',
        string='Lote de Nómina',
        required=True
    )

    def action_generate_excel(self):
        """ Genera el archivo Excel con el formato deseado para cada empleado. """
        # 1. Crear un buffer para generar el Excel en memoria
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})

        # Formatos
        title_format = workbook.add_format({
            'bold': True,
            'font_size': 14,
            'align': 'center'
        })
        header_format = workbook.add_format({
            'bold': True,
            'align': 'center',
            'bg_color': '#D9D9D9'
        })
        normal_format = workbook.add_format({
            'align': 'left'
        })
        currency_format = workbook.add_format({
            'num_format': '#,##0.00',
            'align': 'right'
        })
        bold_format = workbook.add_format({
            'bold': True
        })

        # 2. Obtener la información del lote de nómina y las nóminas asociadas
        payslip_run = self.payslip_run_id
        date_start = payslip_run.date_start
        date_end = payslip_run.date_end

        # Buscar todas las nóminas asociadas al Lote
        payslips = self.env['hr.payslip'].search([
            ('payslip_run_id', '=', payslip_run.id)
        ])

        # 3. Crear la hoja principal en el Excel
        worksheet = workbook.add_worksheet("Boletas de Pago")
        # Ajuste de ancho para mayor legibilidad (puedes personalizar)
        worksheet.set_column('A:A', 30)
        worksheet.set_column('B:B', 15)
        worksheet.set_column('C:C', 15)
        worksheet.set_column('D:D', 5)
        worksheet.set_column('E:E', 30)
        worksheet.set_column('F:F', 15)
        worksheet.set_column('G:G', 15)

        # Variable para llevar el control de la fila en el Excel
        row = 0

        # Obtener el nombre de la empresa desde el lote (o desde otro modelo)
        company = payslip_run.company_id
        company_name = company.name or "Nombre de la Empresa"
        if company.vat:
            company_name = f"{company_name} - {company.vat}"

        # 4. Iterar sobre cada nómina (empleado) para generar su bloque de información
        for payslip in payslips:
            # ---------------------------------------------------------------
            # Encabezado para cada empleado
            # ---------------------------------------------------------------
            worksheet.merge_range(row, 0, row, 6, company_name, title_format)
            row += 1

            date_text = "Comprobante de Pago Salario del {} al {}".format(
                date_start.strftime('%d-%m-%Y') if date_start else '',
                date_end.strftime('%d-%m-%Y') if date_end else ''
            )
            worksheet.merge_range(row, 0, row, 6, date_text, normal_format)
            row += 1

            worksheet.merge_range(row, 0, row, 6, "Empleado: " + payslip.employee_id.name, bold_format)
            row += 1

            # ---------------------------------------------------------------
            # Información de días trabajados (una fila por cada línea)
            if payslip.worked_days_line_ids:
                for worked_day in payslip.worked_days_line_ids:
                    worksheet.merge_range(row, 0, row, 2, worked_day.name, normal_format)
                    worksheet.write(row, 3, worked_day.number_of_days, normal_format)
                    row += 1
            else:
                worksheet.merge_range(row, 0, row, 2, "Sin datos de días trabajados", normal_format)
                worksheet.write(row, 3, 0, normal_format)
                row += 1

            # ---------------------------------------------------------------
            # Títulos de columnas para INGRESOS y EGRESOS
            worksheet.merge_range(row, 0, row, 2, "INGRESOS", header_format)
            worksheet.write(row, 3, "")
            worksheet.merge_range(row, 4, row, 6, "EGRESOS", header_format)
            row += 1

            # ---------------------------------------------------------------
            # Detalle de las líneas (ingresos y deducciones) del empleado
            ingreso_lines = payslip.line_ids.filtered(lambda l: l.category_id.code in ('ALW', 'ING'))
            deduccion_lines = payslip.line_ids.filtered(lambda l: l.category_id.code == 'DED')
            max_lines = max(len(ingreso_lines), len(deduccion_lines))

            for i in range(max_lines):
                if i < len(ingreso_lines):
                    line_ingreso = ingreso_lines[i]
                    worksheet.write(row, 0, line_ingreso.name, normal_format)
                    worksheet.write_number(row, 1, line_ingreso.total, currency_format)
                else:
                    worksheet.write(row, 0, "", normal_format)
                    worksheet.write(row, 1, 0, currency_format)

                worksheet.write(row, 2, "", normal_format)

                if i < len(deduccion_lines):
                    line_deduccion = deduccion_lines[i]
                    worksheet.write(row, 4, line_deduccion.name, normal_format)
                    worksheet.write_number(row, 5, abs(line_deduccion.total), currency_format)
                else:
                    worksheet.write(row, 4, "", normal_format)
                    worksheet.write(row, 5, 0, currency_format)

                row += 1

            total_ingresos = sum(ingreso_lines.mapped('total'))
            total_egresos = sum(deduccion_lines.mapped('total'))
            neto = total_ingresos + total_egresos

            worksheet.write(row, 0, "Total Ingresos", bold_format)
            worksheet.write_number(row, 1, total_ingresos, currency_format)
            worksheet.write(row, 4, "Total Egresos", bold_format)
            worksheet.write_number(row, 5, abs(total_egresos), currency_format)
            row += 1

            worksheet.write(row, 0, "Total Neto", bold_format)
            worksheet.write_number(row, 1, neto, currency_format)
            worksheet.write(row, 4, "JEFE DE PRODUCCION", bold_format)
            row += 2

        workbook.close()
        file_data = output.getvalue()
        output.close()

        self.file_data = base64.b64encode(file_data)
        self.file_name = "Boletas_de_Pago_{}.xlsx".format(fields.Date.today().strftime('%Y%m%d'))

        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/?model={}&id={}&filename_field=file_name&field=file_data&download=true&filename={}'.format(
                self._name,
                self.id,
                self.file_name
            ),
            'target': 'self',
        }
