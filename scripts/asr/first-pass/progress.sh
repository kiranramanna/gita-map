#!/bin/bash
# Emit one progress summary line per interval; exit when no ASR process remains.
D=/tmp/claude-13011/-kiran-home-projects-kr-git-gita-map/0adb5b3d-7734-4628-a3df-7d1b652f7d03/scratchpad/podcast-eval/asr/full
L=$(date -d "$(cat $D/launch.txt)" +%s)
while true; do
  now=$(date +%s); el=$((now-L)); line="t+${el}s"
  for i in $(seq 0 9); do
    st=$(python3 -I -c "import json;print(json.load(open('$D/chunks.json'))['chunks'][$i]['start'])")
    du=$(python3 -I -c "import json;print(json.load(open('$D/chunks.json'))['chunks'][$i]['dur'])")
    last=$(grep '^\[' $D/chunk-$i.stderr | tail -1 | sed -E 's/^\[ *[0-9.]+- *([0-9.]+)\].*/\1/')
    if [ -f $D/chunk-$i.json ]; then line="$line c$i:DONE";
    elif grep -qE 'Traceback|Error|Killed' $D/chunk-$i.stderr; then line="$line c$i:ERROR";
    elif [ -n "$last" ]; then line="$line c$i:$(python3 -I -c "p=($last-$st)/$du; print(f'{p*100:.0f}%,proj{($el/p)/60 if p>0 else 0:.0f}m')")";
    else line="$line c$i:0"; fi
  done
  echo "$line"
  n=$(pgrep -fc 'scripts/asr.py')
  [ "$n" = "0" ] && { echo "ALL ASR PROCESSES EXITED"; exit 0; }
  sleep 120
done
