"""ERP workspace API. Each mutation is atomic and protected by server permissions."""
from copy import deepcopy
from datetime import date
from decimal import Decimal
from functools import wraps
import re

from flask import Blueprint, g, jsonify, request
from sqlalchemy import select, func

from .app import db, Document, Attachment, body, problem, audit
from .permissions import allowed
from .scope import object_visible, require_object, remember, object_creator
from .validation import InvalidBusinessState
from .erp import (Account, JournalEntry, JournalLine, Reconciliation, ERPProduct, StockBalance, StockMove,
                  BillOfMaterials, BOMLine, ManufacturingOrder, ProductionComponent, Expense, BankStatementLine,
                  ERPControl, COMPANY, CHART, CENT, UNIT, dec, day, lock, next_number, post_entry, journal_pair,
                  stock_move, sync_products, matched_amount, reconcile, auto_reconcile, check_period)

bp = Blueprint('erp', __name__, url_prefix='/api/erp')


def access(module, action='view'):
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            state = db.session.get(Document, 'app').data
            if not allowed(g.user, state, module, action):
                problem('Permission denied: ' + module + '.' + action, 403)
            if request.method not in ('GET', 'HEAD'):
                lock()
            return fn(*args, **kwargs)
        return wrapped
    return decorate


def key(data):
    value = str(data.get('requestKey', ''))
    if not re.fullmatch(r'[A-Za-z0-9_-]{8,100}', value):
        raise InvalidBusinessState('A unique requestKey of 8–100 letters/numbers is required')
    return value


def done(value):
    db.session.commit()
    return jsonify(value)


def text(value, label, maximum=160):
    value = str(value or '').strip()
    if not value or len(value) > maximum:
        raise InvalidBusinessState(f'{label} is required (maximum {maximum} characters)')
    return value


def row(model, identity):
    value = db.session.get(model, identity)
    if not value:
        problem('Record not found', 404)
    if model in (JournalEntry,JournalLine,StockMove,BillOfMaterials,ManufacturingOrder,Expense,BankStatementLine,ERPProduct,Attachment):
        require_object(value)
    if model is Account and value.code not in {a[0] for a in CHART}:
        require_object(value)
    return value


def entry_json(entry):
    require_object(entry)
    return dict(id=entry.id, number=entry.number, source=entry.source, memo=entry.memo, date=entry.date,
                status=entry.status, reversalOf=entry.reversal_of,
                lines=[dict(id=l.id, account=l.account, debit=str(l.debit), credit=str(l.credit), partner=l.partner,
                            dueDate=l.due_date, openAmount=str(abs(l.debit-l.credit)-matched_amount(l))) for l in entry.lines])


def move_json(move):
    require_object(move)
    product = db.session.get(ERPProduct, move.product_id)
    return dict(id=move.id, number=move.number, productId=move.product_id, product=product.name,
                quantity=str(move.quantity), value=str(move.value), kind=move.kind, date=move.date,
                journalId=move.journal_id, returnOf=move.return_of)


def expense_json(expense):
    require_object(expense)
    return dict(id=expense.id, number=expense.number, employee=expense.employee, ownerId=expense.owner_id,
                description=expense.description, account=expense.account, amount=str(expense.amount),
                tax=str(expense.tax), total=str(expense.amount+expense.tax), date=expense.date,
                status=expense.status, attachmentId=expense.attachment_id)


def bom_json(bom):
    require_object(bom)
    return dict(id=bom.id, name=bom.name, productId=bom.product_id,
                product=row(ERPProduct,bom.product_id).name, quantity=str(bom.output_quantity),
                conversionCost=str(bom.conversion_cost),
                components=[dict(productId=l.product_id, product=row(ERPProduct,l.product_id).name, quantity=str(l.quantity)) for l in bom.lines])


def mo_json(order):
    require_object(order)
    return dict(id=order.id, number=order.number, bomId=order.bom_id, product=row(ERPProduct,order.product_id).name,
                productId=order.product_id, quantity=str(order.quantity), conversionCost=str(order.conversion_cost),
                actualCost=str(order.actual_cost), state=order.state, date=order.date,
                components=[dict(productId=l.product_id, product=row(ERPProduct,l.product_id).name,
                                 quantity=str(l.quantity)) for l in order.lines])


