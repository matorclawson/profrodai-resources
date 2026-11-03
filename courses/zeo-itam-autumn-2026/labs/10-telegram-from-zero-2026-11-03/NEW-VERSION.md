# Lab 10, new version

The Telegram lab from 3 November now has a Codespace version. The lesson is the same: a customer asks how much ice cream is left, and only Lucy can ask how much to restock. The steps, the words and the checkpoints are the same. What changed is where the bot runs.

**Why.** In the notebook the bot ran as a background thread. When it stopped, nothing on the page said so, and you could not tell whether the bot or Telegram had a problem. In the Codespace version the bot runs in the terminal, and everything it does is printed there: each message, each answer, and each problem it retries.

## Pick one

- **Telegram bot in a Codespace.** Start here if you want the same lab as before, with a visible log. You need your own bot token from BotFather. [Open it](https://codespaces.new/profrodai/profrodai-resources?devcontainer_path=.devcontainer/itam-lucy-telegram/devcontainer.json) and follow the README in the `codespaces` folder.
- **Lucy’s shop on Rasa Mantle.** The same idea, built in Rasa’s Inspector by typing or by voice. It needs three keys that your instructor sets up, so use it only if your instructor tells you to. [Open it](https://codespaces.new/profrodai/profrodai-resources?devcontainer_path=.devcontainer/itam-lucy-mantle/devcontainer.json) and follow the README in the `mantle-alternative` folder.

## What you do not need to redo

Your bot from BotFather still works. If you already have a bot and its token, reuse them in step 05.

## Keep your token private

The token is a password for your bot. Do not paste it into a chat, a document or a screenshot. If it leaks, send `/revoke` to BotFather and use the new one.
