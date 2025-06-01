# -*- coding: utf-8 -*-
{
    'name': "KC PAYROLL FULL",

    'summary': "Desarrollos de Nomina.",

    'description': """
        Desarrollos de Nomina
    """,

    'author': "Luis Daniel Beteta",
    'website': "https://kenocia.com/",

    # Categories can be used to filter modules in modules listing
    # Check https://github.com/odoo/odoo/blob/15.0/odoo/addons/base/data/ir_module_category_data.xml
    # for the full list
    'category': 'Uncategorized',
    'version': '17.1',

    # any module necessary for this one to work correctly
    'depends': ['base', 'hr', 'hr_payroll', 'hr_attendance'],

    # always loaded
    'data': [
        'security/ir.model.access.csv',
        'wizard/hr_payslip_import_input.xml',
        'wizard/payrroll_excel_wizard.xml',
        'wizard/payment_report_excel.xml',
        'wizard/hr_attendance_import_views.xml',
        'wizard/change_schedule_wizard_views.xml',
        'views/resource_calendar.xml',
        'views/hr_contract_views.xml',
        'views/hr_attenadnce_views.xml',
    ],
    'installable': True,
    'application': True,
}
