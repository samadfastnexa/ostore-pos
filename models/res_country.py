from odoo import api, fields, models


class ResCountry(models.Model):
    _inherit = 'res.country'

    # Odoo ships 250 countries with no way to trim the list. An active flag
    # lets the ORM's standard archive filter hide the ones this store will
    # never sell to -- country dropdowns, the POS customer editor and the
    # Localization config list all shrink to the active set. Records are only
    # archived, never deleted, so existing addresses keep their country and any
    # country can be re-enabled from Contacts > Configuration > Localization >
    # Countries via the Archived filter.
    active = fields.Boolean(
        default=True,
        help="Untick to hide this country from address forms and the POS "
             "customer editor, so staff only scroll through the countries you "
             "actually deal with. Nothing is deleted; existing addresses keep "
             "their country and you can bring one back with the Archived "
             "filter.",
    )

    @api.model
    def _load_pos_data_fields(self, config):
        # phone_code is needed to turn a locally-written number such as
        # "0322 4846103" into the international form WhatsApp requires
        # (923224846103). Core loads res.country into the POS but only
        # id/name/code/vat_label, so the dialling code has to be asked for.
        return super()._load_pos_data_fields(config) + ['phone_code']
