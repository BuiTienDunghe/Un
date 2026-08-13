# Discord Bot Control Panel

## Purpose

`Discord Bot Control` gives the Windows operator one explicit switch for the
production Discord bot. It replaces ad-hoc detached commands with three
unambiguous actions:

```text
Start   turn the bot on
End     turn the bot off and terminally cancel open turns
Update  reload the local backend source, then restart the bot
Close   perform End, then close the Control Panel
```

The controller manages these two host processes only:

```text
.venv\Scripts\python.exe -m discord_bot.main
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

It never restarts PostgreSQL, Redis, Qdrant, Ollama, Docker, or workers.
It always starts the bot with:

```text
DISCORD_PERSISTENT_SESSIONS_ENABLED=true
LOCAL_AGENT_BASE_URL=http://127.0.0.1:8000
DISCORD_TURN_EXECUTE_TIMEOUT_SECONDS=180
```

## First-Time Configuration

1. In Discord, enable **User Settings → Advanced → Developer Mode**.
2. Right-click the text or announcement channel used for bot status.
3. Select **Copy Channel ID**.
4. Double-click:

   ```text
   discord-bot-control.bat
   ```

5. Paste the channel ID into **Status channel ID**.
6. Select **Save**.

The bot must have `View Channel` and `Send Messages` permission in that
channel. The channel ID is stored in:

```text
data/discord_bot_control/settings.json
```

This runtime directory is gitignored. `DISCORD_TOKEN` is read from `.env`; the
panel never displays or copies it into its settings or logs.

As an alternative to the UI setting, `.env` can contain:

```text
DISCORD_STATUS_CHANNEL_ID=<channel-id>
DISCORD_CONTROL_BACKEND_URL=http://127.0.0.1:8000
```

Do not commit the real `.env`.

## Start Bot

Select **Start Bot**.

The controller performs:

```text
validate channel ID
-> check that no host or Docker bot instance is running
-> check backend GET /health and the required live OpenAPI route
-> reload only the host Uvicorn API when its live source is stale/unavailable
-> terminally cancel queued/running turns left by an earlier bot run
-> validate Discord channel access
-> start the bot with persistent sessions enabled
-> wait for Discord Gateway connected
-> post "Ún tới chơi"
```

If the backend, token, channel permission, Gateway connection, or startup
announcement fails, Start reports an error. A newly launched bot is stopped
again when its startup announcement cannot be delivered, so the panel does not
show a false successful activation.

## End Bot

Select **End Bot**. End is immediate and does not leave an unfinished FIFO turn
for the next Start.

The controller performs:

```text
stop only the discord_bot.main process tree
-> terminally cancel every queued/running Discord turn
-> clear worker, lease, and heartbeat ownership
-> post "gút bai" through the bot account
-> clear the local controller state
```

If Discord is temporarily unavailable, the panel reports that the goodbye
announcement failed but still stops the bot. It does not delete Discord
sessions, turns, conversations, or memory data.

An interrupted turn is marked `cancelled`, not `completed`. `completed` is
reserved for a response that was delivered successfully to Discord. Both are
terminal states, so a cancelled turn is never queued for the next bot start.
Any response produced but not delivered before Stop is retained for audit but
is excluded from later Discord speaker history.

When the backend is healthy but its live OpenAPI is stale, End reloads only the
host Uvicorn process before terminal cancellation. If cancellation still
fails, the bot remains stopped and the panel reports the backend error.

## Update / Reload

This action reloads the backend and bot source already present in the
repository. It does not run `git pull`, install dependencies, apply a database
migration, start Docker, or download a model.

When the bot is running:

```text
post "Ún đang update"
-> stop the old bot process tree
-> reload only the host Uvicorn API
-> terminally cancel every queued/running turn
-> start the bot from the current source
-> wait for Gateway connected
-> post "Ún update xong"
```

When the bot is stopped, Update still reloads the backend before starting the
bot and posting the completion message.

## Timeout Policy

Ordinary resolver, enqueue, delivery, and health requests keep short timeouts.
The endpoint that performs model inference uses a separate default:

```text
DISCORD_BACKEND_TIMEOUT_SECONDS=45
DISCORD_TURN_EXECUTE_TIMEOUT_SECONDS=180
OLLAMA_CHAT_TIMEOUT_SECONDS=120
```

The Discord execute timeout is intentionally longer than the Ollama chat
timeout. This prevents the bot from abandoning a valid response merely because
the local model needs more than 45 seconds.

## Status and Logs

The panel shows:

- backend health;
- bot Running/Stopped state;
- duplicate host/Docker instance detection;
- Discord Gateway connection;
- persistent-session flag;
- current process PIDs.

Select **Open Logs** to open:

```text
data/discord_bot_control/
```

Files include:

```text
bot.stdout.log
bot.stderr.log
control.log
state.json
settings.json
```

No Discord token or full backend credential is written to these files.

## Closing the Panel

Closing the window is always equivalent to **End Bot**:

```text
request cancellation of any in-progress Start/Update
-> stop the bot process tree
-> terminally cancel queued/running turns
-> send "gút bai" when the bot was running
-> close the Control Panel
```

There is no option to leave the bot running after the panel closes. Network
and process checks run outside the Tkinter UI thread. A close watchdog
terminates the local bot and closes the panel if an external operation does
not return in time.

Only one logical Control Panel instance is allowed. Windows may display a
virtual-environment launcher process plus its Python child; those two PIDs are
one panel, not two independent panels.

## Safety and Limitations

- Start never creates a second host bot process.
- A running Docker `discord-bot` container is detected and left unmanaged; stop
  that container before using the host controller.
- Status messages are authored by the bot account, so the bot's own
  `on_message` guard ignores them and they do not create FIFO turns.
- Controlled Stop/Update uses terminal cancellation. It intentionally abandons
  unfinished questions rather than resuming them after the next Start.
- A forced process kill, machine power loss, network outage, or crash cannot
  guarantee delivery of `gút bai`. The guarantee applies to controlled Stop
  through this panel while Discord is reachable.
- Keep `run-discord-bot.bat` closed while using this controller; that legacy
  launcher starts the Docker profile and is a separate operating mode.
