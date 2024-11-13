
import base64
import pandas as pd
from odoo import models, fields, api
from odoo.exceptions import ValidationError

class HrPayslipImportInput(models.TransientModel):
    _name = 'hr.payslip.import.input'
    _description = 'Wizard para importar otras entradas de nómina'

    file = fields.Binary("Suba su archivo", required=True)
    filename = fields.Char("Nombre del archivo")
    calcular_hoja = fields.Boolean("Calcular Hoja")
    batch_id = fields.Many2one('hr.payslip.run', string="Lote de Planilla", required=True)

    def import_file(self):
        # Decodifica el archivo y lo lee en un DataFrame de Pandas
        try:
            file_data = base64.b64decode(self.file)
            df = pd.read_excel(file_data)
        except Exception as e:
            raise ValidationError("Error al leer el archivo: %s" % str(e))

        # Validación de columnas
        required_columns = ['default_code', 'code', 'amount']
        if not all(column in df.columns for column in required_columns):
            raise ValidationError(
                "El archivo debe contener las columnas: 'default_code', 'code', y 'amount'.")

        for _, row in df.iterrows():
            # Obtener el empleado usando 'default_code'
            employee = self.env['hr.employee'].search(
                [('registration_number', '=', row['default_code'])], limit=1)
            if not employee:
                raise ValidationError(
                    f"Empleado con código {row['default_code']} no encontrado.")

            # Obtener la regla salarial usando 'code'
            rule = self.env['hr.payslip.input.type'].search([('code', '=', row['code'])],
                                                     limit=1)
            if not rule:
                raise ValidationError(
                    f"Regla salarial con código {row['code']} no encontrada.")

            # Obtener la nómina del empleado en el lote seleccionado
            payslip = self.env['hr.payslip'].search([
                ('employee_id', '=', employee.id),
                ('payslip_run_id', '=', self.batch_id.id),
                ('state', '=', 'verify')
            ], limit=1)

            if not payslip:
                raise ValidationError(
                    f"No se encontró una nómina en borrador para el empleado {employee.name} en el lote seleccionado.")

            # Crear la entrada de nómina en la nómina del empleado
            self.env['hr.payslip.input'].create({
                'payslip_id': payslip.id,
                'input_type_id': rule.id,
                'name': rule.name,
                'amount': row['amount'],
            })
            # Calcular la hoja si está marcada la opción calcular_hoja
            if self.calcular_hoja:
                payslip.compute_sheet()

        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }