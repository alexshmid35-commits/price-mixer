#!/bin/zsh
cd "/Users/alexeyvoronkov/Desktop/Сводный прайс парсер OnlinerID/Price_List _localHost"
while true; do
  /opt/homebrew/bin/python3 app.py >> app.log 2>&1
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] server exited, restarting in 2s" >> app.log
  sleep 2
done
