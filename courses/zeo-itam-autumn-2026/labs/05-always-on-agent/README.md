# 05 · Build Lucy's always-on agent (class notebook, 15 October 2026)

The notebook for the ITAM class of 15 October 2026. You build one agent for Lucy's ice-cream shop, one decision at a time, from chapters 1 to 7, 14 and 15 of the exercises book, plus FastMCP and Jev. Each section starts with the way the agent goes wrong and then fixes it in code.

## Open it in Colab

[Open `lucy_always_on_agent.ipynb` in Colab](https://colab.research.google.com/github/profrodai/profrodai-resources/blob/main/courses/zeo-itam-autumn-2026/labs/05-always-on-agent/lucy_always_on_agent.ipynb), choose Runtime > Change runtime type > T4 GPU, and run the cells from the top. The first cell installs three packages (pydantic 2.13.4, fastmcp 4.1.0, typesafe-sdk 0.7.5) and fetches this repository at a pinned commit for the book's runtime. It does not reinstall Colab's own torch, transformers or sentence-transformers.

## What runs live, and what needs a key

- Live in your session, no key: the all-MiniLM-L6-v2 vectors (section 5) and Qwen2.5-1.5B-Instruct on the hostile bulletin (section 8). The first run downloads the models. Each live run prints its device and its seconds.
- Needs your own key, added as a Colab Secret with notebook access on: `TYPESAFE_API_KEY` for Jev (sections 9 and 10) and `ANTHROPIC_API_KEY` for the Claude comparison (cell 8.3d). Without the secret the cell prints one line saying so and stops. Nothing is replayed in its place. Never paste a key into a cell.
- Recorded or scripted, and labelled as such on the cell's first printed line: the model replies in sections 0 to 3 are text we wrote, the ten Qwen requests per run in section 8 were recorded earlier on one laptop, and the Laya answers in section 9 were recorded earlier.

Status: the authors have not yet run this exact notebook top to bottom in Colab. Tell us which cell fails.

## Files

- `lucy_always_on_agent.py`: the source, a jupytext `py:percent` file (cells start with `# %%`, markdown cells with `# %% [markdown]`).
- `lucy_always_on_agent.ipynb`: generated from the source with zeocore's `script_to_notebook()` (outputs stripped). Edit the `.py`, never the `.ipynb`.

The text of this notebook went through a writing review by an independent reviewer on 2026-10-15 (extract sha256 `3f5762076ed3c7d37881d45ca09ff341bf8f35d93ce11741fc162b7751d588a5`).
