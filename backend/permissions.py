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
    return roles


def allowed(user, state, module, action='view'):
    if user.role == 'Admin':
        return True
    role = state.get('roles', {}).get(user.role, {})
    return role.get('permissions', {}).get(module, {}).get(action) is True


def in_scope(user, record, key, state):
    """Enforce sales-team ownership for reads and writes, not just list screens."""
    if user.role not in ('Sales Manager', 'Salesperson', 'Sales Representative'):
        return True
    if key == 'customers':
        if str(record.get('ownerId')) == str(user.id) or (user.role == 'Sales Manager' and str(record.get('managerId')) == str(user.id)):
            return True
        return any(str(lead.get('customerId')) == str(record.get('id')) and
                   in_scope(user, lead, 'leads', state) for lead in state.get('leads', []))
    if key == 'reminders':
        lead = next((r for r in state.get('leads', []) if str(r.get('id')) == str(record.get('leadId'))), None)
        return lead is not None and in_scope(user, lead, 'leads', state)
    if key in ('salesOrders', 'deliveries', 'customerInvoices', 'customerPayments'):
        if key == 'salesOrders':
            quote_id = record.get('quotationId')
        else:
            order = next((r for r in state.get('salesOrders', []) if
                          str(r.get('id')) == str(record.get('orderId')) or
                          (record.get('orderNo') and r.get('orderNo') == record.get('orderNo'))), None)
            if not order:
                return False
            quote_id = order.get('quotationId')
        quote = next((r for r in state.get('salesQuotations', []) if str(r.get('id')) == str(quote_id)), None)
        return quote is not None and in_scope(user, quote, 'salesQuotations', state)
    if key in ('leads', 'salesQuotations'):
        owner = record.get('ownerId') or record.get('createdBy')
        manager = record.get('managerId')
        return str(manager if user.role == 'Sales Manager' else owner) == str(user.id)
    return True
