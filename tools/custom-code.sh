#!/usr/bin/env bash
# custom-code.sh — report custom-authored vs vendored/generated LOC for a git repo.
#
# Policy: custom code must be <5% of counted LOC (see oss-catalog.yaml).
# Vendored/generated code = files under lib/, vendor/, upstream/, third_party/,
# node_modules/, .venv/, dist/, out/, generated names (*generated*, *.pb.*,
# package-lock.json, pnpm-lock.yaml, foundry.lock), lockfiles, license/notice files,
# docs (*.md), and pure config (json/toml/yaml/cfg/ini handled separately below).
#
# Usage: tools/custom-code.sh [repo-path] [--json]
# Exit 0 if custom <= 5%, exit 1 if over (so it can gate CI/builds).

set -euo pipefail
REPO="${1:-.}"
CAP="${CUSTOM_CODE_CAP:-5}"
JSON=0
[ "${2:-}" = "--json" ] && JSON=1

cd "$REPO"
command -v git >/dev/null || { echo "git required"; exit 2; }
git rev-parse --git-dir >/dev/null 2>&1 || { echo "not a git repo: $REPO"; exit 2; }

VENDORED_RE='(^|/)(lib|vendor|upstream|third_party|node_modules|\.venv|venv|dist|out|build|coverage|__pycache__|\.next|target|bin)/'
GENERATED_RE='(generated|\.pb\.|\.min\.|package-lock\.json|pnpm-lock\.yaml|yarn\.lock|foundry\.lock|Cargo\.lock|poetry\.lock|go\.sum|remappings\.txt|LICENSE|LICENCE|COPYING|NOTICE|CHANGELOG)'
DOC_RE='\.(md|txt|rst|pdf|png|jpe?g|gif|svg|webp|ico|woff2?|ttf|otf|mp4|webm|docx)$'
CONFIG_RE='\.(json|ya?ml|toml|ini|cfg|conf|env|example|gitmodules|gitignore|dockerignore|editorconfig|prettierrc.*|eslintrc.*|solhint.*)$'
FIXTURE_RE='(^|/)(test|tests|fixtures|testdata|snapshots|data|ddl|snapshot|snapshot-private)/|\.(test|spec|t|fixture)\.'

is_code() {
  case "$1" in
    *.sol|*.vy|*.ts|*.tsx|*.js|*.jsx|*.mjs|*.cjs|*.py|*.rs|*.go|*.java|*.c|*.cc|*.cpp|*.h|*.hpp|*.rb|*.sh|*.sql|*.css|*.html|*.svelte|*.vue|*.php|*.swift|*.kt) return 0 ;;
  esac
  return 1
}

total=0; custom=0; vendored=0; excluded=0
declare -A custom_files

while IFS= read -r f; do
  [ -f "$f" ] || continue
  if echo "$f" | grep -qE "$VENDORED_RE|$GENERATED_RE|$DOC_RE|$CONFIG_RE|$FIXTURE_RE"; then
    # still count vendored code LOC toward the denominator for honesty
    if is_code "$f"; then
      n=$(wc -l < "$f" 2>/dev/null || echo 0)
      vendored=$((vendored + n)); total=$((total + n))
    else
      excluded=$((excluded + 1))
    fi
    continue
  fi
  is_code "$f" || { excluded=$((excluded + 1)); continue; }
  n=$(wc -l < "$f" 2>/dev/null || echo 0)
  custom=$((custom + n)); total=$((total + n))
  custom_files["$f"]=$n
done < <(git ls-files)

if [ "$total" -eq 0 ]; then pct=0; else pct=$(awk "BEGIN{printf \"%.2f\", ($custom/$total)*100}"); fi

if [ "$JSON" = 1 ]; then
  echo "{\"repo\":\"$REPO\",\"total_code_loc\":$total,\"custom_loc\":$custom,\"vendored_loc\":$vendored,\"custom_pct\":$pct,\"cap\":$CAP}"
else
  echo "repo:          $REPO"
  echo "counted LOC:   $total  (custom: $custom, vendored/generated: $vendored, non-code files skipped: $excluded)"
  echo "custom ratio:  ${pct}%  (cap: ${CAP}%)"
  echo "custom files:"
  for f in "${!custom_files[@]}"; do printf "  %8d  %s\n" "${custom_files[$f]}" "$f"; done | sort -rn | head -30
fi

awk "BEGIN{exit ($pct <= $CAP) ? 0 : 1}"
