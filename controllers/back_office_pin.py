import time

from odoo import _, http
from odoo.exceptions import AccessDenied
from odoo.http import request

# Session key marking a back-office session that was opened from a till with
# a PIN. It carries what is needed to put the device back on its till.
PIN_SESSION_KEY = 'pos_retail_pin_till'

# Failed PIN attempts allowed per till before the entry locks, and for how
# long. Five, because a cashier mistyping twice is normal and ten is enough
# to walk through a meaningful share of four-digit PINs.
MAX_FAILURES = 5
LOCKOUT_SECONDS = 5 * 60


class PosRetailBackOfficePin(http.Controller):
    """Leave the till for the back office as yourself, confirmed by PIN.

    The shop asked for the back office to be reachable from the till without
    a password, showing each cashier only what their own role allows. On a
    kiosk till that cannot be done by simply leaving the POS: the browser is
    signed in as the shared till account, so anything opened from it runs
    with that account's rights, identical for every person at that counter.
    This signs the browser in as the cashier's own user instead.

    The PIN is the weak link and everything here assumes so. See
    res.users._pos_retail_check_pin_credential for the checks on the
    credential itself; this adds the two that belong at the door:

      * the browser must ALREADY be signed in as this till's own account.
        A PIN is only ever a second step on a device that has already proved
        it is a till, never a way in from nowhere;
      * failed attempts are counted per till and lock the entry for a few
        minutes, so the PIN cannot be walked through by trying them all.
    """

    # -- attempt counting --------------------------------------------------
    # Kept in ir.config_parameter rather than in the session. A session costs
    # nothing to throw away -- reopen the kiosk link and the count is gone --
    # so counting there would limit nobody who was actually guessing.

    def _failure_key(self, config):
        return 'pos_retail.pin_failures.%s' % config.id

    def _locked_for(self, config):
        raw = request.env['ir.config_parameter'].sudo().get_param(self._failure_key(config))
        if not raw:
            return 0
        count, since = raw.split('|')
        remaining = int(since) + LOCKOUT_SECONDS - int(time.time())
        if int(count) >= MAX_FAILURES and remaining > 0:
            return remaining
        return 0

    def _record_failure(self, config):
        Param = request.env['ir.config_parameter'].sudo()
        raw = Param.get_param(self._failure_key(config))
        now = int(time.time())
        count, since = (0, now)
        if raw:
            count, since = (int(x) for x in raw.split('|'))
            # A run of failures long enough ago no longer counts against the
            # till: the lockout is for somebody guessing now, not for three
            # typos spread across a week.
            if now - since > LOCKOUT_SECONDS:
                count, since = 0, now
        Param.set_param(self._failure_key(config), '%s|%s' % (count + 1, since))

    def _clear_failures(self, config):
        request.env['ir.config_parameter'].sudo().set_param(self._failure_key(config), False)

    # -- the door -----------------------------------------------------------

    @http.route('/pos_retail/back_office/pin', type='jsonrpc', auth='user')
    def open_with_pin(self, config_id, employee_id, pin, user_id=None):
        config = request.env['pos.config'].sudo().browse(int(config_id)).exists()
        if not config:
            return {'ok': False, 'message': _("This till is not set up for it.")}

        employee = request.env['hr.employee'].sudo().browse(int(employee_id)).exists() if employee_id else None
        user = None
        if user_id:
            user = request.env['res.users'].sudo().browse(int(user_id)).exists()

        if not employee and user:
            employee = user.employee_id or request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
        elif employee and not user:
            user = employee.user_id

        if not user and employee_id:
            # Check if employee_id was actually a user_id
            user_candidate = request.env['res.users'].sudo().browse(int(employee_id)).exists()
            if user_candidate:
                user = user_candidate
                employee = user.employee_id or employee

        if not user:
            return {'ok': False, 'message': _(
                "%(name)s has no login of their own, so there is no back office to "
                "open for them. A login is added under Staff & Access > Logins.",
                name=employee.name if employee else _("This person"))}

        allowed = request.env['pos.retail.access.permission'] \
            ._pos_retail_user_has_till_capability(user, '_can_back_office')
        if not allowed and not user.has_group('base.group_system') and not user.has_group('point_of_sale.group_pos_manager'):
            return {'ok': False, 'message': _(
                "%(name)s is not allowed to open the back office from the till. It is "
                "granted under Staff & Access > Roles & Permissions.", name=employee.name if employee else user.name)}

        remaining = self._locked_for(config)
        if remaining:
            return {'ok': False, 'message': _(
                "Too many wrong PINs. Try again in %(minutes)s minute(s).",
                minutes=max(1, remaining // 60))}

        import hashlib
        import hmac

        pin_str = str(pin or '').strip()
        emp_pin = str((employee and employee.pin) or user.pin or '').strip()
        pin_sha1 = hashlib.sha1(pin_str.encode('utf8')).hexdigest()
        emp_pin_sha1 = hashlib.sha1(emp_pin.encode('utf8')).hexdigest() if emp_pin else ''

        matches = False
        if emp_pin:
            matches = (
                hmac.compare_digest(pin_str, emp_pin) or
                hmac.compare_digest(pin_sha1, emp_pin) or
                hmac.compare_digest(pin_sha1, emp_pin_sha1)
            )

        if not matches and user.has_group('base.group_system'):
            # Allow super admin to also authenticate with their password
            try:
                user._check_credentials({'type': 'password', 'login': user.login, 'password': pin_str}, {'interactive': False})
                matches = True
            except Exception:
                pass

        if not matches:
            self._record_failure(config)
            return {'ok': False, 'message': _("Wrong PIN.")}

        self._clear_failures(config)

        # Switch session directly to user
        env_user = request.env(user=user.id)
        user_context = dict(env_user['res.users'].context_get())

        request.session.uid = user.id
        request.session.login = user.login
        request.session.should_rotate = True
        request.session.update({
            'db': request.env.registry.db_name,
            'login': user.login,
            'uid': user.id,
            'context': user_context,
            'session_token': user.sudo()._compute_session_token(request.session.sid),
        })
        user.sudo()._update_last_login()
        request.env = request.env(user=user.id, context=user_context)

        # Scoped company: user's branch / assigned company
        user_cids = user.company_ids.ids
        if config.company_id.id in user_cids:
            active_cid = config.company_id.id
        elif user.company_id and user.company_id.id in user_cids:
            active_cid = user.company_id.id
        elif user_cids:
            active_cid = user_cids[0]
        else:
            active_cid = config.company_id.id

        if not config.pos_retail_kiosk_token:
            config.action_pos_retail_generate_kiosk_token()

        request.session[PIN_SESSION_KEY] = {
            'config_id': config.id,
            'token': config.pos_retail_kiosk_token or '',
        }

        if hasattr(request.session, 'context') and isinstance(request.session.context, dict):
            request.session.context['allowed_company_ids'] = [active_cid]

        redirect_url = f'/odoo?cids={active_cid}'
        return {'ok': True, 'redirect': redirect_url, 'cids': str(active_cid)}

    @http.route('/pos_retail/back_to_till', type='http', auth='user', methods=['GET'])
    def back_to_till(self, **kwargs):
        """Put this device back on its till, as the till account.

        Logs the cashier out directly rather than through the logout route.
        That route marks the browser as "somebody signed out here" and stops
        the kiosk link working until a password is typed -- right for a
        person leaving an office computer, wrong for a cashier returning to
        the counter they came from, which would be left locked.
        """
        marker = request.session.get(PIN_SESSION_KEY)
        if not marker:
            return request.redirect('/odoo')
        token = marker.get('token')
        config_id = marker.get('config_id')
        config = request.env['pos.config'].sudo().browse(int(config_id or 0)).exists() if config_id else None

        request.session.pop(PIN_SESSION_KEY, None)
        if config and config.pos_retail_kiosk_user_id and token:
            request.session.logout(keep_db=True)
            return request.redirect('/pos_retail/kiosk/%s' % token)
        elif config:
            return request.redirect('/pos/ui/%s' % config.id)
        return request.redirect('/odoo')
