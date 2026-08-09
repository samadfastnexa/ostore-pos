"""Tests for measurement-based selling (spec section 28).

These deliberately exercise Odoo's own conversion engine as well as our
classification. If a future Odoo release changes relative_factor semantics we
want the failure here, not in a shop's stock figures.
"""
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestMeasurement(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Product = cls.env['product.template']
        cls.unit = cls.env.ref('uom.product_uom_unit')
        cls.meter = cls.env.ref('uom.product_uom_meter')
        cls.cm = cls.env.ref('uom.product_uom_cm')
        cls.foot = cls.env.ref('uom.product_uom_foot')
        cls.kg = cls.env.ref('uom.product_uom_kgm')
        cls.gram = cls.env.ref('uom.product_uom_gram')
        cls.ton = cls.env.ref('uom.product_uom_ton')
        cls.litre = cls.env.ref('uom.product_uom_litre')
        cls.sqm = cls.env.ref('uom.product_uom_square_meter')
        cls.sqft = cls.env.ref('uom.product_uom_square_foot')
        cls.roll100 = cls.env.ref('pos_retail.uom_roll_100m')
        cls.bundle50 = cls.env.ref('pos_retail.uom_bundle_50m')

    def _product(self, name, uom, **vals):
        return self.Product.create(dict({
            'name': name, 'uom_id': uom.id, 'list_price': 100.0,
        }, **vals))

    # --- classification -------------------------------------------------

    def test_measurement_type_derived_from_unit(self):
        """Every supported unit lands in the right measurement kind."""
        cases = [
            (self.unit, 'piece'), (self.meter, 'length'), (self.cm, 'length'),
            (self.foot, 'length'), (self.kg, 'weight'), (self.gram, 'weight'),
            (self.litre, 'volume'), (self.sqm, 'area'), (self.sqft, 'area'),
            # A sized pack inherits the kind of what it is made of: a 100 m
            # roll is still a length, which is what lets it convert to metres.
            (self.roll100, 'length'),
        ]
        for uom, expected in cases:
            with self.subTest(uom=uom.name):
                product = self._product(f'T {uom.name}', uom)
                self.assertEqual(product.pos_retail_measurement_type, expected)

    def test_decimal_follows_measurement_type(self):
        """Measured goods allow fractions; counted goods do not."""
        self.assertTrue(self._product('Pipe', self.meter).pos_retail_allow_decimal)
        self.assertTrue(self._product('Cement', self.kg).pos_retail_allow_decimal)
        self.assertTrue(self._product('Paint', self.litre).pos_retail_allow_decimal)
        self.assertTrue(self._product('Tiles', self.sqft).pos_retail_allow_decimal)
        self.assertFalse(self._product('Tap', self.unit).pos_retail_allow_decimal)

    def test_measurement_type_follows_a_unit_change(self):
        """Switching the unit re-classifies the product."""
        product = self._product('Reclassify me', self.unit)
        self.assertEqual(product.pos_retail_measurement_type, 'piece')
        self.assertFalse(product.pos_retail_allow_decimal)
        product.uom_id = self.kg
        self.assertEqual(product.pos_retail_measurement_type, 'weight')
        self.assertTrue(product.pos_retail_allow_decimal)

    def test_manual_override_survives(self):
        """A shopkeeper can overrule the derivation (field is readonly=False)."""
        product = self._product('Boxed screws', self.unit)
        product.pos_retail_measurement_type = 'box'
        self.assertEqual(product.pos_retail_measurement_type, 'box')

    def test_manual_choices_survive_a_later_unit_change(self):
        """Editing the Unit must not silently discard what a human typed.

        These are stored computes with readonly=False, so they are editable but
        were not sticky: setting your own shortcuts and then correcting a typo
        in the Unit wiped them with no warning. Worse, picking a Measurement
        Type re-ran the shortcut compute and blanked it on the spot.
        """
        product = self._product('Sticky Pipe', self.meter)
        product.pos_retail_quick_qty = '1, 2, 3, 6, 12'
        product.pos_retail_measurement_type = 'box'
        # Setting the type must not blank the shortcuts in the same breath.
        self.assertEqual(product.pos_retail_quick_qty, '1, 2, 3, 6, 12')

        product.uom_id = self.kg
        self.assertEqual(product.pos_retail_quick_qty, '1, 2, 3, 6, 12')
        self.assertEqual(product.pos_retail_measurement_type, 'box')

        product.uom_id = self.meter
        self.assertEqual(product.pos_retail_quick_qty, '1, 2, 3, 6, 12')
        self.assertEqual(product.pos_retail_measurement_type, 'box')

    def test_untouched_products_still_follow_the_unit(self):
        """The stickiness must not freeze products nobody has edited."""
        product = self._product('Auto Pipe', self.meter)
        self.assertEqual(product.pos_retail_measurement_type, 'length')
        self.assertEqual(product.pos_retail_quick_qty, '0.5, 1, 2, 5, 10')
        product.uom_id = self.kg
        self.assertEqual(product.pos_retail_measurement_type, 'weight')
        self.assertEqual(product.pos_retail_quick_qty, '0.5, 1, 5, 10, 25')

    def test_clearing_shortcuts_by_hand_means_none(self):
        """Emptying the field means "no shortcuts", not "give me defaults"."""
        product = self._product('No Chips Pipe', self.meter)
        product.pos_retail_quick_qty = False
        product.uom_id = self.kg
        self.assertFalse(product.pos_retail_quick_qty)

    # --- conversion (Odoo's engine, exercised through our units) --------

    def test_length_conversion(self):
        self.assertAlmostEqual(self.meter._compute_quantity(1, self.cm), 100.0, places=4)
        self.assertAlmostEqual(self.cm._compute_quantity(250, self.meter), 2.5, places=4)
        self.assertAlmostEqual(self.foot._compute_quantity(3, self.foot), 3.0, places=4)

    def test_weight_conversion(self):
        self.assertAlmostEqual(self.kg._compute_quantity(1, self.gram), 1000.0, places=2)
        self.assertAlmostEqual(self.ton._compute_quantity(1, self.kg), 1000.0, places=2)
        self.assertAlmostEqual(self.gram._compute_quantity(2500, self.kg), 2.5, places=4)

    def test_area_conversion(self):
        """1 m2 is 10.7639 sq ft; tiles are quoted both ways.

        _compute_quantity ROUNDS to the target unit's precision unless told not
        to, so the default answer is 10.77 and not 10.7639. Both are asserted on
        purpose: the rounding is Odoo's, it is what a customer is billed for,
        and a future change to it should break this test rather than quietly
        move money on a large tile order.
        """
        self.assertAlmostEqual(self.sqm._compute_quantity(1, self.sqft), 10.77, places=2)
        self.assertAlmostEqual(
            self.sqm._compute_quantity(1, self.sqft, round=False), 10.7639, places=3)

    def test_packaging_unit_conversion(self):
        """A roll and a bundle are just lengths with a big factor."""
        self.assertAlmostEqual(self.roll100._compute_quantity(1, self.meter), 100.0, places=2)
        self.assertAlmostEqual(self.roll100._compute_quantity(5, self.meter), 500.0, places=2)
        self.assertAlmostEqual(self.bundle50._compute_quantity(2, self.meter), 100.0, places=2)
        # ...and back the other way, which is what a return has to do.
        self.assertAlmostEqual(self.meter._compute_quantity(500, self.roll100), 5.0, places=4)

    def test_incompatible_units_do_not_convert(self):
        """Section 26: selling a length in kilos must be impossible.

        Odoo refuses by returning the quantity untouched rather than inventing a
        factor between unrelated roots, so a silent wrong number cannot occur.
        """
        self.assertEqual(self.meter._compute_quantity(5, self.kg, raise_if_failure=False), 5.0)

    # --- quick quantities + validation (sections 10 and 26) -------------

    def test_quick_qty_defaults_per_type(self):
        self.assertEqual(self._product('Pipe', self.meter).pos_retail_quick_qty, '0.5, 1, 2, 5, 10')
        self.assertEqual(self._product('Cement', self.kg).pos_retail_quick_qty, '0.5, 1, 5, 10, 25')
        self.assertFalse(self._product('Tap', self.unit).pos_retail_quick_qty)

    def test_quick_qty_parsing(self):
        product = self._product('Pipe', self.meter)
        product.pos_retail_quick_qty = ' 0.5 , 1,2.25 ,  10 '
        self.assertEqual(product.pos_retail_quick_qty_list(), [0.5, 1.0, 2.25, 10.0])

    def test_quick_qty_rejects_non_numeric(self):
        product = self._product('Pipe', self.meter)
        with self.assertRaises(ValidationError):
            product.pos_retail_quick_qty = '1, two, 3'

    def test_quick_qty_rejects_zero_and_negative(self):
        product = self._product('Pipe', self.meter)
        with self.assertRaises(ValidationError):
            product.pos_retail_quick_qty = '1, 0, 5'
        with self.assertRaises(ValidationError):
            product.pos_retail_quick_qty = '1, -2'

    def test_quick_qty_rejects_fraction_on_piece_product(self):
        """Half a tap is not sellable, so it must not be offered as a button."""
        product = self._product('Tap', self.unit)
        with self.assertRaises(ValidationError):
            product.pos_retail_quick_qty = '1, 2.5'

    def test_measured_product_may_forbid_decimals_deliberately(self):
        """Unticking decimals on a measured product is allowed.

        A constraint used to forbid this. It broke bulk imports -- writing any
        field in the dependency chain leaves allow_decimal at its default while
        measurement_type has already resolved, and the constraint rejected that
        half-built state -- while guarding nothing, because the compute already
        switches decimals on by default. Turning it off is now a deliberate
        choice a shopkeeper is allowed to make.
        """
        product = self._product('Pipe', self.meter)
        self.assertTrue(product.pos_retail_allow_decimal)
        product.pos_retail_allow_decimal = False
        self.assertFalse(product.pos_retail_allow_decimal)

    def test_bulk_import_of_a_measured_product_succeeds(self):
        """Regression: the exact shape that used to fail.

        Creating a measured product while explicitly supplying a value in the
        computed chain is what a spreadsheet row does, and it must not trip a
        constraint.
        """
        product = self.Product.create({
            'name': 'Imported Pipe', 'uom_id': self.meter.id,
            'list_price': 200.0, 'pos_retail_quick_qty': '1, 3, 6',
        })
        self.assertEqual(product.pos_retail_measurement_type, 'length')
        self.assertEqual(product.pos_retail_quick_qty_list(), [1.0, 3.0, 6.0])

    # --- selling range still applies to measured goods (section 11) -----

    def test_price_range_enforced_on_measured_product(self):
        product = self._product(
            'PVC Pipe 1 inch', self.meter,
            list_price=200.0, minimum_selling_price=180.0, mrp=220.0)
        self.assertEqual(product.pos_retail_measurement_type, 'length')
        with self.assertRaises(ValidationError):
            product.list_price = 170.0   # under the floor
        with self.assertRaises(ValidationError):
            product.list_price = 230.0   # over the ceiling

    # --- POS payload ----------------------------------------------------

    def test_measurement_fields_reach_the_pos(self):
        config = self.env['pos.config'].search([], limit=1)
        fields_sent = self.Product._load_pos_data_fields(config)
        for field in ('pos_retail_measurement_type', 'pos_retail_allow_decimal',
                      'pos_retail_quick_qty', 'uom_name'):
            self.assertIn(field, fields_sent)
