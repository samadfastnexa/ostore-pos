from odoo import http
from odoo.http import request

from odoo.addons.web.controllers.home import Home
from odoo.addons.web.controllers.session import Session

# Name and lifetime of the marker that says "somebody deliberately signed out
# on this browser". A year, because the point is that it outlives the browser
# being closed -- a marker that expired with the session would be no marker
# at all.
KIOSK_BLOCK_COOKIE = 'pos_retail_kiosk_signed_out'
KIOSK_BLOCK_MAX_AGE = 60 * 60 * 24 * 365


class PosRetailSession(Session):
    """Make signing out mean something on a device holding a kiosk link.

    Reported twice from the shop: "after I logged out I logged in again
    without a password."

    Odoo's logout was never at fault -- measured, and after it a protected
    page does redirect to the login screen. What signed the person back in
    was the kiosk link itself, sitting in history or a bookmark. A link that
    signs you in is a password, and logging out cannot un-bookmark a
    password.

    So logout now leaves a marker on the browser, and the kiosk controller
    refuses to act on it while that marker is there. Signing in with a
    password once clears it, which is the deliberate act that says this
    device is trusted again.

    Only a PERSON signing out locks the device. A till account signing out
    is a till closing, and locking that would leave the counter needing a
    manager's password to reopen -- with the till account having none, by
    design. See the logout override below for why that distinction is the
    whole feature.

    The register also carries a switch to turn this off entirely, for a
    counter where the quick link matters more than the lock.
    """

    @http.route()
    def logout(self, redirect='/odoo'):
        # WHO is signing out decides whether this locks the device, and
        # getting that wrong made the feature fight itself.
        #
        # The shop asked for two things that look contradictory: signing out
        # should stop somebody walking back in without a password, AND a
        # cashier should be able to open the till on their own. A first
        # version locked on every logout, so a till signing out at closing
        # left the counter needing a manager's password to reopen -- and the
        # till account has none, by design.
        #
        # They are only contradictory if "signed out" is treated as one
        # thing. The case worth locking is a PERSON with a real login signing
        # out and the bookmark letting them straight back in. A till account
        # signing out is just a till closing, and locking that helps nobody.
        uid = request.session.uid
        is_till_account = False
        if uid:
            is_till_account = bool(request.env['pos.config'].sudo().search_count(
                [('pos_retail_kiosk_user_id', '=', uid)]))

        response = super().logout(redirect=redirect)
        if not is_till_account:
            response.set_cookie(
                KIOSK_BLOCK_COOKIE, '1',
                max_age=KIOSK_BLOCK_MAX_AGE, samesite='Lax',
            )
        return response


class PosRetailHome(Home):
    """Signing in with a password trusts this browser again."""

    @http.route()
    def web_login(self, redirect=None, **kw):
        response = super().web_login(redirect=redirect, **kw)
        # request.session.uid is set only once credentials actually passed,
        # so this clears the marker on a successful sign-in and leaves it
        # alone when someone merely loaded the login page or got the password
        # wrong.
        if request.session.uid:
            response.set_cookie(KIOSK_BLOCK_COOKIE, '', max_age=0)
        return response
