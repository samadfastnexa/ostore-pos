from . import models


def _pos_retail_post_init(env):
    """Ensure a Store Credit eWallet loyalty program exists so refunds can be
    issued as store credit (native pos_loyalty eWallet 'eWallet Refund' flow).

    Idempotent -- skips if an eWallet program already exists. Uses loyalty's own
    eWallet template (_get_template_values) so the trigger product, earning rule
    and reward are configured exactly like one created from the Loyalty settings.
    """
    LoyaltyProgram = env['loyalty.program']
    if LoyaltyProgram.search_count([('program_type', '=', 'ewallet')]):
        return
    template = LoyaltyProgram._get_template_values().get('ewallet')
    if not template:
        return
    LoyaltyProgram.create({'name': 'Store Credit', 'program_type': 'ewallet', **template})
