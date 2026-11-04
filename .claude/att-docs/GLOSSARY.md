# Overmind

A shared base of skills, hooks, and scripts that agents use to work a repository's issues unattended and to keep its documents and tests current.

## Language

### Work selection

**Cleared**:
An issue that carries the `ready-for-agent` label, so an unattended session may take it up. An issue that is not cleared is never served.
_Avoid_: Ready, approved

**Blocked**:
The `Blocked` label on an issue that waits on something it cannot get for itself, such as another issue or pull request, a person, or a service. It is set and removed by hand or by the implement skill, and a labeled issue is never served.
_Avoid_: Blocker

**Blocker**:
An open issue that GitHub's issue dependencies list as blocking another issue. The blocked issue is not served until every one of its blockers is closed.
_Avoid_: Dependency, blocked issue

### Review

**Ready for review**:
A pull request whose self review is clean and whose checks have all passed, marked by the `Manual Review Needed` label, so it waits on the user.
_Avoid_: Ready, done
