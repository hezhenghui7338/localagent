# LA / la bash tab completion — 由 LA complete-init 生成，也可手动 source

if [[ $- == *i* ]]; then
  _la_completion() {
    local cur prev words cword
    _init_completion || return
    local cmd="${COMP_WORDS[0]:-LA}"
    local -a suggestions
    mapfile -t suggestions < <("$cmd" complete -- "${COMP_WORDS[@]}" 2>/dev/null)
    if ((${#suggestions[@]} == 1)) && [[ ${suggestions[0]} == __LA_FILE__ ]]; then
      compopt -o filenames
      COMPREPLY=()
      _filedir
      return
    fi
    if ((${#suggestions[@]})); then
      COMPREPLY=("${suggestions[@]}")
    fi
  }

  complete -o default -F _la_completion LA la 2>/dev/null
fi
