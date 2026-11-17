# 11 · Agentic ERP: planning, replanning and coordination (class notebooks, 17 November 2026)

The two notebooks for the ITAM class of 17 November 2026. Run the cells in order. They use Python 3.12 or later (Colab's runtime is fine), the `zeocore` package and pydantic, which the first code cell installs.

## Open them in Colab

- [Open `ITAM-Agentic-ERP-01-react-and-plan-and-execute.ipynb` in Colab](https://colab.research.google.com/github/profrodai/profrodai-resources/blob/main/courses/zeo-itam-autumn-2026/labs/11-agentic-erp-planning-2026-11-17/ITAM-Agentic-ERP-01-react-and-plan-and-execute.ipynb): ReAct and plan-and-execute with zeocore typed capabilities and OpenAI tool calls.
- [Open `ITAM-Agentic-ERP-02-replanning-critique-and-scoped-coordination.ipynb` in Colab](https://colab.research.google.com/github/profrodai/profrodai-resources/blob/main/courses/zeo-itam-autumn-2026/labs/11-agentic-erp-planning-2026-11-17/ITAM-Agentic-ERP-02-replanning-critique-and-scoped-coordination.ipynb): replanning, planner-critic checks and scoped coordination.

## Two ways to run them

- **Live (the class path).** Connect your own OpenAI API key in the connection cell. Every planning call is live and is charged to your OpenAI account. A ChatGPT subscription is not an API key. Never paste a key into a saved cell.
- **Test double (no key, no cost).** Set `USE_TEST_DOUBLE = True` in the cell before the harness. A scripted, rule-based stand-in answers each model call so the whole notebook runs offline. **It is not a language model** and shows nothing about model behaviour. It writes a file named `...-test-double.json` marked `mode: test-double`; do not hand that in as live evidence.

The test-double path was run top to bottom on Python 3.12 before this was published. The live path, with a real OpenAI key, was not run by an agent.

Like 05, these notebooks are not part of `make verify`.
