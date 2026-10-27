"""Server-owned defaults and collection-to-module permissions.

Roles are editable by administrators, but the browser cannot grant itself access.
"""
from copy import deepcopy

ACTIONS = ('view', 'create', 'edit', 'delete', 'approve', 'export')
COLLECTIONS = {
    'vendors': 'vendors', 'products': 'products', 'requests': 'requests',
    'rfqs': 'rfqs', 'quotations': 'quotations', 'comparisons': 'comparison',
    'orders': 'orders', 'receipts': 'receipts', 'invoices': 'invoices',
    'payments': 'payments', 'companies': 'companies', 'customers': 'sales_customers',
    'leads': 'leads', 'crmQuotes': 'crmQuotes', 'reminders': 'reminders',
    'salesQuotations': 'sales_quotations', 'salesOrders': 'sales_orders',
    'deliveries': 'sales_deliveries', 'customerInvoices': 'sales_invoices',
    'customerPayments': 'sales_payments',
}
HR_COLLECTIONS = {
    'employees': 'hr_employees', 'manpower': 'hr_manpower',
    'candidates': 'hr_recruitment', 'attendance': 'hr_attendance',
    'leaves': 'hr_leave', 'payroll': 'hr_payroll', 'separations': 'hr_separation',
}
MODULES = sorted(set(COLLECTIONS.values()) | set(HR_COLLECTIONS.values()) | {
    'dashboard', 'sales', 'reports', 'activities', 'users', 'settings',
    'hr_dashboard', 'hr_reports',
    'accounting', 'inventory', 'manufacturing', 'expenses',
})


def default_roles():
    roles = {}
    def add(name, modules, readonly=False, approve=False):
        permissions = {}
        for module in MODULES:
            enabled = module in modules
            permissions[module] = {
                action: enabled and (action in ('view', 'export') or
                    (not readonly and action in ('create', 'edit')) or
                    (not readonly and approve and action == 'approve'))
                for action in ACTIONS
            }
        roles[name] = {m: permissions[m]['view'] for m in MODULES}
        roles[name]['permissions'] = permissions
    purchase = ['dashboard', 'requests', 'rfqs', 'quotations', 'comparison',
                'orders', 'receipts', 'vendors', 'products', 'reports', 'activities']
    sales = ['dashboard', 'sales', 'leads', 'reminders', 'sales_customers',
             'sales_quotations', 'sales_orders', 'sales_deliveries', 'products', 'activities']
    add('Admin', MODULES, approve=True)
    for module in MODULES:
        roles['Admin']['permissions'][module]['delete'] = True
    add('Procurement Manager', purchase, approve=True)
    add('Procurement Staff', purchase, approve=True)
    roles['Procurement Staff']['permissions']['orders']['approve'] = False
    add('Requester', ['dashboard', 'requests', 'products', 'activities'])
    roles['Requester']['permissions']['requests']['edit'] = False
    add('Finance', ['dashboard', 'orders', 'receipts', 'invoices', 'payments',
                    'sales', 'sales_orders', 'sales_customers', 'sales_invoices',
                    'sales_payments', 'products', 'reports', 'activities'], approve=True)
    for module in ('orders', 'receipts', 'sales_orders'):
        roles['Finance']['permissions'][module]['approve'] = False
    add('Sales Manager', sales + ['sales_invoices', 'sales_payments', 'reports'], approve=True)
    add('Salesperson', sales)
    roles['Sales Representative'] = deepcopy(roles['Salesperson'])
    roles['CRM Manager'] = deepcopy(roles['Sales Manager'])
    roles['Quote Manager'] = deepcopy(roles['Sales Manager'])
    add('Viewer', list(COLLECTIONS.values()) + ['dashboard', 'sales', 'reports', 'activities'], readonly=True)
    add('HR Manager', list(HR_COLLECTIONS.values()) + ['dashboard', 'hr_dashboard', 'hr_reports'], approve=True)
    for name in roles:
        for module in ('accounting', 'inventory', 'manufacturing', 'expenses'):
            view = name == 'Admin' or (module == 'accounting' and name == 'Finance') or (module == 'inventory' and name in ('Procurement Manager','Procurement Staff','Sales Manager','Finance','Viewer')) or module == 'expenses'
            write = view and name != 'Viewer'
            approve = name == 'Admin' or (module in ('accounting','expenses') and name == 'Finance') or (module == 'inventory' and name == 'Procurement Manager')
            roles[name][module] = view
            roles[name]['permissions'][module] = dict(view=view, create=write, edit=write, delete=False, approve=approve, export=view)
    # Dedicated shop-floor role; production users do not receive finance access.
    add('Manufacturing Manager', ['dashboard','inventory','manufacturing','products','expenses','activities'])
    for module in ('inventory','manufacturing'):
        roles['Manufacturing Manager'][module] = True
        roles['Manufacturing Manager']['permissions'][module] = dict(view=True,create=True,edit=True,delete=False,approve=True,export=True)
    return roles


def allowed(user, state, module, action='view'):
    if user.role == 'Admin':
        return True
    role = state.get('roles', {}).get(user.role, {})
    return role.get('permissions', {}).get(module, {}).get(action) is True


def in_scope(user, record, key, state):
    from .scope import actor_visible, creator_of_record
    return actor_visible(creator_of_record(record), user)
