from odoo import models
from odoo.http import request


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    def session_info(self):
        """Tell the back office whether this visit came from a till.

        A cashier who opened the back office with their PIN has to be able to
        get back to the counter they came from, and the web client cannot know
        that on its own: to it, the session is simply that cashier's user.
        Only a yes/no reaches the browser -- never the till's kiosk token,
        which stays in the server-side session and is used by the Back to Till
        route itself.
        """
        info = super().session_info()
        info['pos_retail_from_till'] = bool(
            request and request.session.get('pos_retail_pin_till'))
        return info
