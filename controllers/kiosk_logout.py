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

    The cost is real and worth stating: a till that gets signed out, at
    closing or by accident, needs somebody to type a password once before
    the bookmark works again. That is the trade the shop asked for, and it
    is why the register carries a switch to turn this off for a counter
    where the quick link matters more.
    """

    @http.route()
    def logout(self, redirect='/odoo'):
        response = super().logout(redirect=redirect)
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
