" Simple helper commands for invoking HybridAgent from Vim/Neovim.
"
" Usage:
"   :HybridAgentSolve Return ONLY a unified diff that updates hello.py.
"   :HybridAgentApply
"
if !exists(':HybridAgentSolve')
  command! -nargs=+ HybridAgentSolve execute '!bash scripts/ha.sh solve --prompt ' . shellescape(<q-args>)
endif

if !exists(':HybridAgentApply')
  command! -nargs=0 HybridAgentApply execute '!bash scripts/ha.sh apply'
endif
