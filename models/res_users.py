import re

from odoo import api, fields, models, tools
from odoo.exceptions import AccessDenied, AccessError, UserError
from odoo.tools.translate import _

from .res_company import TRADING_COMPANY_DOMAIN, pos_retail_trading_company


class ResUsers(models.Model):
    _inherit = 'res.users'

    # What the SIGNED-IN account may do, keyed by the flag the till sees.
    #
    # Distinct from the per-cashier capabilities on hr.employee, and the
    # distinction is the whole point. A cashier's own permissions decide what
    # that PERSON is allowed to ask for; these decide what the SESSION can
    # actually carry out, because every call from the till runs as whoever the
    # browser is signed in as. A button needs both to be true, and offering
    # one without checking the other is what produced an "Access Error" naming
    # twelve security groups in front of a customer.
    POS_RETAIL_SESSION_CAPABILITIES = {
        '_can_quotation': 'sales_team.group_sale_salesman',
    }

    @api.model
    def _load_pos_data_read(self, records, config):
        """Tell the till what this session is allowed to do.

        Core loads all_group_ids here and deletes the key again before it
        reaches the browser, so nothing client-side can see what the session
        may do. Rather than send the whole group list back -- which is a map
        of the security model handed to every till -- only named capabilities
        go over, one boolean per feature that has a button.
        """
        rows = super()._load_pos_data_read(records, config)
        for row in rows:
            user = self.browse(row['id'])
            for flag, group_xmlid in self.POS_RETAIL_SESSION_CAPABILITIES.items():
                row[flag] = user.has_group(group_xmlid)
        return rows

    def _pos_retail_default_company(self):
        """Land a new user in a shop rather than the holding company.

        Core defaults both company fields to self.env.company, so a user
        created while the owner happens to be switched to MURSHID Company is
        put there too -- a company with no till, no shelves and next to no
        products. The new cashier then signs in to an empty screen and nothing
        explains it. Only the starting point moves; see
        pos_retail_assignable_company_ids for what may still be chosen.

        prefer_member_shop, because this default also has to sit inside
        pos_retail_assignable_company_ids -- falling back to the holding
        company here would put a value in the field that its own dropdown
        refuses to offer.
        """
        return pos_retail_trading_company(self.env, prefer_member_shop=True)

    company_id = fields.Many2one(
        default=lambda self: self._pos_retail_default_company().id)
    company_ids = fields.Many2many(
        default=lambda self: self._pos_retail_default_company().ids)

    pos_retail_assignable_company_ids = fields.Many2many(
        'res.company', string="Assignable Companies", compute_sudo=True,
        compute='_compute_pos_retail_assignable_company_ids',
        help="Technical: the companies the Companies field may offer for this "
             "person. Shops for everyone; administrators may also be put in "
             "the holding company, since that is where the chart of accounts "
             "and the taxes are maintained.")

    @api.depends('all_group_ids')
    def _compute_pos_retail_assignable_company_ids(self):
        """Offer shops to everyone, and the holding company to administrators.

        A flat "shops only" rule here is a one-way door, and a bad one. There
        is no other way back in: res.company.user_ids appears on no company
        form, My Profile carries no company field, and the users list exposes
        Companies only as a search filter. env.company comes from
        allowed_company_ids, which comes from this very field, so a holding
        company nobody holds is a holding company nobody can administer -- no
        taxes, no chart of accounts, no year end. Remove it from the last
        administrator by accident and only a database shell puts it back.

        Nothing is lost by leaving it out for everyone else: branches already
        reach the parent's journals, accounts, taxes and fiscal positions
        through core's parent_of rules WITHOUT holding it, so a cashier gains
        nothing from the parent and only stands to be dropped into a company
        with no till.
        """
        Company = self.env['res.company'].sudo()
        shops = Company.search(TRADING_COMPANY_DOMAIN)
        holdings = Company.search([('child_ids', '!=', False)])
        for user in self:
            # has_group(), not `group in all_group_ids`: on a record still
            # being filled in on screen the membership test has to resolve the
            # pending Role radio, and comparing recordsets does not -- flipping
            # Role to Administrator would leave the holding company hidden.
            extra = holdings if user.has_group('base.group_system') else Company.browse()
            user.pos_retail_assignable_company_ids = shops | extra

    def _pos_retail_login_from_name(self, name, taken=()):
        """Build a sign-in name out of a person's name: "Cashier Ali" -> cashier.ali.

        Anything that is not a letter or a digit becomes a dot, so Urdu-English
        spellings, double spaces and stray punctuation all land on something
        typeable at a counter. If the result is already taken a number is
        appended, checked against hidden users too -- a login stays reserved
        after someone is hidden, and colliding with one raises a database error
        that says nothing useful.

        `taken` carries the names handed out earlier in the same create() batch.
        Without it two people called Ali imported together both derive "ali",
        because neither is in the database yet when the other is worked out, and
        the whole import dies on a bare psycopg2 unique violation naming a
        constraint rather than either person.
        """
        base = re.sub(r'[^a-z0-9]+', '.', (name or '').strip().lower()).strip('.')
        if not base:
            return False
        Users = self.env['res.users'].sudo().with_context(active_test=False)
        taken = set(taken)
        candidate, n = base, 1
        while candidate in taken or Users.search_count([('login', '=', candidate)]):
            n += 1
            candidate = '%s%s' % (base, n)
        return candidate

    def _pos_retail_apply_password(self, password):
        """Store a password the way core's own wizard finally does.

        Straight to the hash, skipping the compute/inverse pair entirely, so
        there is nothing left to race. Same guards core applies: only an
        administrator may set one, and never your own -- changing the password
        of the session you are sitting in logs you out mid-request, which is
        why core routes that through its wizard instead.
        """
        self.ensure_one()
        if not self.env.user._is_system():
            raise AccessError(_(
                "Only the Super Admin can set or reset a password. Please contact them."))
        if self.id == self.env.uid:
            raise UserError(_(
                "To change your own password, use Change Password on your own "
                "profile. Setting it here would sign you out halfway through."))
        self.sudo()._set_encrypted_password(
            self.id, self._crypt_context().hash(password))

    def write(self, vals):
        # Same handling as create(): take the password out and apply it after,
        # because core's new_password inverse silently does nothing here. A
        # password typed on an existing user's form would otherwise look saved
        # and change nothing at all, which is worse than not offering the box.
        password = (vals.pop('new_password', '') or '').strip()
        res = super().write(vals)
        if password:
            for user in self:
                user._pos_retail_apply_password(password)
        return res

    @api.onchange('name')
    def _pos_retail_onchange_name_fills_login(self):
        """Fill the sign-in name in as the person's name is typed.

        `login` is required by the model, and a view cannot relax that -- the
        web client blocks Save with "Missing required fields" and reddens a box
        wearing an envelope icon, which reads as "an email address is
        compulsory". It is not, but the form gives no way to learn that.

        Filling it here rather than only in create() means the value appears on
        screen while the form is still open, so it can be seen, corrected or
        replaced before saving instead of being decided invisibly. Anything
        already typed is left alone, so this only ever helps an empty box.
        """
        for user in self:
            if user.name and not (user.login or '').strip():
                derived = user._pos_retail_login_from_name(user.name)
                if derived:
                    user.login = derived

    @api.model_create_multi
    def create(self, vals_list):
        """Send new POS managers to the dashboard; leave everyone else alone.

        This replaces an ir.default that set the dashboard as the home action
        for EVERY user created. Combined with the manager-only guard on
        get_dashboard_data, that meant each newly created cashier logged in,
        was thrown at the dashboard, and got "available to Point of Sale
        managers only" over an empty screen -- every time, forever. Deciding
        per user at create time is the fix; a blanket default cannot know
        which groups the user ended up in.

        It also fills in a missing sign-in name. `login` is required by the
        model, so leaving it blank stopped the save dead with "Missing required
        fields", pointing at a box wearing an envelope icon -- which reads as
        "an email address is compulsory", and it is not. Shop staff do not all
        have an email, and typing one for every cashier is friction at a
        counter with a queue. Type the person's name, press Save, and the login
        comes from the name; type a login yourself and it is left alone.
        """
        # Taken out of the values and applied after the record exists. Core's
        # own new_password field is unreliable through a form save: it shares
        # _compute_password with `password`, and that compute blanks BOTH. On a
        # full create the compute wins the race against _set_new_password, which
        # then reads an empty string and skips -- the form sends the password,
        # the server accepts the save, and the person still cannot sign in.
        # Verified against the real payload: new_password arrives with its
        # value, and nothing is stored. Applying it ourselves is deterministic.
        passwords = [(vals.pop('new_password', '') or '').strip() for vals in vals_list]

        # Names handed out in this batch are not in the database yet, so they
        # have to be remembered here or two people with the same name collide.
        taken = set()
        for vals in vals_list:
            if (vals.get('login') or '').strip():
                taken.add(vals['login'].strip())
                continue
            derived = self._pos_retail_login_from_name(vals.get('name'), taken=taken)
            if derived:
                vals['login'] = derived
                taken.add(derived)
            else:
                # Only reachable when the name is blank or has no letters or
                # digits in it at all -- an import, say. Left alone this is a
                # not-null violation on a column nobody has heard of.
                raise UserError(_(
                    "Give this person a name, or a sign-in name of your own. "
                    "The sign-in name is normally made from the name, but "
                    "%(name)r leaves nothing to make one out of.",
                    name=vals.get('name') or ""))

        users = super().create(vals_list)

        for user, password in zip(users, passwords):
            if password:
                user._pos_retail_apply_password(password)

        dashboard = self.env.ref('pos_retail.action_pos_retail_dashboard',
                                 raise_if_not_found=False)
        # Lands a cashier in their own register instead of a menu they then
        # have to find their way out of. Managers keep the dashboard: they open
        # the back office far more often than a till.
        open_register = self.env.ref('pos_retail.action_pos_retail_open_my_register',
                                     raise_if_not_found=False)
        for user in users:
            if user.share or user.action_id:
                continue                      # portal user, or a deliberate choice
            if dashboard and user.has_group('point_of_sale.group_pos_manager'):
                user.action_id = dashboard.id
            elif open_register and user.has_group('point_of_sale.group_pos_user'):
                user.action_id = open_register.id
        return users

    @api.model
    def _pos_retail_sync_dashboard_home(self):
        """Put the POS dashboard home action on managers, and only managers.

        Done in Python, not as <record>/<function> domains, for two reasons a
        data file cannot handle:

        * "is a POS manager" means the group OR anything implying it, which
          has_group() resolves and a plain domain on group_ids does not. An
          earlier attempt using all_group_ids matched nobody, so the follow-up
          write cleared the real managers instead.
        * The old ir.default has to be DELETED. Dropping the <function> that
          created it leaves the record in place, so every newly created user
          still inherits the dashboard as their landing page and walks into the
          manager-only guard. Removing a default is an action, not an omission.
        """
        dashboard = self.env.ref('pos_retail.action_pos_retail_dashboard',
                                 raise_if_not_found=False)
        if not dashboard:
            return True

        self.env['ir.default'].sudo().discard_values(
            'res.users', 'action_id', [dashboard.id])

        for user in self.sudo().search([('share', '=', False)]):
            is_manager = user.has_group('point_of_sale.group_pos_manager')
            if is_manager and not user.action_id:
                user.action_id = dashboard.id
            elif not is_manager and user.action_id.id == dashboard.id:
                # Would greet them with "managers only" on every login.
                user.action_id = False
        return True

    def _change_password(self, new_passwd):
        if not self.env.user._is_system():
            raise AccessError(_("Only the Super Admin can set or reset a password. Please contact them."))
        super()._change_password(new_passwd)

    def unlink(self):
        """Keep at least one way back into the system.

        Core protects four accounts by xmlid -- __system__, base.user_admin,
        and the portal/public templates -- and nothing else. The account that
        actually administers THIS database was created by hand, so it carries
        no xmlid and core will delete it without a word. Nobody notices until
        the next login, and by then the only account left holding Settings is
        __system__, which has no usable password. That is a locked door with
        the key on the inside.

        Two ways in are shut here: deleting the last administrator, and
        deleting the account you are signed in as. Both are recoverable only
        from a database shell.

        Written as unlink() rather than @api.ondelete deliberately: ondelete
        methods have no guaranteed order between modules, so whichever fires
        first decides the wording. unlink() runs before all of them and the
        message is always this one.
        """
        if self.env.uid in self.ids:
            raise UserError(_(
                "You cannot delete the account you are signed in as. Ask "
                "another administrator to do it after you have signed out, or "
                "hide it instead."))

        admin_group = self.env.ref('base.group_system', raise_if_not_found=False)
        if admin_group:
            doomed_admins = self.filtered(lambda u: admin_group in u.all_group_ids)
            if doomed_admins:
                # SUPERUSER_ID is excluded on purpose: it is Odoo's internal
                # account for updates and module installs, has no password
                # anyone can sign in with, and so is no way back in.
                survivors = self.sudo().with_context(active_test=False).search_count([
                    ('id', 'not in', self.ids + [api.SUPERUSER_ID]),
                    ('all_group_ids', 'in', admin_group.id),
                    ('share', '=', False),
                ])
                if not survivors:
                    raise UserError(_(
                        "%(names)s cannot be deleted, because that would leave "
                        "nobody who can open Settings, add users or set "
                        "passwords. You would be locked out of your own "
                        "system, and only a technician with database access "
                        "could let you back in.\n\n"
                        "Give another user administrator rights first, then "
                        "delete this one. Or just hide it: it stops being able "
                        "to sign in, and its history stays intact.",
                        names=", ".join(doomed_admins.mapped('login')),
                    ))

        return super().unlink()

    @tools.ormcache('self.id', 'fname')
    def _pos_retail_can_edit_price_field(self, fname):
        """Whether this user may change `fname` (list_price/standard_price) on
        a product that already exists.

        A user who belongs to NO pos.retail.access.role at all is always
        allowed -- this feature only restricts users actually assigned one of
        the new roles, so every admin/manager who exists today is unaffected.
        Otherwise: allowed if at least one of their roles explicitly grants it
        (additive, same composition rule as every other Odoo permission).

        Cached in the DEFAULT ormcache namespace on purpose, NOT 'groups':
        the 'groups' container is only ever cleared by an explicit
        clear_cache('groups') (res.groups create/unlink, or implied_ids
        changes) -- assigning/removing a user from a group goes through
        res.users.write / res.groups.write, which clear only the
        'stable'/'default' containers. The default namespace is exactly the
        one core uses for the analogous per-user membership cache
        (res.users._get_group_ids), so membership changes from ANY direction
        invalidate this too. Membership is checked through all_user_ids so a
        role granted via another group's implied_ids chain is honoured the
        same as an explicit assignment.
        """
        self.ensure_one()
        field_map = {
            'list_price': 'can_edit_product_price',
            'standard_price': 'can_edit_product_cost',
        }
        role_field = field_map[fname]
        roles = self.env['pos.retail.access.role'].sudo().search([('all_user_ids', 'in', self.id)])
        if not roles:
            return True
        return any(roles.mapped(role_field))

    def _check_credentials(self, credential, env):
        """Sign in with a Kiosk Link token instead of a username and password.

        Exists so a till device can be bookmarked once and reopened by
        anyone at the counter with nothing to type but their own PIN
        afterwards -- see pos.config.pos_retail_kiosk_user_id /
        pos_retail_kiosk_token, and the controller at
        controllers/kiosk.py that is the only thing that ever sends this
        credential type.

        Same shape as core's own auth_passkey override: check for the type
        this method owns, handle it completely (raising AccessDenied on
        failure, same as any other auth method), and hand everything else
        to super so ordinary password logins keep working unchanged.

        The token is bound to BOTH this user and one specific pos.config, not
        to the user alone: it is not a general-purpose password replacement,
        only a way onto whichever till it was issued for. It is looked up
        with sudo() because the person attempting to sign in has, by
        definition, no session yet to hold any rights of their own.
        """
        if credential.get('type') != 'pos_retail_kiosk':
            return super()._check_credentials(credential, env)

        self.ensure_one()
        token = (credential.get('token') or '').strip()
        matched = token and self.env['pos.config'].sudo().search_count([
            ('pos_retail_kiosk_user_id', '=', self.id),
            ('pos_retail_kiosk_token', '=', token),
        ])
        if not matched:
            # AccessDenied specifically, matching core's own auth_passkey
            # override -- this is an authentication failure (who are you?),
            # not an authorization one (you can't do that), and _login's own
            # except clause only catches AccessDenied to log the attempt and
            # hand back a clean "login failed" rather than a raw error.
            raise AccessDenied(_("Wrong or expired kiosk link."))
        return {'uid': self.id, 'auth_method': 'pos_retail_kiosk', 'mfa': 'skip'}
