"""Does planning beat the reactive loop? The same model and the same four shop tools, ten multi-step requests, two ways:
reactive  = think, call a tool, read the result, repeat (ReAct)
plan-first = write the whole plan, then run it with a check after each step (Plan-and-Solve, one replan allowed)
Each request has an exact right answer, so success is counted by code, not by opinion. Steps, tokens and cost are counted too.
Run:  python3 planning_compare.py --fake            scripted, offline, free
      python3 planning_compare.py --live            needs OPENAI_API_KEY; stops at --budget dollars (default 3.00)
Environment: PLAN_MODEL (default gpt-4.1-mini), PLAN_PRICE_IN and PLAN_PRICE_OUT in dollars per million tokens (defaults 0.40 and 1.60).
"""
import argparse
import copy
import json
import os
import re
import urllib.request

SHOPS = {
    "Corner Dairy": {"oat milk": (1.90, 0), "vanilla": (4.00, 5), "cones": (0.50, 30)},
    "Market Hall": {"oat milk": (2.20, 12), "vanilla": (3.60, 2), "cones": (0.45, 100)},
    "Green Grocer": {"oat milk": (2.00, 6), "vanilla": (3.90, 8), "cones": (0.55, 10)},
}
# (request, the orders that are right as {(shop, item): quantity}, the total to tell, or None when nothing may be ordered)
TASKS = [
    ("Order 6 oat milk from the cheapest shop that has it in stock. Tell me the total.", {("Green Grocer", "oat milk"): 6}, 12.00),
    ("Order 10 oat milk from the cheapest shop that can fill all 10. Tell me the total.", {("Market Hall", "oat milk"): 10}, 22.00),
    ("I need 4 vanilla and 20 cones from one shop. Order from the cheapest single shop that has both. Tell me the total.",
     {("Corner Dairy", "vanilla"): 4, ("Corner Dairy", "cones"): 20}, 26.00),
    ("Order 3 vanilla from the cheapest shop that has 3, and 3 oat milk from the cheapest shop that has 3. Tell me the total.",
     {("Green Grocer", "vanilla"): 3, ("Green Grocer", "oat milk"): 3}, 17.70),
    ("Order 8 cones from the cheapest shop that has 8. Then order 5 vanilla from the cheapest shop that has 5. Tell me the total.",
     {("Market Hall", "cones"): 8, ("Green Grocer", "vanilla"): 5}, 23.10),
    ("What would 6 oat milk plus 4 vanilla cost at the cheapest single shop that has both? Do not order anything, just tell me the total.", {}, 27.60),
    ("Order 12 oat milk as cheaply as possible, splitting across shops if that is cheaper. Tell me the total.",
     {("Green Grocer", "oat milk"): 6, ("Market Hall", "oat milk"): 6}, 25.20),
    ("Order 5 vanilla and 5 cones from the same shop, the cheapest shop that can fill both. Tell me the total.",
     {("Green Grocer", "vanilla"): 5, ("Green Grocer", "cones"): 5}, 22.25),
    ("Order 1 oat milk, 1 vanilla and 1 cones, each from the cheapest shop that has it in stock. Tell me the total.",
     {("Green Grocer", "oat milk"): 1, ("Market Hall", "vanilla"): 1, ("Market Hall", "cones"): 1}, 6.05),
    ("Order 7 oat milk from one shop, but not from a shop that would be left with fewer than 3. Tell me the total.", {("Market Hall", "oat milk"): 7}, 15.40),
]
TOOLS = [
    {"type": "function", "function": {"name": "list_shops", "description": "The names of the shops.", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_price", "description": "Price of one item at a shop, in dollars.",
                                      "parameters": {"type": "object", "properties": {"shop": {"type": "string"}, "item": {"type": "string"}}, "required": ["shop", "item"]}}},
    {"type": "function", "function": {"name": "check_stock", "description": "How many of an item a shop has.",
                                      "parameters": {"type": "object", "properties": {"shop": {"type": "string"}, "item": {"type": "string"}}, "required": ["shop", "item"]}}},
    {"type": "function", "function": {"name": "place_order", "description": "Order a quantity of an item from a shop. Fails if the shop has too few.",
                                      "parameters": {"type": "object", "properties": {"shop": {"type": "string"}, "item": {"type": "string"}, "quantity": {"type": "integer"}},
                                                     "required": ["shop", "item", "quantity"]}}},
]
MAX_STEPS = 12


class World:
    def __init__(self):
        self.shops, self.orders, self.calls = copy.deepcopy(SHOPS), {}, 0

    def run(self, name, args):
        self.calls += 1
        try:
            if name == "list_shops":
                return list(self.shops)
            shop, item = args["shop"], args["item"]
            price, stock = self.shops[shop][item]
            if name == "get_price":
                return price
            if name == "check_stock":
                return stock
            if name == "place_order":
                quantity = int(args["quantity"])
                if quantity < 1 or quantity > stock:
                    return {"error": f"{shop} has only {stock} {item}"}
                self.shops[shop][item] = (price, stock - quantity)
                self.orders[(shop, item)] = self.orders.get((shop, item), 0) + quantity
                return {"ordered": quantity, "line_total": round(quantity * price, 2)}
        except (KeyError, TypeError, ValueError):
            return {"error": "unknown shop or item"}
        return {"error": "unknown tool"}


