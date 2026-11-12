#!/data/data/com.termux/files/usr/bin/sh
# ============================================================================
# keeper.sh - keep the always-on lane service (agentd) running.
# Same shape as the other keepers on this phone (mcp_door_keeper.sh).
#
#   tick    (default) start the watch loop if it is not running - boot, the
#           15-minute phone timer, and `job add`
#   watch   look every ${AGD_SEC:-5}s; start the service when it is not
#           running; one loop per state folder (lock)
#   once    one look now
#   stop    stop the watch loop and the service; `tick` does nothing until `start`
#   start   allow it again, then tick
# State folder: $HARNESS_STATE_DIR, or this checkout's state/.
# ============================================================================
P=/data/data/com.termux/files/usr/bin
PATH="$P:$PATH"; export PATH
SELF=$(readlink -f "$0"); HERE=$(dirname "$SELF"); ROOT=$(dirname "$HERE")
STATE="${HARNESS_STATE_DIR:-$ROOT/state}"; DIR="$STATE/agentd"; mkdir -p "$DIR"
LOG="$DIR/keeper.log"; LOCK="$DIR/keeper.lock"; GUARD="$DIR/keeper.flock"; PIDF="$DIR/daemon.pid"; OFF="$DIR/STOPPED"
PY="${AGD_PYTHON:-$P/python}"
log(){ printf '[%s] %s\n' "$(date '+%F %T')" "$*" >>"$LOG"; }
cmd_of(){ { tr '\0' ' ' <"/proc/$1/cmdline"; } 2>/dev/null; }
daemon_alive(){ p=$(cat "$PIDF" 2>/dev/null); [ -n "$p" ] && cmd_of "$p" | grep -q 'agentd _daemon'; }
loop_alive(){ p=$(cat "$LOCK/pid" 2>/dev/null); [ -n "$p" ] && cmd_of "$p" | grep -q 'agentd/keeper.sh watch'; }

once(){
  [ -f "$OFF" ] && return 0
  daemon_alive && return 0
  "$P/termux-wake-lock" 2>/dev/null
  setsid "$PY" -B "$ROOT/toolbox/bin/agentd" _daemon 9>&- </dev/null >>"$DIR/daemon.out" 2>&1 &
  log "service was not running - started"; }

case "${1:-tick}" in
  once)  once ;;
  watch)
    # This inode stays in place. The kernel releases it when this watcher exits.
    exec 9>>"$GUARD"
    flock -n 9 || exit 0
    # A keeper started before the flock upgrade can still be running.
    loop_alive && exit 0
    mkdir -p "$LOCK"
    echo $$ >"$LOCK/pid"
    cleanup(){ [ "$(cat "$LOCK/pid" 2>/dev/null)" = "$$" ] && rm -f "$LOCK/pid"; }
    trap cleanup EXIT
    trap 'exit 0' INT TERM
    log "watch loop up"
    while [ ! -f "$OFF" ]; do once; sleep "${AGD_SEC:-5}" 9>&-; done ;;
  tick)  [ -f "$OFF" ] && exit 0
         loop_alive || { setsid sh "$SELF" watch </dev/null >/dev/null 2>&1 & } ;;
  start) rm -f "$OFF"; exec sh "$SELF" tick ;;
  stop)
    : >"$OFF"
    p=$(cat "$LOCK/pid" 2>/dev/null); loop_alive && kill "$p" 2>/dev/null
    p=$(cat "$PIDF" 2>/dev/null); daemon_alive && kill "$p" 2>/dev/null
    log "stopped by hand" ;;
  *) echo "usage: keeper.sh tick|watch|once|start|stop" >&2; exit 2 ;;
esac