@bp.get('/overview')
def overview():
    state = db.session.get(Document, 'app').data
    if not any(allowed(g.user,state,module) for module in ('accounting','inventory','manufacturing','expenses')):
        problem('ERP workspace access required',403)
    result = dict(company=state.get('company', COMPANY), warehouse='WH / Stock', currency='PKR',
                  canSeed=g.user.role=='Admin', permissions={m:{a:allowed(g.user,state,m,a) for a in ('view','create','edit','approve')} for m in ('accounting','inventory','manufacturing','expenses')})
    if allowed(g.user,state,'inventory'):
        result['inventoryValue'] = str(sum((m.value for m in db.session.scalars(select(StockMove)) if object_visible(m)),Decimal(0)))
        result['stockProducts'] = sum(1 for p in db.session.scalars(select(ERPProduct).where(ERPProduct.kind=='stock')) if object_visible(p))
    if allowed(g.user,state,'manufacturing'):
        result['openProduction'] = sum(1 for o in db.session.scalars(select(ManufacturingOrder).where(ManufacturingOrder.state.in_(['Draft','Confirmed','In Progress']))) if object_visible(o))
    if allowed(g.user,state,'expenses'):
        query=db.session.query(Expense).filter(Expense.status.in_(['Submitted','Approved']))
        result['pendingExpenses']=sum(1 for e in query if object_visible(e))
    if allowed(g.user,state,'accounting'):
        report=financial_report()
        result.update(cashBank=report['cashBank'],receivables=report['receivables'],payables=report['payables'],profit=report['profit'])
    return jsonify(result)


@bp.get('/accounts')
@access('accounting')
def accounts():
    return jsonify(accounts=[dict(code=a.code,name=a.name,type=a.kind,reconcile=a.reconcile) for a in db.session.scalars(select(Account).order_by(Account.code)) if a.code in {c[0] for c in CHART} or object_visible(a)])


@bp.post('/accounts')
@access('accounting','create')
def create_account():
    data=body(); code=str(data.get('code',''))
    if not re.fullmatch(r'[0-9]{4,8}',code) or data.get('type') not in ('asset','liability','equity','income','expense'):
        raise InvalidBusinessState('Use a 4–8 digit code and a valid account type')
    if not isinstance(data.get('reconcile',False),bool):
        raise InvalidBusinessState('Reconciliation must be true or false')
    account=Account(code=code,name=text(data.get('name'),'Account name'),kind=data['type'],reconcile=bool(data.get('reconcile',False)))
    db.session.add(account);db.session.flush();remember(account)
    audit('Created account',{'code':code})
    return done(dict(ok=True))


@bp.get('/entries')
@access('accounting')
def entries():
    query = select(JournalEntry).order_by(JournalEntry.id.desc())
    source = request.args.get('source')
    if source:
        query = query.where((JournalEntry.source == source) | JournalEntry.source.startswith(source + ':', autoescape=True) |
                            JournalEntry.source.startswith('stock:' + source + ':', autoescape=True))
    return jsonify(entries=[entry_json(e) for e in db.session.scalars(query) if object_visible(e)][:500])


@bp.post('/entries')
@access('accounting','create')
def create_entry():
    data=body(); request_key=key(data)
    if not isinstance(data.get('lines'),list) or len(data['lines'])>100:
        raise InvalidBusinessState('Provide up to 100 journal lines')
    for line in data['lines']:row(Account,str(line.get('account')))
    entry=post_entry('manual:'+request_key,text(data.get('memo'),'Memo',500),data['lines'],data.get('date'),draft=True)
    return done(entry_json(entry))


@bp.post('/entries/<int:identity>/post')
@access('accounting','approve')
def post_manual_entry(identity):
    entry=row(JournalEntry,identity)
    if entry.status=='Draft':
        check_period(entry.date); entry.status='Posted'; audit('Posted manual journal',{'number':entry.number})
    return done(entry_json(entry))


@bp.post('/entries/<int:identity>/reverse')
@access('accounting','approve')
def reverse_manual_entry(identity):
    entry=row(JournalEntry,identity)
    if entry.status!='Posted' or not entry.source.startswith(('manual:','transfer:')):
        raise InvalidBusinessState('Only posted manual journals/transfers can be reversed here; use the source document return flow for stock')
    g.scope_creator=object_creator(entry)
    reversal=post_entry('reversal:'+str(entry.id),'Reversal of '+entry.number,
                       [dict(account=l.account,debit=l.credit,credit=l.debit,partner=l.partner) for l in entry.lines],body().get('date'))
    reversal.reversal_of=entry.id
    return done(entry_json(reversal))


