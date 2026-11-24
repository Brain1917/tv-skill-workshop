#!/bin/sh
# Run from the repository root. Only reviewed installer files from the commit are eligible.
set -eu
if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
    echo 'Usage: sh tools/build-release.sh OUTPUT.zip [COMMIT]' >&2
    exit 2
fi
out=$1
revision=$(git rev-parse --verify "${2:-HEAD}^{commit}")
git archive --format=zip --prefix=TV-Workshop/ --output="$out" "$revision" -- \
    README.md 'Начать здесь.md' \
    .opencode/skills/tv-workshop/SKILL.md \
    .opencode/skills/tv-workshop/references/practice.md \
    .opencode/skills/tv-workshop/references/clear-russian.md \
    .opencode/skills/tv-skill-builder/SKILL.md \
    .opencode/skills/tv-skill-builder/references/native-pack.md \
    .opencode/skills/tv-skill-builder/scripts/pack_skill.py
