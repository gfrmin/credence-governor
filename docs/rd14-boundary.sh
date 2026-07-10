#!/usr/bin/env bash
# rd14-boundary.sh — the R-D14 freeze-boundary ceremony, AUTHOR-run.
#
# Applies rd14-boundary.patch (the five reviewed edits), runs the gates,
# re-signs MANIFEST.sha256 over the SAME file census, commits and tags with
# the AUTHOR key, and pushes. Every irreversible step asks first; abort at
# any prompt and `git -C ~/git/proplang checkout -- . ` restores the tree.
#
# Usage:  bash rd14-boundary.sh [path/to/rd14-boundary.patch]
#         (default: the patch sitting next to this script)

set -euo pipefail

REPO="${PROPLANG_DIR:-$HOME/git/proplang}"
PATCH="${1:-$(dirname "$(readlink -f "$0")")/rd14-boundary.patch}"
TAG="rd14-close"
AUTHOR_FPR="SHA256:Sfh8OBG9CtkTF/y8rch4Cf6wv1rCpJ8ymEtKilUucsY"

confirm() {
    local ans
    read -r -p "$1 [type yes to continue] " ans
    [ "$ans" = "yes" ] || { echo "aborted — nothing pushed."; exit 1; }
}

cd "$REPO"

echo "== 0. preconditions"
[ -f "$PATCH" ] || { echo "ERROR: patch not found: $PATCH"; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo "ERROR: tree not clean — commit/stash first"; exit 1; }
if git rev-parse --verify "refs/tags/$TAG" >/dev/null 2>&1; then
    echo "ERROR: tag $TAG already exists"; exit 1
fi
KEY=$(git config user.signingkey)
case "$KEY" in
    *proplang-builder*)
        echo "ERROR: signing key is the BUILDER key ($KEY)."
        echo "This boundary must be author-signed — run from the author shell."
        exit 1 ;;
esac
FPR=$(ssh-keygen -lf "$KEY" | awk '{print $2}')
echo "   signing key: $KEY"
echo "   fingerprint: $FPR"
if [ "$FPR" != "$AUTHOR_FPR" ]; then
    echo "ERROR: fingerprint is not the author key ($AUTHOR_FPR)"; exit 1
fi

echo "== 1. pre-check: the manifest verifies over the frozen tree"
sha256sum --quiet -c MANIFEST.sha256
N_ROWS=$(wc -l < MANIFEST.sha256)
echo "   manifest OK ($N_ROWS rows)"

echo "== 2. applying the patch"
git apply --check "$PATCH"
git apply "$PATCH"
git --no-pager diff --stat
echo
echo "   Review the full diff now (in another window):  git -C $REPO diff"
confirm "The five edits look right?"

echo "== 3. gates: cabal test all (the locale rename must stay green; takes a while)"
export PATH="$HOME/.ghcup/bin:$PATH"
cabal test all

echo "== 4. re-signing the manifest over the SAME census"
# sha256sum -c format: 64 hex chars + two spaces + path -> path starts at col 67
cut -c67- MANIFEST.sha256 | xargs -d '\n' sha256sum > MANIFEST.sha256.new
mv MANIFEST.sha256.new MANIFEST.sha256
sha256sum --quiet -c MANIFEST.sha256
N_ROWS_AFTER=$(wc -l < MANIFEST.sha256)
[ "$N_ROWS_AFTER" = "$N_ROWS" ] || { echo "ERROR: census changed ($N_ROWS -> $N_ROWS_AFTER)"; exit 1; }
echo "   manifest re-verified, census unchanged ($N_ROWS_AFTER rows)"

echo "== 5. commit + tag (author key)"
git add -A
git commit -S -m "R-D14 boundary: the acceptance metric registered — realized loss per decision against grounded outcomes (credence-governor outcome_bench @ bef325f, reading manifest b3ec4bb1...); exit-from-shadow declared: bar_waste 0.05%, n_min 1000, rolling 30 days; safety bar deferred to the harm-channel ruling. Riding the same boundary: the deference-floor amendment (never-zero floor withdrawn for the VoI readout; change-point re-funding + the strict k in {1,2,3} edge stand proven), R-D20/21/22 canonized into CLAUDE.md's protocol text, the test-membrane locale fix. Manifest re-signed over the same census."
git tag -s "$TAG" -m "author countersign over the R-D14 registration boundary: the outcome-scored realized-loss metric is the membrane's registered acceptance standard; exit-from-shadow bars declared (waste 0.05%, n_min 1000, rolling 30 days; safety deferred to the harm-channel ruling); the deference-floor amendment, the R-D20/21/22 canonization and the locale fix ride the same boundary; the acceptance-metric interregnum closes"
echo
git tag -v "$TAG"
echo

confirm "Push master + $TAG to origin?"
git push origin master
git push origin "$TAG"

echo
echo "BOUNDARY CLOSED: $TAG is author-signed and pushed."
echo "Builder follow-ups now unblocked: bar values into outcome_bench/bench.py,"
echo "bench + report regeneration (the bar table renders pass/fail), roadmap"
echo "Phase-1 line -> CLOSED."