@bp.post('/transfers')
@access('accounting','create')
def transfer():
    data=body(); source,target=str(data.get('fromAccount')),str(data.get('toAccount'))
    if source not in ('1000','1010') or target not in ('1000','1010') or source==target:
        raise InvalidBusinessState('Choose different cash and bank accounts')
    entry=journal_pair('transfer:'+key(data),'Internal bank/cash transfer',target,source,dec(data.get('amount'),positive=True),data.get('date'))
    return done(entry_json(entry))


@bp.post('/reconcile')
@access('accounting','approve')
def reconcile_lines():
    data=body(); debit=row(JournalLine,data.get('debitLine')); credit=row(JournalLine,data.get('creditLine'))
    reconcile(debit,credit,data.get('amount'));audit('Matched journal items',{'debit':debit.id,'credit':credit.id})
    return done(dict(ok=True))


def financial_report():
    start=day(request.args['from']) if request.args.get('from') else None
    end=day(request.args['to']) if request.args.get('to') else day()
    if start and start>end: raise InvalidBusinessState('Start date must precede end date')
    query=select(JournalLine,JournalEntry).join(JournalEntry).where(JournalEntry.status=='Posted',JournalEntry.date<=end)
    lines=db.session.execute(query).all()
    totals={a.code:dict(code=a.code,name=a.name,type=a.kind,debit=Decimal(0),credit=Decimal(0),periodDebit=Decimal(0),periodCredit=Decimal(0)) for a in db.session.scalars(select(Account).order_by(Account.code)) if a.code in {c[0] for c in CHART} or object_visible(a)}
    ledger=[]; cash_in=Decimal(0);cash_out=Decimal(0);opening_cash=Decimal(0)
    for line,entry in lines:
        if not object_visible(entry):continue
        account=totals[line.account];account['debit']+=line.debit;account['credit']+=line.credit
        inside=not start or entry.date>=start
        if inside:
            account['periodDebit']+=line.debit;account['periodCredit']+=line.credit
            ledger.append(dict(id=line.id,date=entry.date,entry=entry.number,memo=entry.memo,account=line.account,partner=line.partner,
                               debit=str(line.debit),credit=str(line.credit),openAmount=str(abs(line.debit-line.credit)-matched_amount(line))))
        if line.account in ('1000','1010'):
            if inside: cash_in+=line.debit;cash_out+=line.credit
            else: opening_cash+=line.debit-line.credit
    assets=liabilities=equity=earnings=profit=Decimal(0)
    for item in totals.values():
        balance=item['debit']-item['credit'];period=item['periodDebit']-item['periodCredit']
        if item['type']=='asset':assets+=balance
        if item['type']=='liability':liabilities-=balance
        if item['type']=='equity':equity-=balance
        if item['type'] in ('income','expense'): earnings-=balance;profit-=period
        item['balance']=balance
    def amount(code):return totals[code]['balance']
    result=dict(fromDate=start,toDate=end,currency='PKR',accounts=[{k:str(v) if isinstance(v,Decimal) else v for k,v in a.items()} for a in totals.values()],
                ledger=ledger,assets=str(assets),liabilities=str(liabilities),equity=str(equity),currentEarnings=str(earnings),
                balanceCheck=str(assets-liabilities-equity-earnings),profit=str(profit),cashBank=str(amount('1000')+amount('1010')),
                receivables=str(amount('1100')),payables=str(-amount('2100')),cashIn=str(cash_in),cashOut=str(cash_out),openingCash=str(opening_cash),
                closingCash=str(opening_cash+cash_in-cash_out))
    return result


@bp.get('/reports')
@access('accounting')
def reports():
    return jsonify(financial_report())


