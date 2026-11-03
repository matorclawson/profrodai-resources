# Build Lucy’s shop bot on your phone, in a Codespace

**Your goal.** A customer can ask how much ice cream is left. Only Lucy can ask how much to restock. Watch it work, then build your own.

This is the same lesson as the Colab notebook, with one change: the bot is a program that runs in the terminal of a Codespace, and its log is on the screen the whole time. Every message it answers and every problem it meets is printed there.

[Open in a Codespace](https://codespaces.new/profrodai/profrodai-resources?devcontainer_path=.devcontainer/itam-lucy-telegram/devcontainer.json)

## Before you start

- The Telegram app on your phone (step 02).
- A GitHub account. A Codespace is a small computer in the cloud that opens in your browser.
- Your bot’s token, which you get in step 03. You give it to the Codespace in step 05, one of two ways: as a Codespaces secret named `TELEGRAM_BOT_TOKEN` (create it at github.com/settings/codespaces, tick this repository, then open the Codespace), or by typing it hidden into the terminal with `source set_token.sh`.

Run each step in the terminal at the bottom of the Codespace. The scripts are small. Open one in the editor before you run it and read it.

## 01 · Watch Lucy answer from her shelf

Rod projects the prepared demo bot’s chat. Anyone can watch before signing in. Ask “How many vanilla tubs does Lucy have?” Send `/stock vanilla`. Show the reply with 2 tubs. Change one number in `shop.py`, restart the demo bot, then send the identical message again. Ask someone to predict the second reply before revealing it.

**Checkpoint.** The phone now says 7 tubs. Where did that number come from?

## 02 · Open your two workspaces

Phone: open the official Telegram app from https://telegram.org/apps. If you are new, choose Start Messaging, select your country, enter your own phone number and follow Telegram’s verification and profile prompts privately. Stop when you see the chat list. If sign-in takes longer, pair with someone already signed in.

Laptop: open the Codespace with the button above. Wait until you see a terminal at the bottom. A terminal is a place to type one command and read the answer directly underneath.

**Checkpoint.** You see Telegram’s chat list and a terminal prompt in the Codespace.

## 03 · Register a new bot

Open the verified @BotFather chat: https://t.me/BotFather. BotFather is Telegram’s account for creating bots. Tap Start, send `/newbot`, then reply with a display name such as Lucy’s Shop. When it asks for a username, try a unique one such as lucy_itam_4821_bot. If taken, change the digits. Rod: hide your phone before BotFather issues the token.

**Checkpoint.** BotFather gives you a public t.me link to your new bot and a private token. Keep this chat private.

## 04 · Open your shop bot’s chat

Copy the username from the end of your bot’s public t.me link. Open `https://t.me/<that username>`, tap Start, then send `hello lucy` in this new chat. BotFather registers the account. Your shop bot receives customer messages. Switch between these two chats by checking the name at the top.

**Checkpoint.** Your message appears in the shop chat. Silence is expected until you write the reply code.

## 05 · Give the Codespace the private token

A token is a password that lets code act as this bot. Pause screen sharing. In the BotFather chat copy the token.

- If you made the `TELEGRAM_BOT_TOKEN` secret, it is already here.
- If not, run `source set_token.sh`, paste the token into the hidden prompt and press Enter. Resume sharing only after the prompt closes. The token lives in this terminal only. If you open a new terminal, run it again.

Each pair uses its own bot. If you accidentally share a token, use BotFather’s `/revoke` and load the replacement here.

**Checkpoint.** With the secret, run `echo "${TELEGRAM_BOT_TOKEN:+Token loaded}"`. It prints “Token loaded”. With `set_token.sh` the script says it. You will verify the token with Telegram next.

## 06 · Ask Telegram which bot you control

An API is a set of requests one program can make to another. Open `tg.py` and read the `api` function first. Your Python code asks Telegram a question called getMe. Telegram uses the token to decide which bot you mean and returns its public username. Run it with the username from step 04 and compare the printed @username:

```
python3 step06_getme.py your_bot_username
```

**Checkpoint.** Verified @your_bot. A 401 means Telegram rejected the token. Repeat step 05 and run this again.

## 07 · Read one message before answering it

Send `hello lucy` again in your shop chat, then run:

```
python3 step07_read.py
```

getUpdates asks Telegram for waiting messages. Look at the three lines it prints. The text tells you what was asked, the sender identifies who asked, and the chat tells you where the answer belongs. Hide the numeric IDs on the projector. If no matching message appears, confirm the username, resend the words and run again.

**Checkpoint.** Python prints “Received: hello lucy”. Look at your phone. Has anyone answered yet?

## 08 · Send the first reply yourself

Predict which chat will receive this message. Run `python3 step08_send.py` once and look at that chat on the phone. sendMessage takes two things you already understand: the destination and the words to send. Ask your partner what would happen if you edited only the words in `step08_send.py`. Try it.

**Checkpoint.** The exact words from Python appear as a new message from your shop bot.

## 09 · Teach Python to read the shelf

Lucy keeps stock in a Python dictionary in `shop.py`. Predict the answer for chocolate, then run `python3 step09_shelf.py`. Edit vanilla from 2 to 5 in `shop.py`, run it again, and explain why chocolate stays the same. Compare strawberry (a product with zero stock) with mango (absent). These checks run entirely inside the Codespace.

**Checkpoint.** The same function distinguishes an empty shelf from an unknown product.

## 10 · Connect the shelf to incoming commands

A command is ordinary chat text beginning with a slash. Send `/stock vanilla` to your bot and run:

```
python3 step10_answer_once.py
```

Trace one request with your finger: read the message, choose the product, look it up, send the result back. Change the shelf in step 09, send the command again and run this step again. If several classmates want to test, use one bot per pair.

**Checkpoint.** The phone displays your current vanilla count. Until the next step, each reply requires you to run the script.

## 11 · Keep answering while the program runs

Run the bot:

```
python3 bot.py
```

It prints “Listening” and stays on the screen. Send two different stock commands from your phone. Each one appears in the log with the answer sent. Ask your partner to open your public link, tap Start and test a third. A 409 in the log means another bot.py or a webhook is using this token. Stop the other one or create a fresh classroom bot. If the connection drops, the log says “Problem” and the bot tries again by itself.

**Checkpoint.** Different phone replies arrive without you running anything again, and the log shows each one. To stop, press Ctrl+C in the terminal.

## 12 · Give Lucy a permission customers lack

Lucy wants a proposal for enough vanilla to bring the stock up to 8 tubs. Before running, set vanilla to 2 in `shop.py`. Each pair should use a fresh bot whose link stayed private until its owner sent hello lucy in step 07. For extra certainty, get your own numeric ID: with the bot running, send `/whoami` privately. The bot reads Telegram’s sender field to check identity. A customer typing “I am Lucy” cannot choose that field.

**Checkpoint.** The owner has not yet been assigned. Both phones get “Owner only” for /restock vanilla.

## 13 · Try the same request from two phones

Stop the bot with Ctrl+C. Only the intended owner uses the number from their own `/whoami` reply. Start the bot again with that number, which the log never prints:

```
python3 bot.py --owner 123456789
```

Both partners now send /restock vanilla to the same bot from different Telegram accounts. Who gets a proposal? Did anything on the shelf change? Show your partner both replies, and the log lines that say “owner asked” and “customer asked”. If working alone, send it from your phone and have a classmate send the second one.

**Checkpoint.** With 2 tubs on the shelf, Lucy sees “Propose 6 tubs”. A customer sees “Owner only”. Stock stays at 2.

## 14 · Prove you can change the bot

Add a flavor by editing `STOCK` in `shop.py`, then stop and start the bot. Ask a partner to predict its reply, then try it from Telegram. Explain aloud how a phone message reached your dictionary and how the answer found its way back. As a final experiment, stop the bot with Ctrl+C and send another command. Compare the two outcomes.

**Checkpoint.** Your new product answers while the bot runs. After you stop it, a new request waits.

## 15 · Stop the bot and explain the silence

Press Ctrl+C. The log says “Stopped”. Send `/stock mango` again. Why did the earlier message get a reply while this one waits? Name the part that stopped.

**Checkpoint.** The log says “Stopped”, and the new request stays unanswered.

## If something goes wrong

- **“No bot token found.”** Add the secret, or run `source set_token.sh` in this terminal.
- **401.** Telegram rejected the token. Copy it again from BotFather.
- **409.** Two programs are reading the same bot. Stop one.
- **No reply and no log line.** The bot is not running, or you messaged a different bot. Check the name at the top of the chat.
- **Closing the browser tab.** The Codespace stops after a while and so does the bot. Open it again and run `python3 bot.py`.

## Files

- `tg.py`: the one function that talks to Telegram.
- `shop.py`: the shelf and the answers, no Telegram code.
- `step06_getme.py` to `step10_answer_once.py`: one script per step.
- `bot.py`: the bot that keeps answering.
- `test_lab.py`: offline tests with a fake Telegram. Run `python3 -m unittest test_lab`.

[Telegram apps](https://telegram.org/apps) · [Create a bot](https://core.telegram.org/bots/tutorial) · [Bot API methods](https://core.telegram.org/bots/api)
