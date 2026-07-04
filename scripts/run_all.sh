#!/bin/bash
# Cross-platform-friendly wrapper. Prefer: python scripts/run_all.py
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VAULT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$VAULT"

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "❌ 未找到 Python。请先安装 Python 3。"
  exit 1
fi

echo "=================================================="
echo "   🧠 知识蒸馏系统 - 全功能运行"
echo "   wrapper: run_all.sh → run_all.py"
echo "=================================================="
echo "Python: $PYTHON_BIN"
echo "Vault:  $VAULT"
echo ""

exec "$PYTHON_BIN" "$SCRIPT_DIR/run_all.py" "$@"
