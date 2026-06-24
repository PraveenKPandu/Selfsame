# README demo GIF for Selfsame.
# Record with:
#   bash demo/setup.sh
#   vhs demo/selfsame.tape
# Produces assets/selfsame-demo.gif

Output assets/selfsame-demo.gif

Set Shell zsh
Set FontSize 21
Set Width 1240
Set Height 720
Set Padding 24
Set Theme "Dracula"
Set TypingSpeed 55ms

# Off-camera: enable `#` comments, put `selfsame` on PATH, enter the demo dir.
Hide
Type 'setopt interactivecomments' Enter
Type 'export PATH=$HOME/Library/Python/3.9/bin:$PATH' Enter
Type 'cd /tmp/selfsame-demo && clear' Enter
Show

Sleep 800ms
Type "# My AI agent just shipped a 'harmless' refactor. Run the tests:" Enter Sleep 1.2s
Type "pytest -q" Enter Sleep 2.5s

Type "# Green. So we're good... right?" Enter Sleep 1.8s

Type "# Did the BEHAVIOR actually change vs the build I trusted?" Enter Sleep 900ms
Type "selfsame drift" Enter Sleep 4s

Sleep 4s
