"""Creator/direct-manager/Admin access, shared by every business module.

Ownership metadata uses the existing Document store, avoiding schema changes.
Unattributed historic records are restricted to Admin; they are never made public.
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
    return actor_visible(object_creator(value))


def require_object(value):
    from .app import problem
    if not object_visible(value):
        problem('Record is outside your creator/team scope', 403)
    return value


def source_creator(source):
    """Generated ledgers belong to the source creator, even when a manager posts."""
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
