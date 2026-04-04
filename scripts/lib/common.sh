#!/usr/bin/env bash

automation_current_user() {
  if [[ -n "${USER:-}" ]]; then
    printf '%s\n' "$USER"
    return 0
  fi

  id -un
}

automation_prepend_path() {
  local dir

  for dir in "$@"; do
    [[ -d "$dir" ]] || continue
    case ":${PATH:-}:" in
      *":$dir:"*) ;;
      *) PATH="$dir:${PATH:-/usr/bin:/bin}" ;;
    esac
  done

  export PATH
}

automation_setup_path() {
  PATH="${PATH:-/usr/bin:/bin}"
  automation_prepend_path \
    "$HOME/.local/bin" \
    /opt/homebrew/bin \
    /usr/local/bin \
    /usr/bin \
    /bin
}