@bp.get('/aged')
@access('accounting')
def aged():
    as_of=day(request.args.get('date')); result=[]
    lines=db.session.execute(select(JournalLine,JournalEntry).join(JournalEntry).where(JournalEntry.status=='Posted',JournalEntry.date<=as_of,JournalLine.account.in_(['1100','2100']))).all()
    # Reconciliation is current-state only. The UI labels this report accordingly.
    for line,entry in lines:
        if not object_visible(entry):continue
        remaining=abs(line.debit-line.credit)-matched_amount(line)
        if remaining<=0:continue
        overdue=(date.fromisoformat(as_of)-date.fromisoformat(line.due_date or entry.date)).days
        bucket='Not due' if overdue<=0 else '1–30' if overdue<=30 else '31–60' if overdue<=60 else '61–90' if overdue<=90 else '90+'
        result.append(dict(id=line.id,account=line.account,partner=line.partner,entry=entry.number,dueDate=line.due_date or entry.date,
                           debit=str(line.debit),credit=str(line.credit),openAmount=str(remaining),bucket=bucket))
    return jsonify(items=result,asOf=as_of,settlements='Current reconciliation state')


@bp.route('/period-lock',methods=['GET','POST'])
@access('accounting','approve')
def period_lock():
    control=row(ERPControl,1)
    if request.method=='POST':
        if g.user.role!='Admin':problem('Administrator access required to change period locks',403)
        value=body().get('date');control.lock_date=day(value) if value else None
        audit('Changed period lock',{'through':control.lock_date});return done(dict(date=control.lock_date))
    return jsonify(date=control.lock_date)


@bp.get('/inventory')
@access('inventory')
def inventory():
    products=[]
    for product in db.session.scalars(select(ERPProduct).order_by(ERPProduct.name)):
        if not object_visible(product):continue
        balance=row(StockBalance,product.id)
        scoped_moves=[m for m in db.session.scalars(select(StockMove).where(StockMove.product_id==product.id)) if object_visible(m)]
        quantity=sum((m.quantity for m in scoped_moves),Decimal(0));value=sum((m.value for m in scoped_moves),Decimal(0))
        products.append(dict(id=product.id,name=product.name,sku=product.sku,type=product.kind,unit=product.unit,
                             quantity=str(quantity),value=str(value),averageCost=str(dec(value/quantity)) if quantity else '0.00'))
    return jsonify(warehouse='WH / Stock',products=products,moves=[move_json(m) for m in db.session.scalars(select(StockMove).order_by(StockMove.id.desc())) if object_visible(m)][:500])


@bp.post('/inventory/adjust')
@access('inventory','approve')
def adjust_stock():
    data=body();product=row(ERPProduct,str(data.get('productId')));quantity=dec(data.get('quantity'),UNIT)
    cost=dec(data.get('unitCost',0),UNIT)
    if cost<0:raise InvalidBusinessState('Cost cannot be negative')
    move=stock_move(product.id,quantity,'adjust:'+key(data),text(data.get('reason'),'Adjustment reason',300),'5105',cost,data.get('date'))
    return done(move_json(move))


@bp.post('/inventory/return')
@access('inventory','approve')
def return_stock():
    data=body();original=row(StockMove,data.get('moveId'));quantity=dec(data.get('quantity'),UNIT,positive=True)
    if original.kind not in ('Purchase Receipt','Sales Delivery'):
        raise InvalidBusinessState('Returns must reference a purchase receipt or sales delivery')
    g.scope_creator=object_creator(original)
    source='return:'+key(data)
    existing=db.session.scalar(select(StockMove).where(StockMove.source==source))
    if existing:return done(move_json(existing))
    returned=db.session.scalar(select(func.coalesce(func.sum(func.abs(StockMove.quantity)),0)).where(StockMove.return_of==original.id))
    if quantity+returned>abs(original.quantity):raise InvalidBusinessState('Return exceeds the unreturned original quantity')
    # Customer returns recover original delivery cost. Vendor returns issue at current average cost.
    sign=1 if original.quantity<0 else -1
    cost=abs(original.value/original.quantity)
    move=stock_move(original.product_id,sign*quantity,source,'Customer Return' if sign>0 else 'Vendor Return',original.counterpart,cost,data.get('date'),return_of=original.id)
    return done(move_json(move))


@bp.get('/boms')
@access('manufacturing')
def boms():
    return jsonify(boms=[bom_json(b) for b in db.session.scalars(select(BillOfMaterials).order_by(BillOfMaterials.id.desc())) if object_visible(b)])


