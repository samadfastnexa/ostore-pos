from odoo import models
from odoo.exceptions import AccessError
from odoo.tools.translate import _


class ResUsers(models.Model):
    _inherit = 'res.users'

    def _change_password(self, new_passwd):
        if not self.env.user._is_system():
            raise AccessError(_("Only the Super Admin can set or reset a password. Please contact them."))
        super()._change_password(new_passwd)
