"""Versioned migration and compatibility facade over domain tables."""

from copy import deepcopy
from . import master_store as masters, trade_store as trade
from .app import db


def project(stored):
    return trade.project(masters.project(stored))


def persist(data, include_trade=True):
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
    if doc.stored_data.get(masters.MARKER) and doc.stored_data.get(trade.MARKER):
        return False
    original = deepcopy(doc.data)
    stored = persist(original)
    db.session.flush()
    for module in (masters, trade):
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
