"""Generated product barcodes.

Most hardware and sanitary goods arrive with nothing printed on them, so the
shopkeeper would otherwise invent a number per product before any shelf label
could be printed. New products therefore get one automatically.

The whole feature turns on one rule: a barcode that came from the real world
is never replaced. If Odoo overwrote a manufacturer's code, the number printed
on the box would stop matching the number in the database, and the product
would silently stop scanning at the till -- the failure mode is a queue, not
an error message. Most of what follows exists to hold that rule down.
"""
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProductBarcode(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.pos_retail_auto_product_barcode = True
        cls.Product = cls.env['product.template']
        cls.Variant = cls.env['product.product']

    # --- the barcode gets generated -------------------------------------

    def test_new_product_gets_a_barcode(self):
        product = self.Product.create({'name': 'PVC Pipe 1 inch', 'list_price': 300})
        self.assertTrue(product.barcode, "a new product should be scannable")

    def test_generated_barcode_is_a_valid_ean13(self):
        """Scanners reject a wrong check digit, so this is not cosmetic.

        A 12-digit body with a miscomputed 13th digit looks fine in the form
        and fails at the counter, which is the worst place to find out.
        """
        product = self.Product.create({'name': 'Brass Tap', 'list_price': 850})
        code = product.barcode
        self.assertEqual(len(code), 13, "EAN-13 is thirteen digits: %s" % code)
        self.assertTrue(code.isdigit(), "barcodes must be digits only: %s" % code)
        body, check = code[:12], int(code[12])
        total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(body))
        self.assertEqual(check, (10 - total % 10) % 10, "check digit is wrong")

    def test_generated_barcode_uses_the_in_store_range(self):
        """298 is inside GS1's 20-29 'restricted circulation' block.

        That block is reserved worldwide for codes that never leave the shop,
        which is the guarantee that an invented number can never collide with
        a real manufacturer's barcode on some future delivery.
        """
        product = self.Product.create({'name': 'Cement Bag 50kg', 'list_price': 1400})
        self.assertTrue(product.barcode.startswith('298'),
                        "expected the 298 in-store run, got %s" % product.barcode)

    def test_products_and_packages_do_not_share_a_run(self):
        """A package barcode and a product barcode must never be the same code.

        The till resolves a scan against both models; a shared code would ring
        up whichever matched first, which is a bundle sold at the loose price
        or the reverse.
        """
        product = self.Product.create({'name': 'Paint 1L', 'list_price': 900})
        package = self.env['product.uom'].create({
            'product_id': product.product_variant_id.id,
            'uom_id': self.env.ref('uom.product_uom_dozen').id,
        })
        self.assertTrue(product.barcode.startswith('298'))
        self.assertTrue(package.barcode.startswith('299'))
        self.assertNotEqual(product.barcode, package.barcode)

    # --- a real barcode is never replaced -------------------------------

    def test_a_typed_barcode_is_kept(self):
        product = self.Product.create({
            'name': 'Nestle Water 1.5L', 'list_price': 80,
            'barcode': '8964000111119'})
        self.assertEqual(product.barcode, '8964000111119',
                         "a scanned manufacturer barcode must never be replaced")

    def test_an_imported_barcode_is_kept(self):
        """The import sheet has a Barcode column, and it must win.

        Same rule as the form, different code path: base_import goes through
        load() rather than a plain create(), so it is asserted separately.
        """
        result = self.Product.load(
            ['name', 'list_price', 'barcode'],
            [['Imported Tap', '850', '8964000222226']])
        self.assertFalse(result['messages'], result['messages'])
        product = self.Product.browse(result['ids'])
        self.assertEqual(product.barcode, '8964000222226')

    def test_bulk_fill_never_overwrites(self):
        """The catch-up action is for blanks only.

        Anything with a code may already have a label printed and stuck to
        stock in the aisle.
        """
        kept = self.Product.create({
            'name': 'Has A Barcode', 'list_price': 10,
            'barcode': '8964000333333'})
        self.company.pos_retail_auto_product_barcode = False
        blank = self.Product.create({'name': 'No Barcode', 'list_price': 20})
        self.assertFalse(blank.barcode)

        variants = (kept | blank).product_variant_ids
        variants.action_pos_retail_generate_barcode()

        self.assertEqual(kept.barcode, '8964000333333', "existing code was overwritten")
        self.assertTrue(blank.barcode, "blank code was not filled")

    # --- the setting -----------------------------------------------------

    def test_setting_off_leaves_the_barcode_blank(self):
        """A shop selling only branded goods should not accumulate invented
        codes that are printed nowhere."""
        self.company.pos_retail_auto_product_barcode = False
        product = self.Product.create({'name': 'Branded Only', 'list_price': 500})
        self.assertFalse(product.barcode)

    # --- uniqueness ------------------------------------------------------

    def test_every_generated_barcode_is_unique(self):
        codes = [
            self.Product.create({'name': 'Bulk %d' % i, 'list_price': 10}).barcode
            for i in range(25)
        ]
        self.assertEqual(len(set(codes)), 25, "generated barcodes repeated")

    def test_generation_skips_a_code_already_taken(self):
        """The sequence does not know what is already in the database.

        An import can supply its own 298-prefixed codes, so the next sequence
        number may already be on a product. The generator has to step over it
        rather than raise -- otherwise one imported row poisons every product
        created afterwards.
        """
        next_code = self.Variant._pos_retail_next_free_product_barcode()
        # Park that exact code on a product, then prove the next create()
        # routes around it instead of failing on the unique index.
        self.Product.create({
            'name': 'Squatter', 'list_price': 1, 'barcode': next_code})
        later = self.Product.create({'name': 'After Squatter', 'list_price': 2})
        self.assertTrue(later.barcode)
        self.assertNotEqual(later.barcode, next_code)

    def test_duplicate_barcodes_are_still_rejected(self):
        """Generation must not have weakened the constraint it works around."""
        self.Product.create({
            'name': 'First', 'list_price': 10, 'barcode': '8964000444440'})
        with self.assertRaises(ValidationError):
            self.Product.create({
                'name': 'Second', 'list_price': 10, 'barcode': '8964000444440'})

    # --- variants --------------------------------------------------------

    def test_each_variant_gets_its_own_barcode(self):
        """Barcodes live on the variant, so four sizes need four codes.

        product.template.barcode is only a compute+inverse onto the variants,
        so generating at template level would leave three of four sizes
        unscannable -- and the form would not show it, because the template
        field displays the single-variant case.
        """
        attribute = self.env['product.attribute'].create({
            'name': 'Size',
            'value_ids': [
                (0, 0, {'name': '1/2 inch'}),
                (0, 0, {'name': '3/4 inch'}),
                (0, 0, {'name': '1 inch'}),
            ],
        })
        product = self.Product.create({
            'name': 'PVC Pipe', 'list_price': 300,
            'attribute_line_ids': [(0, 0, {
                'attribute_id': attribute.id,
                'value_ids': [(6, 0, attribute.value_ids.ids)],
            })],
        })
        variants = product.product_variant_ids
        self.assertEqual(len(variants), 3)
        codes = variants.mapped('barcode')
        self.assertTrue(all(codes), "a variant was left without a barcode")
        self.assertEqual(len(set(codes)), 3, "variants shared a barcode")
