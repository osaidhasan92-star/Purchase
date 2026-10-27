"""Record-level customer API during the frontend migration.

The existing aggregate remains the compatibility store. Writes are serialized and
versioned; other registers are never supplied or overwritten by the caller.
"""
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import re
import secrets
import time
from flask import Blueprint, g, jsonify, request
from .app import (db, app_document, body, problem, digest, audit, utcnow,
                  commit_document, merge_collection)
from .permissions import COLLECTIONS, HR_COLLECTIONS, allowed, in_scope
from .erp import lock, dec

bp=Blueprint('customer_records',__name__,url_prefix='/api')
FIELDS=('name','contact','phone','email','category','paymentTerms','creditLimit','status','address')


def permit(action):
    if not allowed(g.user,app_document().data,'sales_customers',action):
        problem('Customers '+action+' permission required',403)


def version(record):
    return digest(json.dumps(record,sort_keys=True,separators=(',',':')))


def output(record):
    result={key:str(record.get(key) or '') for key in FIELDS if key!='creditLimit'}
    result.update(paymentTerms=result['paymentTerms'] or 'Cash',status=result['status'] or 'Active',
                  creditLimit=record.get('creditLimit') or 0,id=record['id'],code=str(record.get('code') or ''),
                  createdBy=record.get('createdBy'),version=version(record))
    return result


def values(data,previous=None):
    if set(data)-set(FIELDS)-{'version','requestKey'}:problem('Unknown customer fields')
    if previous:data={**{key:previous[key] for key in FIELDS if key in previous},**data}
    result={}
    limits={'name':160,'contact':160,'phone':80,'email':254,'category':100,'address':1000}
    for key,limit in limits.items():
        value=data.get(key,'')
        if not isinstance(value,str) or len(value.strip())>limit:problem('Invalid customer '+key)
        result[key]=value.strip()
    if not result['name']:problem('Customer name is required')
    if result['email'] and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',result['email']):problem('Enter a valid email address')
    result['paymentTerms']=data.get('paymentTerms','Cash')
    result['status']=data.get('status','Active')
    if result['paymentTerms'] not in ('Cash','15 Days','30 Days','45 Days'):problem('Invalid payment terms')
    if result['status'] not in ('Active','Inactive'):problem('Invalid customer status')
    credit=data.get('creditLimit',0)
    if isinstance(credit,bool) or not isinstance(credit,(int,float)) or not math.isfinite(credit) or not 0<=credit<=1e12:
        problem('Credit limit must be a finite non-negative number')
    result['creditLimit']=float(dec(credit))
    return result


@bp.get('/ui/bootstrap')
def bootstrap():
    state=app_document().data
    # No business collections or employee/payroll data on the modern screen.
    compact={key:[] for key in COLLECTIONS}
    compact.update(company=deepcopy(state.get('company',{})),roles=deepcopy(state['roles']),
                   users=[g.user.public()],activities=[])
    return jsonify(user=g.user.public(),csrfToken=g.login_session.csrf,state=compact,
                   hr={key:[] for key in HR_COLLECTIONS})


@bp.get('/customers')
def customers():
    permit('view')
    try:page=int(request.args.get('page','1'));size=int(request.args.get('pageSize','25'))
    except ValueError:problem('Page and pageSize must be integers')
    if page<1 or not 1<=size<=100:problem('Page must be positive; pageSize must be 1–100')
    search=request.args.get('search','').strip().casefold()
    if len(search)>160:problem('Search is too long')
    records=app_document().data.get('customers',[])
    filtered=[r for r in records if not search or any(search in str(r.get(k,'')).casefold() for k in ('name','code','phone','email','contact'))]
    filtered.sort(key=lambda r:(str(r.get('name','')).casefold(),str(r['id'])))
    start=(page-1)*size
    return jsonify(items=[output(r) for r in filtered[start:start+size]],total=len(filtered),page=page,pageSize=size)


@bp.get('/customers/<identity>')
def customer_details(identity):
    permit('view');state=app_document().data
    record=next((r for r in state.get('customers',[]) if str(r['id'])==identity),None)
    if record is None:problem('Customer not found',404)
    orders=[r for r in state.get('salesOrders',[]) if str(r.get('customerId'))==identity and
            allowed(g.user,state,'sales_orders') and in_scope(g.user,r,'salesOrders',state)]
    orders.sort(key=lambda r:(str(r.get('orderDate','')),str(r['id'])),reverse=True)
    return jsonify(customer=output(record),orderTotal=len(orders),orders=[{key:r.get(key) for key in ('id','orderNo','orderDate','total','status')} for r in orders[:25]])


@bp.route('/customers',methods=['POST'])
@bp.route('/customers/<identity>',methods=['PATCH'])
def save_customer(identity=None):
    permit('create' if identity is None else 'edit')
    data=body()
    lock();doc=app_document();db.session.refresh(doc)
    saved=deepcopy(doc.data);rows=saved.get('customers',[])
    old=next((r for r in rows if str(r['id'])==str(identity)),None) if identity is not None else None
    if identity is not None:
        if old is None:problem('Customer not found',404)
        if not data.get('version'):problem('Customer version is required',428)
        if data['version']!=version(old):problem('This customer changed. Reload before saving.',409)
        normalized=values(data,old)
        changed={**old,**normalized}
        rows=[changed if str(r['id'])==str(identity) else r for r in rows]
    else:
        normalized=values(data)
        request_key=data.get('requestKey','')
        if not isinstance(request_key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,100}',request_key):problem('A unique requestKey is required')
        existing=next((r for r in rows if r.get('creationRequestKey')==request_key and r.get('createdBy')==g.user.id),None)
        if existing:
            if any(existing.get(key)!=value for key,value in normalized.items()):problem('This request key was already used with different customer details',409)
            return jsonify(customer=output(existing))
        suffix=max((int(str(r.get('code','')).split('-')[-1]) for r in rows if str(r.get('code','')).split('-')[-1].isdigit()),default=0)+1
        used={str(r['id']) for r in rows}
        identity=int(time.time()*1000)*1000+secrets.randbelow(1000)
        while str(identity) in used:identity+=1
        changed={**normalized,'id':identity,'code':f'CUS-{datetime.now(timezone.utc).year}-{suffix:03d}',
                 'createdAt':utcnow(),'creationRequestKey':request_key}
        rows=rows+[changed]
    saved['customers']=merge_collection('customers',rows,doc.data.get('customers',[]),doc.data,'sales_customers')
    g.changed_keys={'customers'}
    audit('Updated customer' if old else 'Created customer',{'customerId':identity})
    revision=commit_document(doc,doc.revision,saved)
    result=next(r for r in saved['customers'] if str(r['id'])==str(identity))
    return jsonify(customer=output(result),revision=revision)
