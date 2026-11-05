"""Offline tests for planning_compare.py. The scripted model here only proves the plumbing (tools, scoring, counting, budget);
it says nothing about whether planning beats reacting. Run: python3 -m unittest test_planning_compare"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import planning_compare as pc  # noqa: E402


def scripted_chat(solves=True):
    """A scripted 'model': it knows each task's right answer. solves=False places a wrong order and gives a wrong total."""
    def chat(messages, tools):
        if tools is None:
            return {"role": "assistant", "content": "1. Check stock.\n2. Compare prices.\n3. Order.\n4. Add the total."}, 50, 40
        task = next(t for t in pc.TASKS if t[0] == messages[1]["content"])
        placed = [m for m in messages if m["role"] == "tool"]
        wanted = list(task[1].items()) if solves else [(("Corner Dairy", "oat milk"), 6)]
        if len(placed) < len(wanted):
            (shop, item), quantity = wanted[len(placed)]
            call = {"id": f"c{len(placed)}", "type": "function", "function": {"name": "place_order", "arguments": json.dumps({"shop": shop, "item": item, "quantity": quantity})}}
            return {"role": "assistant", "content": None, "tool_calls": [call]}, 100, 20
        return {"role": "assistant", "content": f"Total ${task[2]:.2f}" if solves else "Total $1.00"}, 100, 20
    return chat


class CompareTests(unittest.TestCase):
    def test_the_right_answers_are_really_right(self):
        """Each task's expected orders and total are recomputed from the shop data by brute force where the rule is simple."""
        shops = pc.SHOPS
        price = lambda s, i: shops[s][i][0]
        stock = lambda s, i: shops[s][i][1]
        self.assertEqual(sum(q * price(s, i) for (s, i), q in pc.TASKS[0][1].items()), 12.00)
        cheapest_with_stock = min((s for s in shops if stock(s, "oat milk") >= 6), key=lambda s: price(s, "oat milk"))
        self.assertEqual(cheapest_with_stock, "Green Grocer")
        self.assertEqual(round(sum(q * price(s, i) for (s, i), q in pc.TASKS[6][1].items()), 2), 25.20)
        for _, orders, total in pc.TASKS:
            for (s, i), q in orders.items():
                self.assertLessEqual(q, stock(s, i))
            if orders:
                self.assertAlmostEqual(sum(q * price(s, i) for (s, i), q in orders.items()), total, places=2)
        self.assertEqual(len(pc.TASKS), 10)

    def test_world_refuses_an_order_the_shop_cannot_fill(self):
        world = pc.World()
        self.assertIn("error", world.run("place_order", {"shop": "Corner Dairy", "item": "oat milk", "quantity": 1}))
        self.assertEqual(world.orders, {})
        self.assertEqual(world.run("place_order", {"shop": "Market Hall", "item": "oat milk", "quantity": 2})["line_total"], 4.40)
        self.assertEqual(world.run("check_stock", {"shop": "Market Hall", "item": "oat milk"}), 10)

    def test_a_scripted_solver_scores_everything_and_a_wrong_one_scores_nothing(self):
        rows, _ = pc.compare(scripted_chat(True))
        self.assertEqual(pc.summary(rows)["reactive"]["success"], 10)
        rows, _ = pc.compare(scripted_chat(False))
        self.assertEqual(pc.summary(rows)["plan"]["success"], 0)

    def test_plan_mode_adds_exactly_one_model_call(self):
        reactive = pc.run_agent(scripted_chat(True), pc.TASKS[0], "reactive")
        plan = pc.run_agent(scripted_chat(True), pc.TASKS[0], "plan")
        self.assertEqual(plan[2], reactive[2] + 1)

    def test_the_budget_stops_the_run_and_says_so(self):
        rows, spent = pc.compare(scripted_chat(True), price_in=1_000_000, price_out=1_000_000, budget=1.0)
        self.assertTrue(any(r.get("skipped") == "budget reached" for r in rows))
        self.assertGreaterEqual(spent, 1.0)

    def test_a_wrong_total_with_the_right_orders_still_fails(self):
        world = pc.World()
        world.run("place_order", {"shop": "Green Grocer", "item": "oat milk", "quantity": 6})
        self.assertTrue(pc.score(pc.TASKS[0], world, "That comes to $12.00."))
        self.assertFalse(pc.score(pc.TASKS[0], world, "That comes to $13.00."))


if __name__ == "__main__":
    unittest.main()
