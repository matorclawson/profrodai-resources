# Lab 10, new version

**En español, en pocas palabras.** El laboratorio 10 ahora se hace en un Codespace, no en Colab. El bot sigue funcionando y muestra en pantalla todo lo que hace. Abre el enlace de abajo, guarda tu token como secreto y sigue el README de la carpeta `codespaces`. Los nombres de los helados funcionan en español: `/stock vainilla`.

## What changed

The Telegram lab from 3 November now runs in a Codespace. The lesson is the same: a customer asks how much ice cream is left, and only Lucy can ask how much to restock. The steps, the words and the checkpoints are the same. What changed is where the bot runs.

**Why.** In Colab the bot ran as a background thread, and Colab stops it. When it stopped, nothing on the page said so. In a Codespace the bot runs in the terminal, and everything it does is printed there: each message, each answer, and each problem it retries.

Two small changes in the bot: the flavor names also work in Spanish and ignore capitals and accents (`/stock vainilla`, `/stock Fresa`), and `/start` or any first message gets one line on how to use it.

## Open it

- **Lab 10, Telegram bot in a Codespace.** [Open it](https://codespaces.new/profrodai/profrodai-resources?devcontainer_path=.devcontainer/itam-lucy-telegram/devcontainer.json) and follow the README in the `codespaces` folder.
- **Lab 10, Lucy’s shop on Rasa Mantle** (only if your instructor tells you to; it needs three keys that your instructor sets up). [Open it](https://codespaces.new/profrodai/profrodai-resources?devcontainer_path=.devcontainer/itam-lucy-mantle/devcontainer.json) and follow the README in the `mantle-alternative` folder.

## Give the Codespace your token (Telegram lab)

1. In Telegram, BotFather gave you a token when you made your bot (step 03). If you lost it, send BotFather `/token` and choose your bot.
2. Open github.com/settings/codespaces. Under Secrets, choose New secret. Name it `TELEGRAM_BOT_TOKEN`, paste the token, and under Repository access select `profrodai/profrodai-resources`. Save.
3. Then open the Codespace with the link above. If you opened it first, stop it and open it again.
4. If you would rather not save it, open the terminal and type `source set_token.sh`, then paste the token into the hidden prompt. It works only in that terminal.

Keep your token private. It is a password for your bot. Do not paste it into a chat, a document or a screenshot. If it leaks, send `/revoke` to BotFather and use the new one.

## Your bot from before

If you already made a bot, you can reuse it and its token. Messages you sent to it earlier are not answered; send new ones.