@bp.post('/boms')
@access('manufacturing','create')
def create_bom():
    data=body();request_key=key(data);existing=db.session.scalar(select(BillOfMaterials).where(BillOfMaterials.request_key==request_key))
    if existing:return done(bom_json(existing))
    product=row(ERPProduct,str(data.get('productId')))
    if product.kind!='stock':raise InvalidBusinessState('A manufacturing output must be a stock product')
    components=data.get('components')
    if not isinstance(components,list) or not 1<=len(components)<=100:raise InvalidBusinessState('Add 1–100 components')
    seen=set();lines=[]
    for item in components:
        component=row(ERPProduct,str(item.get('productId')))
        if component.kind!='stock' or component.id==product.id or component.id in seen:raise InvalidBusinessState('Use distinct stock components different from the output')
        seen.add(component.id);lines.append(BOMLine(product_id=component.id,quantity=dec(item.get('quantity'),UNIT,positive=True)))
    conversion=dec(data.get('conversionCost',0))
    if conversion<0:raise InvalidBusinessState('Conversion cost cannot be negative')
    bom=BillOfMaterials(name=text(data.get('name'),'BoM name'),product_id=product.id,output_quantity=dec(data.get('quantity'),UNIT,positive=True),
                        conversion_cost=conversion,request_key=request_key,lines=lines)
    db.session.add(bom);db.session.flush();remember(bom);audit('Created bill of materials',{'id':bom.id});return done(bom_json(bom))


@bp.get('/manufacturing')
@access('manufacturing')
def manufacturing():
    return jsonify(orders=[mo_json(o) for o in db.session.scalars(select(ManufacturingOrder).order_by(ManufacturingOrder.id.desc())) if object_visible(o)])


@bp.post('/manufacturing')
@access('manufacturing','create')
def create_mo():
    data=body();request_key=key(data);existing=db.session.scalar(select(ManufacturingOrder).where(ManufacturingOrder.request_key==request_key))
    if existing:return done(mo_json(existing))
    bom=row(BillOfMaterials,data.get('bomId'));quantity=dec(data.get('quantity'),UNIT,positive=True);factor=quantity/bom.output_quantity
    order=ManufacturingOrder(number=next_number('MO'),bom_id=bom.id,product_id=bom.product_id,quantity=quantity,
                             conversion_cost=dec(bom.conversion_cost*factor),actual_cost=0,state='Draft',date=day(data.get('date')),request_key=request_key,
                             lines=[ProductionComponent(product_id=l.product_id,quantity=dec(l.quantity*factor,UNIT,positive=True)) for l in bom.lines])
    db.session.add(order);db.session.flush();remember(order);audit('Created manufacturing order',{'number':order.number});return done(mo_json(order))


@bp.post('/manufacturing/<int:identity>/<action>')
@access('manufacturing','approve')
def advance_mo(identity,action):
    order=row(ManufacturingOrder,identity)
    if action=='complete' and order.state=='Done':return done(mo_json(order))
    transitions={'confirm':('Draft','Confirmed'),'start':('Confirmed','In Progress'),'cancel':('Draft','Cancelled')}
    if action in transitions:
        before,after=transitions[action]
        if order.state!=before:raise InvalidBusinessState('Invalid production transition')
        order.state=after
    elif action=='complete':
        if order.state not in ('Confirmed','In Progress'):raise InvalidBusinessState('Confirm the manufacturing order first')
        g.scope_creator=object_creator(order)
        check_period(order.date);total=Decimal(0)
        for index,line in enumerate(order.lines):
            move=stock_move(line.product_id,-line.quantity,f'mo:{order.id}:component:{index}','Manufacturing Consumption','1250',value_date=order.date)
            total-=move.value
        if order.conversion_cost:
            journal_pair(f'mo:{order.id}:conversion','Accrued production conversion cost','1250','2400',order.conversion_cost,order.date)
        total+=order.conversion_cost
        stock_move(order.product_id,order.quantity,f'mo:{order.id}:output','Manufacturing Output','1250',value_date=order.date,total_value=total)
        order.actual_cost=total;order.state='Done'
    else:problem('Unknown production action',404)
    audit('Updated manufacturing order',{'number':order.number,'state':order.state});return done(mo_json(order))


@bp.get('/expenses')
@access('expenses')
def expenses():
    query=select(Expense).order_by(Expense.id.desc())
    return jsonify(expenses=[expense_json(e) for e in db.session.scalars(query) if object_visible(e)])


