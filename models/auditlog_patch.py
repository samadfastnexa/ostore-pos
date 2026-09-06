from odoo import models


class Base(models.AbstractModel):
    """Make the OCA audit trail survive a write that is still in flight.

    Creating a user from an employee crashed the whole save with "Could not
    find all values of resource.resource(7,) to flush them", and no user was
    created.

    Why: hr.employee delegates to resource.resource, so linking the new user to
    the employee writes through to that employee's resource row. auditlog then
    takes its post-create snapshot inside a ThrowAwayCache, which empties the
    transaction's field DATA but cannot empty field_dirty -- that is a
    cached_property on Environment, already resolved for envs that touched the
    record. So the snapshot reads a field, the read queries another model, the
    query forces a flush of the real dirty set against an emptied cache, and
    the flush finds nothing to write.

    Settling those writes first, while the cache is still whole, leaves the
    snapshot nothing to trip over.

    An earlier version of this fix dropped every one2many from the snapshot
    instead. It stopped the crash but quietly cost real audit rows: adding a
    bank account to a vendor, or a payment method to the Bank journal, produced
    NO log entry at all afterwards, because auditlog only writes a log when at
    least one line survives and neither child model carries a rule of its own.
    On a shop that pays vendors by bank transfer those are the most valuable
    rows the audit rules produce. The flush keeps every field.

    Patched onto the class rather than declared with _inherit = 'auditlog.rule'
    so pos_retail does NOT depend on auditlog. That module is AGPL-3 while this
    one is LGPL-3, it lives outside this repository, and it is absent from the
    addons_path the deployment guide builds -- a hard dependency would make
    pos_retail refuse to install on the very server it is deployed to. Here the
    patch binds where auditlog is present and does nothing where it is not.
    """
    _inherit = 'base'

    def _register_hook(self):
        res = super()._register_hook()
        Rule = self.env.registry.get('auditlog.rule')
        if Rule is None or Rule.__dict__.get('_pos_retail_flush_patched'):
            return res

        origin = Rule.get_auditlog_fields

        def get_auditlog_fields(self, model):
            # Called at auditlog_rule.py:376, just BEFORE the snapshot enters
            # ThrowAwayCache -- the last moment the cache is still intact.
            model.env.flush_all()
            return origin(self, model)

        Rule.get_auditlog_fields = get_auditlog_fields
        Rule._pos_retail_flush_patched = True
        return res
