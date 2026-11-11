"""Versioned migration and compatibility facade over domain tables."""

from copy import deepcopy
from . import master_store as masters, trade_store as trade, crm_register_store as crm
from .app import db


def project(stored):
    return crm.project(trade.project(masters.project(stored)))


def persist(data, include_trade=True):
    data = crm.persist(data)
    master_data = masters.persist(data)
    if not include_trade:
        return master_data
    trade.persist(data)
    return {
        **{
            k: v
            for k, v in data.items()
            if k not in masters.MODELS and k not in trade.MODELS
        },
        masters.MARKER: 1,
        trade.MARKER: 1,
    }


def migrate(doc):
    if all(doc.stored_data.get(m) for m in (masters.MARKER, trade.MARKER, crm.MARKER)):
        return False
    original = deepcopy(doc.data)
    stored = persist(original)
    db.session.flush()
    for module in (masters, trade, crm):
        for key in module.MODELS:
            if module.read(key) != original.get(key, []):
                raise ValueError(
                    "Migration stopped: "
                    + key
                    + " could not round-trip exactly. No business data was changed."
                )
    doc.stored_data = stored
    doc.revision += 1
    return True