@bp.post('/expenses')
@access('expenses','create')
def create_expense():
    data=body();request_key=key(data);existing=db.session.scalar(select(Expense).where(Expense.request_key==request_key))
    if existing:
        if existing.owner_id!=g.user.id:problem('Expense belongs to another user',403)
        return done(expense_json(existing))
    account=row(Account,str(data.get('account','6105')))
    if account.kind!='expense':raise InvalidBusinessState('Select an expense account')
    amount=dec(data.get('amount'),positive=True);tax=dec(data.get('tax',0))
    if tax<0 or tax>amount:raise InvalidBusinessState('Tax must be between zero and the expense amount')
    attachment=data.get('attachmentId') or None
    if attachment:
        file=row(Attachment,attachment)
        if file.uploader_id!=g.user.id or file.module!='expenses':problem('Select your uploaded expense receipt',403)
    employee = data.get('employee',g.user.name) if allowed(g.user,db.session.get(Document,'app').data,'expenses','approve') else g.user.name
    expense=Expense(number=next_number('EXP'),employee=text(employee,'Employee'),owner_id=g.user.id,
                    description=text(data.get('description'),'Description',500),account=account.code,amount=amount,tax=tax,
                    date=day(data.get('date')),status='Draft',attachment_id=attachment,request_key=request_key)
    db.session.add(expense);db.session.flush();audit('Created expense',{'number':expense.number});return done(expense_json(expense))


@bp.post('/expenses/<int:identity>/<action>')
@access('expenses','edit')
def advance_expense(identity,action):
    expense=row(Expense,identity);g.scope_creator=expense.owner_id;state=db.session.get(Document,'app').data
    approver=allowed(g.user,state,'expenses','approve')
    if action in ('approve','pay','reject') and not approver:problem('Expense approval permission required',403)
    if not approver and expense.owner_id!=g.user.id:problem('Expense belongs to another user',403)
    if (action=='approve' and expense.status in ('Approved','Paid')) or (action=='pay' and expense.status=='Paid'):return done(expense_json(expense))
    if action=='submit' and expense.status=='Draft':expense.status='Submitted'
    elif action=='reject' and expense.status=='Submitted':expense.status='Rejected'
    elif action=='approve' and expense.status=='Submitted':
        post_entry(f'expense:{expense.id}',expense.number,[dict(account=expense.account,debit=expense.amount),dict(account='1300',debit=expense.tax),
                   dict(account='2350',credit=expense.amount+expense.tax,partner='employee:'+expense.employee)],expense.date);expense.status='Approved'
    elif action=='pay' and expense.status=='Approved':
        data=body();cash=str(data.get('account','1010'))
        if cash not in ('1000','1010'):raise InvalidBusinessState('Choose cash or bank')
        entry=journal_pair(f'expense:{expense.id}:payment','Reimbursement '+expense.number,'2350',cash,expense.amount+expense.tax,data.get('date'),partner='employee:'+expense.employee)
        auto_reconcile(f'expense:{expense.id}',entry,'2350');expense.status='Paid'
    else:raise InvalidBusinessState('Invalid expense transition')
    audit('Updated expense',{'number':expense.number,'status':expense.status});return done(expense_json(expense))


@bp.route('/bank-statements',methods=['GET','POST'])
@access('accounting','edit')
def bank_statements():
    if request.method=='POST':
        data=body();request_key=key(data);existing=db.session.scalar(select(BankStatementLine).where(BankStatementLine.request_key==request_key))
        if existing:require_object(existing);return done(dict(id=existing.id))
        account=str(data.get('account','1010'))
        if account not in ('1000','1010'):raise InvalidBusinessState('Choose cash or bank')
        amount=dec(data.get('amount'))
        if not amount:raise InvalidBusinessState('Statement amount cannot be zero')
        line=BankStatementLine(date=day(data.get('date')),description=text(data.get('description'),'Description',300),account=account,amount=amount,request_key=request_key)
        db.session.add(line);db.session.flush();remember(line);audit('Recorded bank statement line',{'id':line.id});return done(dict(id=line.id))
    items=[dict(id=l.id,date=l.date,description=l.description,account=l.account,amount=str(l.amount),matchedLine=l.matched_line) for l in db.session.scalars(select(BankStatementLine).order_by(BankStatementLine.id.desc())) if object_visible(l)]
    used={l['matchedLine'] for l in items if l['matchedLine']}
    ledger=[dict(id=l.id,date=e.date,entry=e.number,memo=e.memo,account=l.account,amount=str(l.debit-l.credit)) for l,e in db.session.execute(select(JournalLine,JournalEntry).join(JournalEntry).where(JournalEntry.status=='Posted',JournalLine.account.in_(['1000','1010']))) if l.id not in used and object_visible(e)]
    return jsonify(statements=items,ledger=ledger)