def score(task, world, answer):
    _, orders, total = task
    said = [float(x) for x in re.findall(r"\d+\.\d\d|\d+", (answer or "").replace(",", ""))]
    return world.orders == orders and any(abs(x - total) < 0.005 for x in said)


REACTIVE = "You are Lucy's ordering assistant. Use the tools. When you are done, answer the owner in one short message that states the total in dollars."
PLANNER = ("Write a numbered plan for this request, using only these tools: list_shops, get_price, check_stock, place_order. "
           "Put every check before any order. Do not order in the plan. Do not run the plan. Plain numbered lines only.")
EXECUTOR = (REACTIVE + " Follow this plan step by step. After each step, say in one line whether its check passed. "
            "If a check fails, rewrite the rest of the plan in one line and continue. Never order before the checks pass.\nPLAN:\n")


def run_agent(chat, task, mode):
    """chat(messages, tools) -> (message dict, tokens_in, tokens_out). Returns (world, answer, model_calls, tokens_in, tokens_out)."""
    world, tin, tout, calls = World(), 0, 0, 0
    system = REACTIVE
    if mode == "plan":
        plan, a, b = chat([{"role": "system", "content": PLANNER}, {"role": "user", "content": task[0]}], None)
        tin, tout, calls, system = tin + a, tout + b, 1, EXECUTOR + (plan.get("content") or "")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": task[0]}]
    answer = None
    for _ in range(MAX_STEPS):
        reply, a, b = chat(messages, TOOLS)
        tin, tout, calls = tin + a, tout + b, calls + 1
        messages.append(reply)
        if not reply.get("tool_calls"):
            answer = reply.get("content")
            break
        for call in reply["tool_calls"]:
            result = world.run(call["function"]["name"], json.loads(call["function"]["arguments"] or "{}"))
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result)})
    return world, answer, calls, tin, tout


def compare(chat, price_in=0.40, price_out=1.60, budget=3.00, tasks=TASKS):
    rows, spent = [], 0.0
    for number, task in enumerate(tasks, 1):
        for mode in ("reactive", "plan"):
            if spent >= budget:
                rows.append({"task": number, "mode": mode, "skipped": "budget reached"})
                continue
            world, answer, calls, tin, tout = run_agent(chat, task, mode)
            cost = (tin * price_in + tout * price_out) / 1_000_000
            spent += cost
            rows.append({"task": number, "mode": mode, "success": score(task, world, answer), "tool_calls": world.calls, "model_calls": calls,
                         "tokens": tin + tout, "cost": round(cost, 5), "answer": answer})
    return rows, round(spent, 4)


def summary(rows):
    out = {}
    for mode in ("reactive", "plan"):
        done = [r for r in rows if r["mode"] == mode and "skipped" not in r]
        out[mode] = {"runs": len(done), "success": sum(r["success"] for r in done), "tool_calls": sum(r["tool_calls"] for r in done),
                     "model_calls": sum(r["model_calls"] for r in done), "cost": round(sum(r["cost"] for r in done), 4)}
    return out


def openai_chat():
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise SystemExit("No OPENAI_API_KEY. Add it as a Codespaces secret, or use --fake.")
    model = os.environ.get("PLAN_MODEL", "gpt-4.1-mini")

    def chat(messages, tools):
        body = {"model": model, "messages": messages, "temperature": 0}
        if tools:
            body["tools"] = tools
        request = urllib.request.Request("https://api.openai.com/v1/chat/completions", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(request, timeout=90) as response:
            data = json.load(response)
        usage = data.get("usage", {})
        return data["choices"][0]["message"], usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
    return chat


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--fake", action="store_true")
    parser.add_argument("--budget", type=float, default=3.00)
    parser.add_argument("--out", default="planning_compare_result.json")
    args = parser.parse_args()
    if args.live == args.fake:
        raise SystemExit("Choose one: --fake or --live.")
    if args.fake:
        from test_planning_compare import scripted_chat
        chat = scripted_chat()
    else:
        chat = openai_chat()
    rows, spent = compare(chat, float(os.environ.get("PLAN_PRICE_IN", 0.40)), float(os.environ.get("PLAN_PRICE_OUT", 1.60)), args.budget)
    result = {"model": os.environ.get("PLAN_MODEL", "gpt-4.1-mini") if args.live else "scripted", "spent_dollars": spent, "summary": summary(rows), "rows": rows}
    with open(args.out, "w") as handle:
        json.dump(result, handle, indent=1)
    print(json.dumps(result["summary"], indent=1), "\nspent $", spent, "\nraw:", args.out)
    if args.fake:
        print("The scripted model always answers right. This run proves the plumbing only, not that planning helps.")


if __name__ == "__main__":
    main()
