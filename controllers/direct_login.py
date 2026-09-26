# -*- coding: utf-8 -*-
# Part of pos_retail: Direct Login POS and Auto-Session Opening

import logging
from odoo import http, _
from odoo.http import request
from odoo.addons.web.controllers.home import Home
from odoo.addons.point_of_sale.controllers.main import PosController

_logger = logging.getLogger(__name__)


def _ensure_active_pos_session(user, env=None):
    """Ensure an active POS session exists for user's assigned config, creating one if needed."""
    if not user or not user.pos_config_id:
        return None

    if env is None:
        try:
            env = request.env
        except (RuntimeError, AttributeError):
            env = user.env

    pos_config = user.sudo().pos_config_id
    if not pos_config.exists() or not pos_config.active:
        return None

    # Ensure access and employee link
    try:
        user.sudo()._ensure_pos_access_and_company()
    except Exception as e:
        _logger.warning("Could not sync POS access or employee for user %s: %s", user.login, e)

    # Search for an already active session
    session = env["pos.session"].sudo().search([
        ("config_id", "=", pos_config.id),
        ("state", "in", ["opening_control", "opened"]),
        ("rescue", "=", False),
    ], order="id desc", limit=1)

    if not session and user.pos_auto_open_session:
        # Check if an unclosed session is in closing_control
        closing_session = env["pos.session"].sudo().search([
            ("config_id", "=", pos_config.id),
            ("state", "=", "closing_control"),
            ("rescue", "=", False),
        ], order="id desc", limit=1)

        if closing_session:
            try:
                closing_session.action_pos_session_open()
                session = closing_session
                _logger.info("Resumed closing POS session %s for register %s", session.name, pos_config.name)
            except Exception as e:
                _logger.warning("Could not re-open closing session %s: %s", closing_session.id, e)

        if not session:
            try:
                pos_config._check_before_creating_new_session()
            except Exception as e:
                _logger.warning("POS config pre-check warning for %s: %s", pos_config.name, e)

            session = env["pos.session"].sudo().create({
                "user_id": user.id,
                "config_id": pos_config.id,
            })
            _logger.info("Auto-created new POS session %s for cashier %s on register %s",
                         session.name, user.login, pos_config.name)

            # Auto-open session to 'opened' state
            try:
                if session.state == "opening_control":
                    opening_cash = session.cash_register_balance_start or 0.0
                    session.set_opening_control(opening_cash, "Direct login auto-open")
            except Exception as e:
                _logger.warning("Could not auto-open session: %s", e)

    elif session and session.state == "opening_control" and user.pos_auto_open_session:
        try:
            opening_cash = session.cash_register_balance_start or 0.0
            session.set_opening_control(opening_cash, "Direct login auto-open")
        except Exception as e:
            _logger.warning("Could not set opening control on existing session: %s", e)

    return pos_config


class PosDirectLoginHome(Home):

    def _login_redirect(self, uid, redirect=None, env=None):
        """Redirect direct-login cashiers straight to their assigned POS register."""
        if uid:
            if env is None:
                try:
                    env = request.env
                except (RuntimeError, AttributeError):
                    env = None

            user = None
            if env:
                user = env["res.users"].sudo().browse(uid)

            if user and user.exists() and user.pos_direct_login and user.pos_config_id:
                if not redirect or redirect in ("/odoo", "/web", "/odoo/", "/web/", "/", "/web/login"):
                    pos_config = _ensure_active_pos_session(user, env=env)
                    if pos_config:
                        return f"/pos/ui/{pos_config.id}?from_backend=True"
                elif redirect and "/pos/ui" in redirect:
                    _ensure_active_pos_session(user, env=env)
                    if "from_backend=True" not in redirect:
                        delimiter = "&" if "?" in redirect else "?"
                        redirect = f"{redirect}{delimiter}from_backend=True"
                    return redirect
        return super()._login_redirect(uid, redirect=redirect)

    @http.route(["/web", "/odoo", "/odoo/<path:subpath>", "/scoped_app/<path:subpath>"], type="http", auth="none")
    def web_client(self, s_action=None, **kw):
        """Restrict backend access for direct-login cashiers and redirect appropriately."""
        if request.session.uid:
            user = request.env["res.users"].sudo().browse(request.session.uid)
            if user.exists() and user.pos_direct_login and user.pos_restrict_backend and user.pos_config_id:
                pos_config = user.sudo().pos_config_id
                active_session = request.env["pos.session"].sudo().search([
                    ("config_id", "=", pos_config.id),
                    ("state", "in", ["opening_control", "opened"]),
                    ("rescue", "=", False),
                ], limit=1)

                if not active_session and not user.pos_auto_open_session:
                    return request.redirect("/web/session/logout")

                _ensure_active_pos_session(user)
                return request.redirect(f"/pos/ui/{pos_config.id}?from_backend=True")

        return super().web_client(s_action=s_action, **kw)

    @http.route("/", type="http", auth="none")
    def index(self, s_action=None, db=None, **kw):
        """Root redirect for direct login cashiers."""
        if request.db and request.session.uid:
            user = request.env["res.users"].sudo().browse(request.session.uid)
            if user.exists() and user.pos_direct_login and user.pos_config_id:
                pos_config = _ensure_active_pos_session(user)
                if pos_config:
                    return request.redirect(f"/pos/ui/{pos_config.id}?from_backend=True")
        return super().index(s_action=s_action, db=db, **kw)


class PosDirectLoginPosController(PosController):

    @http.route(["/pos/ui/<config_id>", "/pos/ui/<config_id>/<path:subpath>"], auth="user", type="http")
    def pos_web(self, config_id=False, from_backend=False, subpath=None, **k):
        """Ensure active session exists and bypass login/screensaver for direct login cashiers."""
        user = request.env.user
        if user.pos_direct_login and user.pos_config_id:
            _ensure_active_pos_session(user)
            if subpath in ("saver", "login"):
                return request.redirect(f"/pos/ui/{config_id}?from_backend=True")
            from_backend = True

        return super().pos_web(config_id=config_id, from_backend=from_backend, subpath=subpath, **k)
