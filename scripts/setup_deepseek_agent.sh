#!/usr/bin/env bash
#
# setup_deepseek_agent.sh
#
# Installs Open Interpreter and configures it to use DeepSeek via OpenRouter
# with full autonomous ("God Mode") operation enabled by the -y flag.
#
# Usage:
#   bash scripts/setup_deepseek_agent.sh
#
# After running this script a launcher is created at:
#   ~/run_deepseek_agent.sh
#
# Run it with:
#   bash ~/run_deepseek_agent.sh
#

set -euo pipefail

# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()    { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
section() { echo -e "\n${CYAN}=== $* ===${NC}"; }

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║   DeepSeek God Mode Agent Setup (via OpenRouter)     ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════╝${NC}"
echo ""

# ---------------------------------------------------------------------------
# 1. Check Python
# ---------------------------------------------------------------------------
section "Checking Python"
if ! command -v python3 &>/dev/null; then
    error "Python 3 is required but was not found."
    error "Install it from https://www.python.org/downloads/ and re-run this script."
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
info "Found Python ${PYTHON_VERSION}"

MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)
if [[ "$MAJOR" -lt 3 ]] || { [[ "$MAJOR" -eq 3 ]] && [[ "$MINOR" -lt 10 ]]; }; then
    error "Python 3.10 or newer is required (found ${PYTHON_VERSION})."
    exit 1
fi

# ---------------------------------------------------------------------------
# 2. Install Open Interpreter
# ---------------------------------------------------------------------------
section "Installing Open Interpreter"

INSTALL_CMD=""
if command -v uv &>/dev/null; then
    info "Using uv to install open-interpreter"
    INSTALL_CMD="uv pip install --quiet open-interpreter"
elif command -v pip3 &>/dev/null; then
    info "Using pip3 to install open-interpreter"
    INSTALL_CMD="pip3 install --quiet open-interpreter"
elif command -v pip &>/dev/null; then
    info "Using pip to install open-interpreter"
    INSTALL_CMD="pip install --quiet open-interpreter"
else
    error "No pip or uv found. Please install pip and re-run this script."
    exit 1
fi

eval "$INSTALL_CMD"
info "open-interpreter installed successfully"

# ---------------------------------------------------------------------------
# 3. Collect OpenRouter API key
# ---------------------------------------------------------------------------
section "OpenRouter API Key"

if [[ -n "${OPENROUTER_API_KEY:-}" ]]; then
    info "Found OPENROUTER_API_KEY in environment — skipping prompt"
    OPENROUTER_KEY="$OPENROUTER_API_KEY"
else
    echo ""
    echo "  Enter your OpenRouter API key."
    echo "  Get one at: https://openrouter.ai/keys"
    echo ""
    read -rsp "  API key (input hidden): " OPENROUTER_KEY
    echo ""
    if [[ -z "$OPENROUTER_KEY" ]]; then
        error "No API key provided. Aborting."
        exit 1
    fi
fi

# ---------------------------------------------------------------------------
# 4. Choose DeepSeek model
# ---------------------------------------------------------------------------
section "Select DeepSeek Model"

echo "  Available models:"
echo "    1) deepseek/deepseek-chat    – DeepSeek V3, fast, near-GPT-4o quality  (~\$0.27/1M input)"
echo "    2) deepseek/deepseek-r1      – DeepSeek R1, chain-of-thought reasoning (~\$0.55/1M input)"
echo "    3) deepseek/deepseek-coder   – DeepSeek Coder, optimised for code      (~\$0.14/1M input)"
echo ""
read -rp "  Enter choice [1-3, default=1]: " MODEL_CHOICE

case "${MODEL_CHOICE:-1}" in
    2) DEEPSEEK_MODEL="openrouter/deepseek/deepseek-r1"    ;;
    3) DEEPSEEK_MODEL="openrouter/deepseek/deepseek-coder"  ;;
    *) DEEPSEEK_MODEL="openrouter/deepseek/deepseek-chat"   ;;
esac

info "Selected model: ${DEEPSEEK_MODEL}"

# ---------------------------------------------------------------------------
# 5. Write system prompt
# ---------------------------------------------------------------------------
section "Creating System Prompt"

PROMPT_DIR="$HOME/.config/open-interpreter"
PROMPT_FILE="$PROMPT_DIR/deepseek_system_prompt.txt"

mkdir -p "$PROMPT_DIR"

cat > "$PROMPT_FILE" <<'PROMPT'
You are an elite autonomous engineering agent with full, unrestricted access to this machine.

You have permission to run any shell command, edit files, install packages,
start servers, and browse the web without asking for confirmation.

Operational rules:
1. When you encounter an error: read the full output, form a hypothesis,
   apply a fix, and re-run — iterate until the task is complete.
2. Never stop mid-task to ask for permission or clarification unless
   the situation is genuinely ambiguous and could cause irreversible harm.
3. Prefer minimal, targeted changes. Avoid destroying files or data
   unless explicitly instructed to do so.
4. Document what you do in brief inline comments so the user can follow along.
5. When the task is finished, print a concise summary of what was done.
PROMPT

info "System prompt written to ${PROMPT_FILE}"

# ---------------------------------------------------------------------------
# 6. Write the launcher script
# ---------------------------------------------------------------------------
section "Creating Launcher Script"

LAUNCHER="$HOME/run_deepseek_agent.sh"

cat > "$LAUNCHER" <<LAUNCHER
#!/usr/bin/env bash
#
# run_deepseek_agent.sh  –  DeepSeek God Mode Agent launcher
# Generated by setup_deepseek_agent.sh
#
# Usage:
#   bash ~/run_deepseek_agent.sh
#
# The agent will run fully autonomously (-y flag).
# Press Ctrl+C at any time to stop it.
#

set -euo pipefail

OPENROUTER_API_KEY="${OPENROUTER_KEY}"
DEEPSEEK_MODEL="${DEEPSEEK_MODEL}"
SYSTEM_PROMPT="\$(cat "\${HOME}/.config/open-interpreter/deepseek_system_prompt.txt")"

echo ""
echo "Starting DeepSeek God Mode Agent"
echo "  Model : \${DEEPSEEK_MODEL}"
echo "  Mode  : autonomous (-y)"
echo "  Press Ctrl+C to stop"
echo ""

interpreter \\
  --api_key       "\${OPENROUTER_API_KEY}" \\
  --api_base      "https://openrouter.ai/api/v1" \\
  --model         "\${DEEPSEEK_MODEL}" \\
  --system_message "\${SYSTEM_PROMPT}" \\
  -y
LAUNCHER

chmod +x "$LAUNCHER"
info "Launcher written to ${LAUNCHER}"

# ---------------------------------------------------------------------------
# 7. Done
# ---------------------------------------------------------------------------
section "Setup Complete"

echo ""
echo -e "${GREEN}Everything is ready!${NC}"
echo ""
echo "  Start the agent with:"
echo -e "    ${CYAN}bash ~/run_deepseek_agent.sh${NC}"
echo ""
echo "  Or run directly:"
echo ""
echo -e "    ${CYAN}interpreter \\${NC}"
echo -e "    ${CYAN}  --api_key  \"${OPENROUTER_KEY:0:12}…\" \\${NC}"
echo -e "    ${CYAN}  --api_base \"https://openrouter.ai/api/v1\" \\${NC}"
echo -e "    ${CYAN}  --model    \"${DEEPSEEK_MODEL}\" \\${NC}"
echo -e "    ${CYAN}  -y${NC}"
echo ""
warn "God Mode (-y) means the agent executes all commands without asking."
warn "Keep a terminal open so you can press Ctrl+C if needed."
echo ""
