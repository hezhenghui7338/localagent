# LA / la zsh tab completion — 由 LA complete-init 生成，也可手动 source

if [[ -o interactive ]]; then
  autoload -Uz compinit
  compinit -C
  autoload -Uz compdef

  _la() {
    local -a suggestions
    local cmd="${words[1]:-LA}"
    if ! command -v "$cmd" >/dev/null 2>&1; then
      cmd=la
      command -v "$cmd" >/dev/null 2>&1 || return
    fi
    suggestions=("${(@f)$("$cmd" complete -- "${words[@]}" 2>/dev/null)}")
    if (( ${#suggestions} == 1 )) && [[ ${suggestions[1]} == __LA_FILE__ ]]; then
      _files
      return
    fi
    if (( ${#suggestions} )); then
      compadd -a suggestions
    fi
  }

  compdef _la LA la
fi
