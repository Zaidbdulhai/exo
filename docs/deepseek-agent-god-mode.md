# DeepSeek "God Mode" Agent Setup with Open Interpreter

This guide explains how to connect [Open Interpreter](https://github.com/OpenInterpreter/open-interpreter) to a **DeepSeek** model via [OpenRouter](https://openrouter.ai) and enable fully autonomous ("God Mode") operation using the `-y` flag.

You can also point Open Interpreter at your local **exo** cluster instead of OpenRouter — exo exposes an OpenAI-compatible API, so the same approach works for any DeepSeek model you are running locally across your devices.

---

## Prerequisites

| Requirement | Details |
|---|---|
| Python ≥ 3.10 | `python --version` |
| pip / uv | Package manager |
| OpenRouter account | [openrouter.ai](https://openrouter.ai) — load at least $5 credit |
| (optional) exo running locally | `uv run exo` – see main README |

---

## 1. Install Open Interpreter

```bash
pip install open-interpreter
```

Or with `uv` (recommended if you already use it for exo):

```bash
uv pip install open-interpreter
```

---

## 2. Get your OpenRouter API key

1. Sign up at <https://openrouter.ai>.
2. Go to **Account → Keys** and click **Create Key**.
3. Copy the key — it starts with `sk-or-v1-…`.

---

## 3. Run the agent in God Mode

### Option A – DeepSeek via OpenRouter (cloud)

```bash
export OPENROUTER_API_KEY="sk-or-v1-YOUR_KEY_HERE"

interpreter \
  --api_key   "$OPENROUTER_API_KEY" \
  --api_base  "https://openrouter.ai/api/v1" \
  --model     "openrouter/deepseek/deepseek-chat" \
  -y
```

| Flag | Meaning |
|---|---|
| `--api_base` | Redirect requests to OpenRouter instead of OpenAI |
| `--model` | The DeepSeek model to use (see §5 for all options) |
| `-y` | **God Mode** – auto-approve every code block without asking |

### Option B – DeepSeek via your local exo cluster

Start exo first (`uv run exo`), then:

```bash
interpreter \
  --api_key  "ignored"  \
  --api_base "http://localhost:52415/v1" \
  --model    "deepseek-ai/DeepSeek-V3-0324-4bit" \
  -y
```

exo serves an OpenAI-compatible endpoint at `http://localhost:52415/v1`, so Open Interpreter connects to it transparently.

---

## 4. Add a custom system prompt (recommended for autonomous work)

Create a file `~/.config/open-interpreter/system_prompt.txt`:

```
You are an elite autonomous engineering agent with full access to this machine.
You have permission to run any shell command, edit files, install packages,
start servers, and browse the web without asking for confirmation.

When you encounter an error:
1. Read the full error message and log files.
2. Form a hypothesis about the root cause.
3. Apply a fix and re-run — do NOT ask the user unless you are truly stuck.
4. Keep iterating until the task is complete.

Be decisive. Be thorough. Minimise interruptions.
```

Then load it:

```bash
interpreter \
  --api_key  "$OPENROUTER_API_KEY" \
  --api_base "https://openrouter.ai/api/v1" \
  --model    "openrouter/deepseek/deepseek-chat" \
  --system_message "$(cat ~/.config/open-interpreter/system_prompt.txt)" \
  -y
```

---

## 5. Available DeepSeek models on OpenRouter

| Model slug | Description | ~Cost per 1 M tokens |
|---|---|---|
| `openrouter/deepseek/deepseek-chat` | DeepSeek V3 – fast, very capable | $0.27 input / $1.10 output |
| `openrouter/deepseek/deepseek-r1` | DeepSeek R1 – chain-of-thought reasoning | $0.55 input / $2.19 output |
| `openrouter/deepseek/deepseek-coder` | DeepSeek Coder – optimised for code | $0.14 input / $0.28 output |

Check the current prices at <https://openrouter.ai/models?q=deepseek>.

> **Budget tip:** `deepseek-chat` (DeepSeek V3) offers near-GPT-4o quality at roughly 10× lower cost.  
> $5 of credit easily covers several hours of autonomous agent work.

---

## 6. Use the automated setup script

A convenience script is provided at `scripts/setup_deepseek_agent.sh`.  
It installs Open Interpreter, writes the system prompt, and generates a ready-to-run launcher:

```bash
bash scripts/setup_deepseek_agent.sh
```

Follow the on-screen prompts to enter your OpenRouter API key.

---

## 7. Safety considerations

`-y` (God Mode) means the agent **will execute every command it generates without asking you first**.

- Keep a terminal open so you can press **Ctrl+C** at any time to stop the agent.
- For sensitive workloads, consider running inside a **Docker container** or **WSL 2** sandbox to limit the blast radius of accidental destructive commands.
- Review the agent's plan before starting long-running autonomous sessions.
- Never pass secrets (SSH keys, database passwords) as plain text in your prompt — the model context may be stored by the API provider.

---

## 8. Putting it all together – example session

```bash
export OPENROUTER_API_KEY="sk-or-v1-YOUR_KEY"

interpreter \
  --api_key  "$OPENROUTER_API_KEY" \
  --api_base "https://openrouter.ai/api/v1" \
  --model    "openrouter/deepseek/deepseek-chat" \
  --system_message "You are an autonomous agent. Fix errors yourself without asking." \
  -y
```

Then type your task, for example:

```
Create a Python Flask REST API with /health and /echo endpoints,
write unit tests with pytest, and make sure all tests pass.
```

The agent will write the code, install dependencies, run the tests, fix any failures, and report back — fully hands-free.

---

## Related resources

- [Open Interpreter documentation](https://docs.openinterpreter.com)
- [OpenRouter model list](https://openrouter.ai/models)
- [DeepSeek model page](https://openrouter.ai/models?q=deepseek)
- [exo API reference](api.md)
