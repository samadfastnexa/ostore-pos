from odoo import http
from odoo.exceptions import AccessDenied
from odoo.http import request

from .kiosk_logout import KIOSK_BLOCK_COOKIE


class PosRetailKiosk(http.Controller):
    """One bookmark, no username or password, straight to a till's PIN screen.

    Built because the till login (a username and a password) and the cashier
    PIN are two different security layers answering two different questions --
    "which device is this?" and "who is standing at it?" -- and a shop
    running at a fast counter has no patience for the first one to keep
    coming back. Session cookies already make the till login a once-off in
    steady state; this exists for everything a cookie does not survive --
    a new device, a cleared browser, a server update -- so the answer to
    "why do I sometimes see a login page at all" is "you should not have to,
    tap this instead," not "type the password again."

    Deliberately auth='public': the whole point is a visitor with no session
    reaching this and getting one. What that session can then DO is bounded
    the same way it always was -- pos.config.pos_retail_kiosk_user_id is
    ordinarily the branch's own shared till account, already scoped to one
    company, Point of Sale User only, no Settings. Anyone holding the link
    can act as that account, exactly as anyone standing at the physical till
    already can; the link is the new physical-access boundary, not a
    reduction of one that existed before.
    """

    @http.route('/pos_retail/kiosk/<string:token>', type='http', auth='public', methods=['GET'])
    def open(self, token, **kwargs):
        Config = request.env['pos.config'].sudo()
        config = Config.search([('pos_retail_kiosk_token', '=', token)], limit=1)
        user = config.pos_retail_kiosk_user_id if config else None

        if not config or not user:
            return request.render('pos_retail.kiosk_link_invalid', {})

        # Somebody deliberately signed out on this browser. Without this the
        # link undoes that instantly -- press Back and you are in again, no
        # password -- which is what the shop reported twice and is fair: a
        # link that signs you in is a password, and logging out cannot
        # un-bookmark a password. Signing in once with a password clears the
        # marker (see kiosk_logout.py) and the bookmark works again.
        if (config.pos_retail_kiosk_relock_on_logout
                and request.httprequest.cookies.get(KIOSK_BLOCK_COOKIE)):
            return request.render('pos_retail.kiosk_link_signed_out', {})

        try:
            credential = {'type': 'pos_retail_kiosk', 'login': user.login, 'token': token}
            request.session.authenticate(request.env, credential)
        except AccessDenied:
            return request.render('pos_retail.kiosk_link_invalid', {})

        return request.redirect(f'/pos/ui/{config.id}')
