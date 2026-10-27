"""Department permissions, private CRM/HR records and company-wide Finance access.

Creator metadata is retained for audit, not used as a universal visibility rule.
"""
from copy import deepcopy
from flask import g


def actor_visible(creator, user=None):
    from .app import db, User
    user = user or g.user
    if user.role == 'Admin':
        return True
    if not creator:
        return False
    if str(creator) == str(user.id):
        return True
    owner = db.session.get(User, str(creator))
    return owner is not None and str(owner.manager_id or '') == str(user.id)


def creator_of_record(record):
    return record.get('createdBy') or record.get('ownerId')


def team_visible(creator,user=None):
    from .app import db,User
    user=user or g.user
    if actor_visible(creator,user):return True
    owner=db.session.get(User,str(creator)) if creator else None
    return owner is not None and bool(user.manager_id) and (
        str(owner.id)==str(user.manager_id) or str(owner.manager_id or '')==str(user.manager_id))


def finance_access(user,state):
    from .permissions import allowed
    return allowed(user,state,'accounting')


def hr_access(user,state):
    from .permissions import allowed
    return user.role=='Admin' or allowed(user,state,'hr_employees','edit')


def employee_is_self(user,record,key,state):
    from .app import db,Document,User
    doc=db.session.get(Document,'hr')
    employees=(doc.data if doc else {}).get('employees',[])
    actors={str(user.id)}|{str(uid) for uid in db.session.scalars(db.select(User.id).where(User.manager_id==user.id))}
    if key=='employees':return str(record.get('linkedUserId','')) in actors
    for employee in employees:
        if str(employee.get('linkedUserId','')) not in actors:continue
        label=str(employee.get('employeeId',''))+' - '+str(employee.get('name',''))
        if str(record.get('employeeKey',''))==str(employee['id']) or record.get('employee')==label:return True
    return False


def business_visible(user,record,key,state):
    from .permissions import allowed,HR_COLLECTIONS
    if user.role=='Admin':return True
    creator=creator_of_record(record)
    if key in HR_COLLECTIONS:
        if hr_access(user,state):return True
        if key in ('manpower','candidates'):return actor_visible(creator,user)
        return employee_is_self(user,record,key,state)
    if key in ('leads','crmQuotes'):
        return actor_visible(creator,user) or actor_visible(record.get('ownerId'),user)
    if key=='reminders':
        lead=next((l for l in state.get('leads',[]) if str(l['id'])==str(record.get('leadId'))),None)
        return actor_visible(creator,user) or (lead is not None and business_visible(user,lead,'leads',state))
    if key=='requests':
        return allowed(user,state,'rfqs') or finance_access(user,state) or team_visible(creator,user)
    if key in ('salesQuotations','salesOrders','deliveries','customerInvoices','customerPayments'):
        if finance_access(user,state):return True
        if team_visible(creator,user) or team_visible(record.get('ownerId'),user):return True
        # A workflow assignment carries access through its quotation/order chain.
        if key=='salesQuotations':
            lead=next((r for r in state.get('leads',[]) if str(r['id'])==str(record.get('leadId'))),None)
            return lead is not None and business_visible(user,lead,'leads',state)
        parent_key='salesQuotations' if key=='salesOrders' else 'salesOrders'
        parent_field='quotationId' if key=='salesOrders' else 'orderId'
        parent=next((r for r in state.get(parent_key,[]) if str(r['id'])==str(record.get(parent_field))),None)
        return parent is not None and business_visible(user,parent,parent_key,state)
    # Shared company masters and purchasing records; module/action checks remain mandatory.
    return True


def attachment_visible(attachment,user=None):
    from .app import db,Document
    from .permissions import allowed
    user=user or g.user;state=db.session.get(Document,'app').data
    if user.role=='Admin':return True
    if not allowed(user,state,attachment.module):return False
    if attachment.module=='expenses':return finance_access(user,state) or actor_visible(attachment.uploader_id,user)
    if attachment.module=='requests':return allowed(user,state,'rfqs') or finance_access(user,state) or team_visible(attachment.uploader_id,user)
    return attachment.module in ('quotations','orders')


def registry():
    from .app import db, Document
    doc = db.session.get(Document, 'record_scopes')
    return doc.data if doc else {}


def remember(value, creator=None):
    from .app import db, Document
    identity = str(getattr(value, 'id', None) or getattr(value, 'code', ''))
    key = value.__tablename__ + ':' + identity
    doc = db.session.get(Document, 'record_scopes')
    if doc is None:
        doc = Document(name='record_scopes', data={}, revision=1)
        db.session.add(doc)
    data = deepcopy(doc.data)
    data.setdefault(key, str(creator or g.user.id))
    doc.data = data
    return value


def object_creator(value):
    from .app import db, Document
    table = value.__tablename__
    if table == 'journal_line':
        return object_creator(value.entry)
    if table == 'stock_move':
        creator=registry().get(table+':'+str(value.id))
        if creator:return creator
        from .erp import JournalEntry
        entry = db.session.get(JournalEntry, value.journal_id)
        return object_creator(entry) if entry else None
    if table == 'expense':
        return value.owner_id
    if table == 'attachment':
        return value.uploader_id
    if table == 'erp_product':
        state = db.session.get(Document, 'app').data
        record = next((r for r in state.get('products', []) if str(r['id']) == str(value.id)), {})
        return creator_of_record(record)
    if table == 'journal_entry':
        return registry().get(table + ':' + str(value.id)) or value.created_by
    return registry().get(table + ':' + str(getattr(value, 'id', None) or getattr(value, 'code', '')))


def object_visible(value):
    from .app import db,Document
    from .permissions import allowed
    user=g.user;state=db.session.get(Document,'app').data
    if user.role=='Admin':return True
    table=value.__tablename__
    if table in ('journal_entry','journal_line','bank_statement_line','account'):
        return finance_access(user,state)
    if table=='expense':return finance_access(user,state) or actor_visible(value.owner_id,user)
    if table=='attachment':return attachment_visible(value,user)
    if table=='erp_product':return any(allowed(user,state,m) for m in ('products','inventory','manufacturing'))
    if table=='stock_move':return allowed(user,state,'inventory')
    if table in ('bill_of_materials','manufacturing_order'):return allowed(user,state,'manufacturing')
    return actor_visible(object_creator(value),user)


def require_object(value):
    from .app import problem
    if not object_visible(value):
        problem('Record access is not permitted for your department or assignment', 403)
    return value


def source_creator(source):
    """Retain source-creator attribution when another authorized department posts."""
    from .app import db, Document
    from .erp import ManufacturingOrder, Expense, StockMove, JournalEntry
    if getattr(g,'scope_creator',None):return g.scope_creator
    parts = source.split(':')
    if parts[0] == 'stock':
        return source_creator(':'.join(parts[1:]))
    if len(parts) > 1:
        collection, identity = parts[:2]
        models = {'mo': ManufacturingOrder, 'expense': Expense, 'return': None, 'reversal': JournalEntry}
        if collection in models and models[collection] is not None and identity.isdigit():
            obj = db.session.get(models[collection], int(identity))
            if obj:
                return object_creator(obj)
        namespace = 'hr' if collection == 'payroll' else 'app'
        doc = db.session.get(Document, namespace)
        row = next((r for r in (doc.data.get(collection, []) if doc else []) if str(r.get('id')) == identity), None)
        if row:
            return creator_of_record(row)
    return getattr(g, 'scope_creator', None) or g.user.id
