from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    @api.constrains('pin')
    def _verify_pin(self):
        """Say whose PIN is wrong, where it is, and what to type instead.

        Core raises "The PIN must be a sequence of digits." on a form with five
        tabs, and stops there. It never says which person failed when saving
        more than one, never says where the box is, and "a sequence of digits"
        is not how anyone running a hardware shop describes a number. The
        person is left hunting for a field they cannot see, on a screen that
        will not save.

        The directions here are the ones actually on screen: the tab reads
        Settings (hr_employee_views.xml:357 names it hr_settings but shows
        "Settings"), and the field is labelled PIN Code inside the
        Attendance/Point of Sale group.
        """
        for employee in self:
            pin = employee.pin
            if not pin or pin.isdigit():
                continue
            offending = sorted({c for c in pin if not c.isdigit()})
            raise ValidationError(_(
                "%(name)s's PIN can only be numbers, and this one contains "
                "%(bad)s.\n\n"
                "Type digits only, for example 1234. The box is called PIN "
                "Code, on the Settings tab of this form, under "
                "Attendance/Point of Sale.\n\n"
                "It is what this person taps at the till to take the register "
                "over from whoever was on it, so keep it short and easy for "
                "them to remember.",
                name=employee.name or _("This employee"),
                bad=", ".join("a space" if c == " " else '"%s"' % c for c in offending),
            ))

    pos_discount_role_id = fields.Many2one(
        'pos.retail.discount.role',
        string="POS Discount Role",
        default=lambda self: self.env.ref(
            'pos_retail.discount_role_cashier', raise_if_not_found=False
        ),
        help="Controls how much order-level discount this employee can apply "
             "in the POS without manager approval.",
    )

    @api.model
    def _load_pos_data_fields(self, config):
        result = super()._load_pos_data_fields(config)
        if 'pos_discount_role_id' not in result:
            result.append('pos_discount_role_id')
        return result

    # Permissions that reach into the till, keyed by the flag the browser sees.
    # Each value is the xmlid of the res.groups a permission in the Roles &
    # Permissions catalogue carries.
    POS_RETAIL_TILL_PERMISSIONS = {
        '_can_khata': 'pos_retail.perm_khata_adjust_res_groups',
    }

    @api.model
    def _load_pos_data_read(self, records, config):
        """Tell the till what each cashier is allowed to do beyond selling.

        Sent as extra KEYS on the payload rather than as fields, deliberately.
        Adding a real field to the POS employee payload is what broke every
        cashier login once before: hr.employee._check_private_fields treats a
        field absent from hr.employee.public as private, and POS serves
        employees through that model to anyone without HR rights. The failure
        surfaced as an unrelated JavaScript error about currency_id. Core
        already sends _role, _barcode and _pin this way for the same reason.

        The permission is read from the EMPLOYEE's own user, not from whoever
        the browser is signed in as. On a kiosk till the browser is the till
        account, so asking it what it may do would give every cashier the same
        answer -- and the wrong one.
        """
        rows = super()._load_pos_data_read(records, config)
        by_id = {employee.id: employee for employee in records}
        for row in rows:
            employee = by_id.get(row['id'])
            user = employee.sudo().user_id if employee else None
            for flag, group_xmlid in self.POS_RETAIL_TILL_PERMISSIONS.items():
                row[flag] = bool(user) and user.has_group(group_xmlid)
        return rows


class HrEmployeePublic(models.Model):
    """Expose the discount role on the public employee profile.

    Without this, no cashier could open the till at all.

    POS serves employees to anyone without HR rights through
    hr.employee.public, and hr.employee._check_private_fields
    (hr/models/hr_employee.py:1150) calls a field private simply because it is
    absent from that model. Adding pos_discount_role_id to the POS payload above
    therefore made every employee read raise AccessError for a cashier.

    The failure was almost impossible to read. pos_session.load_data catches
    AccessError per model and quietly substitutes an empty list, so pos.config
    arrived empty; pos_loyalty then did data['pos.config'][0] and the browser
    showed "Cannot read properties of undefined (reading 'currency_id')" --
    naming neither the field, the model, nor the access check that started it.

    Declared the same way core declares job_title and phone here: related to
    employee_id, not stored, so the SQL view behind this model is untouched.
    """
    _inherit = 'hr.employee.public'

    pos_discount_role_id = fields.Many2one(
        'pos.retail.discount.role', string="POS Discount Role",
        related='employee_id.pos_discount_role_id', readonly=True)
