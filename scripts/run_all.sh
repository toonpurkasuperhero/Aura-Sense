#!/usr/bin/env bash
# Start everything for the demo: Ollama (Gemma 4), backend + web UI, simulator.
#   ./scripts/run_all.sh            # with simulated sensor nodes
#   ./scripts/run_all.sh --no-sim   # real ESP32 hardware only
#   ./scripts/run_all.sh stop       # stop everything started by this script
set -u
cd "$(dirname "$0")/.."
ROOT=$(pwd)
PY="$ROOT/.venv/bin/python"
OLLAMA_BIN="${OLLAMA_BIN:-$(command -v ollama || echo "$HOME/.local/ollama/bin/ollama")}"
LOGS="$ROOT/data/logs"; mkdir -p "$LOGS"

stop() {
  for p in backend simulator dashboard; do  # 'dashboard' = legacy pid file
    [ -f "$LOGS/$p.pid" ] && kill "$(cat "$LOGS/$p.pid")" 2>/dev/null && echo "stopped $p"
    rm -f "$LOGS/$p.pid"
  done
}
if [ "${1:-}" = "stop" ]; then stop; exit 0; fi
stop >/dev/null 2>&1

if ! curl -s http://127.0.0.1:11434/api/version >/dev/null; then
  echo "starting ollama ($OLLAMA_BIN)"
  OLLAMA_KEEP_ALIVE=2h nohup "$OLLAMA_BIN" serve > "$LOGS/ollama.log" 2>&1 &
  for i in $(seq 1 30); do curl -s http://127.0.0.1:11434/api/version >/dev/null && break; sleep 1; done
fi
"$OLLAMA_BIN" list | grep -q "gemma4:e4b" || "$OLLAMA_BIN" pull gemma4:e4b

nohup "$ROOT/.venv/bin/uvicorn" backend.main:app --host 0.0.0.0 --port 8000 --no-access-log > "$LOGS/backend.log" 2>&1 &
echo $! > "$LOGS/backend.pid"
for i in $(seq 1 30); do curl -s http://127.0.0.1:8000/api/health >/dev/null && break; sleep 1; done
echo "backend   http://$(hostname -I | awk '{print $1}'):8000  (ESP32 posts here)"

if [ "${1:-}" != "--no-sim" ]; then
  nohup "$PY" simulator/mock_esp32.py > "$LOGS/simulator.log" 2>&1 &
  echo $! > "$LOGS/simulator.pid"
  echo "simulator running (motor_01, fan_02, pump_03)"
fi

echo "control room UI  http://localhost:8000/   (phones on the same Wi-Fi: http://$(hostname -I | awk '{print $1}'):8000/)"
echo "logs in $LOGS ; stop with ./scripts/run_all.sh stop"
