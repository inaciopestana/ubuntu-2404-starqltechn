#!/usr/bin/env bash
# scan-privacy.sh - look for personal data and secrets in a directory tree
# before it is committed or attached to an issue. Exit status 1 if anything
# suspicious is found. Matches are printed MASKED (value replaced by ***).
#
#   tools/scan-privacy.sh [DIR]             # default: current directory
#   S9_PRIVACY_TERMS=~/.s9-privacy-terms tools/scan-privacy.sh
#
# S9_PRIVACY_TERMS: optional file with one extra extended-regex per line
# (your own user name, host names, e-mail, family names ...). Keep that file
# OUTSIDE the repository. A line containing "privacy-ok" is never reported.
set -u
DIR=${1:-.}
TERMS=${S9_PRIVACY_TERMS:-$HOME/.s9-privacy-terms}
hits=0

scan() {  # $1=label  $2=regex  [$3=regex of lines to ignore]
  local out
  out=$(grep -rInE --binary-files=without-match \
        --exclude-dir=.git --exclude-dir=node_modules --exclude=LICENSE --exclude=scan-privacy.sh \
        -e "$2" "$DIR" 2>/dev/null | grep -v 'privacy-ok' | grep -vE "${3:-^\$}" | head -40)
  [ -n "$out" ] || return 0
  hits=$((hits+1))
  echo "== $1"
  # mask everything after the match location is not possible portably; mask long tokens
  echo "$out" | cut -c1-220 | sed -E 's/([A-Za-z0-9+\/_=-]{24})[A-Za-z0-9+\/_=-]{8,}/\1***/g'
}

scan "private key material"        '-----BEGIN ([A-Z0-9 ]+ )?PRIVATE KEY-----|ssh-(rsa|ed25519) AAAA'
scan "tokens / API keys"           'gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}|xox[abp]-[0-9A-Za-z-]{10,}'
scan "password / psk assignments"  '(^|[^A-Za-z_])(psk|wpa-psk|password|passwd|senha|secret|api[_-]?key|token)[A-Za-z_]*[[:space:]]*[=:][[:space:]]*["'"'"']?[^[:space:]"'"'"'$<{(*][^[:space:]"'"'"']{3,}' '^[^:]*:[0-9]+:[[:space:]]*def [A-Za-z_]+\('
scan "private IPv4 addresses"      '(^|[^0-9.])(192\.168|10\.[0-9]{1,3}|172\.(1[6-9]|2[0-9]|3[01]))\.[0-9]{1,3}\.[0-9]{1,3}([^0-9]|$)' '172\.16\.42\.1|192\.168\.49\.1'   # USB-RNDIS gadget and Wi-Fi Direct group defaults, not personal
scan "MAC addresses"               '([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}' '00:00:00:00:00:00|ff:ff:ff:ff:ff:ff'
scan "IMEI-like / serial numbers"  '(imei|serial|ro\.serialno|androidboot\.serialno)[^A-Za-z0-9]{0,4}[0-9A-Za-z]{10,}'
# upstream copyright/authorship headers legitimately carry e-mail addresses
scan "e-mail addresses"            '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.(com|net|org|br|io|dev)([^A-Za-z0-9]|$)' '[Cc]opyright|[Aa]uthored|[Aa]uthor:|[Mm]aintainer|Signed-off|Co-authored|noreply@anthropic'
# grep -E has no look-ahead: do the home-path check separately
out=$(grep -rInE --binary-files=without-match --exclude-dir=.git -e '/home/[a-z][a-z0-9_-]*/' "$DIR" 2>/dev/null \
      | grep -vE '/home/(\$|<|\{|USER|user/|S9_)|privacy-ok' | head -40)
if [ -n "$out" ]; then hits=$((hits+1)); echo "== absolute /home/<name>/ paths"; echo "$out" | cut -c1-200; fi

if [ -r "$TERMS" ]; then
  while IFS= read -r t; do
    [ -n "$t" ] && case "$t" in \#*) ;; *) scan "your terms: ${t:0:2}***" "$t";; esac
  done < "$TERMS"
else
  echo "(note: no personal-terms file at $TERMS - add your own user name etc. there)" >&2
fi

# forbidden file types
bad=$(find "$DIR" -path "$DIR/.git" -prune -o -type f \( -name '*.img' -o -name '*.mbn' -o -name '*.nmconnection' \
      -o -name 'id_rsa*' -o -name '*.pem' -o -name '*.key' -o -name '*.log' -o -name '*.bak*' -o -name '*.pre-*' \) -print | head -20)
if [ -n "$bad" ]; then hits=$((hits+1)); echo "== files that must not be committed"; echo "$bad"; fi

large=$(find "$DIR" -path "$DIR/.git" -prune -o -type f -size +2M -print | head -10)
if [ -n "$large" ]; then hits=$((hits+1)); echo "== files larger than 2 MB (binary blobs?)"; echo "$large"; fi

if [ "$hits" -eq 0 ]; then echo "scan-privacy: nothing suspicious found in $DIR"; exit 0; fi
echo "scan-privacy: $hits category(ies) with findings - review before committing"; exit 1
