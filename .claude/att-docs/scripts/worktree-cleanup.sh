#!/usr/bin/env bash
# Runs the worktree cleanup script, which lives in the worktree-sweeper plugin.
exec bash "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/plugins/worktree-sweeper/scripts/worktree-cleanup.sh" "$@"