@bp.post('/bank-statements/<int:identity>/match')
@access('accounting','approve')
def match_bank(identity):
    statement=row(BankStatementLine,identity);line=row(JournalLine,body().get('lineId'))
    if statement.matched_line:
        if statement.matched_line==line.id:return done(dict(ok=True))
        raise InvalidBusinessState('Statement line is already matched')
    if line.entry.status!='Posted' or line.account!=statement.account or line.debit-line.credit!=statement.amount:
        raise InvalidBusinessState('Match a posted line with the same account and signed amount')
    if db.session.scalar(select(BankStatementLine.id).where(BankStatementLine.matched_line==line.id)):
        raise InvalidBusinessState('Journal item is already matched to a statement')
    statement.matched_line=line.id;audit('Reconciled bank statement',{'statementId':statement.id,'journalLineId':line.id});return done(dict(ok=True))


@bp.post('/company-profile')
def company_profile():
    if g.user.role!='Admin':problem('Administrator access required',403)
    lock();data=body();doc=row(Document,'app');company=deepcopy(doc.data.get('company',COMPANY))
    for field in ('name','legalName','address','phone','email','taxNumber'):
        if field in data:company[field]=str(data[field]).strip()[:500]
    company.update(country='Pakistan',currency='PKR',currencySymbol='Rs',currencyLocale='en-PK')
    saved=deepcopy(doc.data);saved['company']=company;doc.data=saved;doc.revision+=1
    audit('Updated company profile');return done(dict(company=company))


@bp.post('/seed-demo')
def seed_demo():
    if g.user.role!='Admin':problem('Administrator access required',403)
    lock()
    if db.session.scalar(select(JournalEntry.id).limit(1)) or db.session.scalar(select(StockMove.id).limit(1)):
        raise InvalidBusinessState('Demo opening data can only be loaded into an empty ledger')
    doc=row(Document,'app');state=deepcopy(doc.data)
    if state.get('products') or any(state.get(k) for k in ('orders','receipts','invoices','customerInvoices','payments','customerPayments')):
        raise InvalidBusinessState('Load demo data before creating or importing products and transactions')
    state['products']=[dict(id=9001,name='General Panel',sku='RAW-001',unit='Each',rate=750,productType='stock'),
                       dict(id=9002,name='Fastener Pack',sku='RAW-002',unit='Pack',rate=100,productType='stock'),
                       dict(id=9003,name='General Assembly Kit',sku='FG-001',unit='Each',rate=2500,productType='stock'),
                       dict(id=9004,name='Installation Service',sku='SVC-001',unit='Service',rate=1000,productType='service')]
    state['vendors']=[dict(id=9005,name='Pakistan Supplies',status='Active',email='vendor@example.test')]
    state['customers']=[dict(id=9006,code='CUS-001',name='Pakistan Demo Customer',status='Active',paymentTerms='30 Days')]
    for collection in ('products','vendors','customers'):
        for record in state[collection]:record['createdBy']=g.user.id
    state['company']={**COMPANY,**state.get('company',{}),'country':'Pakistan','currency':'PKR'}
    doc.data=state;doc.revision+=1;sync_products(state)
    journal_pair('demo:bank','Demo opening bank balance','1010','3000',250000)
    journal_pair('demo:cash','Demo opening cash balance','1000','3000',25000)
    stock_move('9001',100,'demo:panel','Opening Stock','3000',500)
    stock_move('9002',200,'demo:fasteners','Opening Stock','3000',50)
    bom=BillOfMaterials(name='General Assembly Kit — Standard BoM',product_id='9003',output_quantity=1,conversion_cost=100,request_key='demo-standard-bom',
                        lines=[BOMLine(product_id='9001',quantity=2),BOMLine(product_id='9002',quantity=4)])
    db.session.add(bom);db.session.flush();remember(bom);audit('Loaded Pakistan demo opening data');return done(dict(ok=True))


def init_erp(app):
    app.register_blueprint(bp)
