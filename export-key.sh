# Source this file in Termux: . "$HOME/interaction-harness/export-key.sh"
# Never pass the key as an argument or place it in shell history.
_harness_saved_trace=
case $- in *x*) set +x; _harness_saved_trace=1 ;; esac
_harness_entered_key=$(python -B -c 'import getpass; print(getpass.getpass("OpenAI API key: "))') || return 1
if [ -z "$_harness_entered_key" ]; then
    unset _harness_entered_key
    return 1
fi
export OPENAI_API_KEY="$_harness_entered_key"
unset _harness_entered_key
python -B "$HOME/interaction-harness/save_key.py"
if [ "$_harness_saved_trace" = 1 ]; then
    unset _harness_saved_trace
    set -x
else
    unset _harness_saved_trace
fi
