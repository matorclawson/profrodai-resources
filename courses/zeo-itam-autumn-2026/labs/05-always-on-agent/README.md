# 05 · Build Lucy's always-on agent (class notebook, 15 October 2026)

The notebook for the ITAM class of **15 October 2026**: one agent for Lucy's ice-cream shop, built one decision at a time, from the exercises book's chapters 1 to 7, 14 and 15, plus FastMCP and Jev. Every output you see in class came from a real run of this code.

## Open it in Colab

[Open `lucy_always_on_agent.ipynb` in Colab](https://colab.research.google.com/github/profrodai/profrodai-resources/blob/main/courses/zeo-itam-autumn-2026/labs/05-always-on-agent/lucy_always_on_agent.ipynb), then run the cells from the top. The first cells install the packages (pydantic 2.13.4, fastmcp, typesafe-sdk, numpy) and fetch this repository for the book's runtime.

**No key is needed.** The Jev section replays a *recorded* run of the real Jev (model jev-1.13.0); the recording is embedded in the notebook, so the numbers are the same every time. A cell that replays a recording says so on its first printed line, and so does every cell whose model turn is scripted. If you want to call Jev live, add your own key as a Colab Secret named `TYPESAFE_API_KEY` and never paste a key into a cell.

Status: the setup cells have not been run inside Colab by the authors yet (they were tested as plain Python); tell us if anything fails.

## Files

- `lucy_always_on_agent.py`: the **source**, a jupytext `py:percent` file (cells start with `# %%`, markdown cells with `# %% [markdown]`).
- `lucy_always_on_agent.ipynb`: **generated** from the source with zeocore's `script_to_notebook()` (outputs stripped). Edit the `.py`, never the `.ipynb`.
