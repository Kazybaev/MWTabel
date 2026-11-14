#!/usr/bin/env bash
set -euo pipefail
umask 077
secret_dir=/root/mwtabel-private/agrarian-dify-20261114
mkdir -p "$secret_dir"
if [[ ! -r /dev/tty ]]; then
  printf 'Нужен интерактивный терминал для скрытого ввода.\n' >&2
  exit 1
fi
IFS= read -r -s -p 'Dify Console access_token: ' access_token </dev/tty
printf '\n' >/dev/tty
IFS= read -r -s -p 'Dify Console csrf_token cookie: ' csrf_token </dev/tty
printf '\n' >/dev/tty
if [[ -z "$access_token" || -z "$csrf_token" ]]; then
  printf 'Пустое значение; файлы не изменены.\n' >&2
  exit 1
fi
access_tmp=$(mktemp "$secret_dir/.access.XXXXXX")
csrf_tmp=$(mktemp "$secret_dir/.csrf.XXXXXX")
trap 'rm -f "$access_tmp" "$csrf_tmp"' EXIT
printf '%s' "$access_token" > "$access_tmp"
printf '%s' "$csrf_token" > "$csrf_tmp"
unset access_token csrf_token
chmod 600 "$access_tmp" "$csrf_tmp"
mv -f "$access_tmp" "$secret_dir/console-session.private"
mv -f "$csrf_tmp" "$secret_dir/console-csrf.private"
printf 'Console credentials сохранены с правами 0600; значения не выведены.\n'
