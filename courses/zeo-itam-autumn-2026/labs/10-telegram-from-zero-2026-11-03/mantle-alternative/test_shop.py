import os
import unittest

import shop


class ShelfTests(unittest.TestCase):
    def setUp(self):
        self.saved = dict(shop.INVENTORY)
        os.environ["LUCY_SENDER_ID"] = "lucy"

    def tearDown(self):
        shop.INVENTORY.clear()
        shop.INVENTORY.update(self.saved)
        os.environ.pop("LUCY_SENDER_ID", None)

    def test_minute_one(self):
        self.assertEqual(shop.stock_reply("vanilla"), "vanilla: 2 tubs")

    def test_change_one_number(self):
        shop.INVENTORY["vanilla"] = 7
        self.assertEqual(shop.stock_reply("vanilla"), "vanilla: 7 tubs")
        self.assertEqual(shop.stock_reply("chocolate"), "chocolate: 12 tubs")

    def test_empty_shelf_is_not_unknown(self):
        self.assertEqual(shop.stock_reply("strawberry"), "strawberry: 0 tubs")
        self.assertEqual(shop.stock_reply("mango"), "Unknown flavor")

    def test_owner_gets_a_proposal_and_stock_is_unchanged(self):
        self.assertEqual(shop.restock_reply("lucy", "vanilla"), "Propose 6 tubs")
        self.assertEqual(shop.INVENTORY["vanilla"], 2)

    def test_customer_is_refused_and_stock_is_unchanged(self):
        self.assertEqual(shop.restock_reply("customer", "vanilla"), "Owner only")
        self.assertEqual(shop.INVENTORY["vanilla"], 2)

    def test_nobody_is_owner_when_the_setting_is_missing(self):
        del os.environ["LUCY_SENDER_ID"]
        self.assertEqual(shop.restock_reply("lucy", "vanilla"), "Owner only")

    def test_proposal_never_below_zero(self):
        shop.INVENTORY["vanilla"] = 11
        self.assertEqual(shop.restock_reply("lucy", "vanilla"), "Propose 0 tubs")

    def test_other_flavor_has_no_target(self):
        self.assertEqual(shop.restock_reply("lucy", "chocolate"), "No target for that flavor")


if __name__ == "__main__":
    unittest.main()
