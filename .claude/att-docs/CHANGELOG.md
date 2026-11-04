# Changelog

## [0.31.12](https://github.com/merph518/Overmind/compare/v0.31.11...v0.31.12) (2026-11-04)


### Features

* run one Phase 9 step or one builder pass on its own ([#491](https://github.com/merph518/Overmind/issues/491)) ([#525](https://github.com/merph518/Overmind/issues/525)) ([44e9754](https://github.com/merph518/Overmind/commit/44e975462796d1f0c9fae53d125bf41d5bc705d0))


### Bug Fixes

* remove the scratch folders test files leave in the temp folder ([#523](https://github.com/merph518/Overmind/issues/523)) ([c84c49b](https://github.com/merph518/Overmind/commit/c84c49b74cd257fccaff470a36c3cc2aa15a9ced))

## [0.31.11](https://github.com/merph518/Overmind/compare/v0.31.10...v0.31.11) (2026-11-04)


### Bug Fixes

* fetch the objects a partial clone left in the pin workflow checkout ([#521](https://github.com/merph518/Overmind/issues/521)) ([297011f](https://github.com/merph518/Overmind/commit/297011f182c75ff70ba75a4915513cafb4fd19bb))

## [0.31.10](https://github.com/merph518/Overmind/compare/v0.31.9...v0.31.10) (2026-11-04)


### Bug Fixes

* guard the main checkout in sessions that load .omp extensions ([#517](https://github.com/merph518/Overmind/issues/517)) ([#518](https://github.com/merph518/Overmind/issues/518)) ([5e7ce09](https://github.com/merph518/Overmind/commit/5e7ce093b4c13de0343f1dc334901149854a355e))
* keep the guard extension's shipped comments harness neutral ([#520](https://github.com/merph518/Overmind/issues/520)) ([2f6556e](https://github.com/merph518/Overmind/commit/2f6556e0e7d8bf090c9d675fa9601183da62f646))

## [0.31.9](https://github.com/merph518/Overmind/compare/v0.31.8...v0.31.9) (2026-11-04)


### Features

* persist implement backlog loops ([#256](https://github.com/merph518/Overmind/issues/256)) ([#515](https://github.com/merph518/Overmind/issues/515)) ([9113602](https://github.com/merph518/Overmind/commit/9113602b15fd8048c089198e3f4637a8b161aa8a))

## [0.31.8](https://github.com/merph518/Overmind/compare/v0.31.7...v0.31.8) (2026-11-04)


### Features

* doc-watch waits 30 seconds for a manual sign-in on an attended run ([#182](https://github.com/merph518/Overmind/issues/182)) ([#512](https://github.com/merph518/Overmind/issues/512)) ([93ac88b](https://github.com/merph518/Overmind/commit/93ac88bdc4d39f0c57757df56f462743970cff78))

## [0.31.7](https://github.com/merph518/Overmind/compare/v0.31.6...v0.31.7) (2026-11-04)


### Bug Fixes

* Remove the build-pack test scratch folders after each run ([#506](https://github.com/merph518/Overmind/issues/506)) ([deced9a](https://github.com/merph518/Overmind/commit/deced9ac12e7212d8c1073fbe04d971f1a2bcf70))

## [0.31.6](https://github.com/merph518/Overmind/compare/v0.31.5...v0.31.6) (2026-11-04)


### Features

* open consumer pin pull requests after releases ([#194](https://github.com/merph518/Overmind/issues/194)) ([#503](https://github.com/merph518/Overmind/issues/503)) ([ca3b7d5](https://github.com/merph518/Overmind/commit/ca3b7d550bc0c04bd737c06ae559b54e6756cc12))
* read long replies in short and a ready reply as one line ([#189](https://github.com/merph518/Overmind/issues/189)) ([#504](https://github.com/merph518/Overmind/issues/504)) ([90ffda7](https://github.com/merph518/Overmind/commit/90ffda78d1c76aca6a12193e00e811f969361961))

## [0.31.5](https://github.com/merph518/Overmind/compare/v0.31.4...v0.31.5) (2026-11-04)


### Features

* record each model call's prompt and reply in work/calls ([#492](https://github.com/merph518/Overmind/issues/492)) ([#496](https://github.com/merph518/Overmind/issues/496)) ([0ac9451](https://github.com/merph518/Overmind/commit/0ac9451e7f5d5f8a88337565f95c89a8cc45e69c))


### Bug Fixes

* document git worktree fallback ([#500](https://github.com/merph518/Overmind/issues/500)) ([603d9fc](https://github.com/merph518/Overmind/commit/603d9fcb04ac0861a6ae0a980cbea51389c2b7f0))

## [0.31.4](https://github.com/merph518/Overmind/compare/v0.31.3...v0.31.4) (2026-11-04)


### Features

* build-test-pack keeps a snapshot per phase and reruns a slice of a job in a sandbox ([#490](https://github.com/merph518/Overmind/issues/490)) ([#497](https://github.com/merph518/Overmind/issues/497)) ([c5758c1](https://github.com/merph518/Overmind/commit/c5758c17cead4ccb8a24ad4a641b39ce7aea0703))
* oversee-development serves the best next issue in a milestone ([#230](https://github.com/merph518/Overmind/issues/230)) ([#494](https://github.com/merph518/Overmind/issues/494)) ([8a8e13f](https://github.com/merph518/Overmind/commit/8a8e13f13f4df11f75d0985dd0ecd6199c5ced59))
* refuse stray files and bulk adds before every commit ([#157](https://github.com/merph518/Overmind/issues/157)) ([#495](https://github.com/merph518/Overmind/issues/495)) ([d9d6ada](https://github.com/merph518/Overmind/commit/d9d6ada042fd52245335f78de5e8a34fd0dfcab4))

## [0.31.3](https://github.com/merph518/Overmind/compare/v0.31.2...v0.31.3) (2026-11-04)


### Features

* apply a volume change to the clip already playing ([#111](https://github.com/merph518/Overmind/issues/111)) ([#481](https://github.com/merph518/Overmind/issues/481)) ([9c641be](https://github.com/merph518/Overmind/commit/9c641bedc6afd78a045a2922cf9fa46ede4b440c))
* list worktrees with their pull request state and remove merged ones ([#144](https://github.com/merph518/Overmind/issues/144)) ([#484](https://github.com/merph518/Overmind/issues/484)) ([7ecd79e](https://github.com/merph518/Overmind/commit/7ecd79ec198eee68a07269ba5eba6ec8dc057f7e))
* report installed plugins that are behind the repository ([#137](https://github.com/merph518/Overmind/issues/137)) ([#482](https://github.com/merph518/Overmind/issues/482)) ([76416b9](https://github.com/merph518/Overmind/commit/76416b9207a60b357ba66955676329f023f75cd3))
* ship the consumer sync and check scripts in every snapshot ([#234](https://github.com/merph518/Overmind/issues/234)) ([#480](https://github.com/merph518/Overmind/issues/480)) ([a5de379](https://github.com/merph518/Overmind/commit/a5de3793a2f6667a32c1031eb37edcaf97df0eed))

## [0.31.2](https://github.com/merph518/Overmind/compare/v0.31.1...v0.31.2) (2026-11-04)


### Features

* **general:** oversee-development serves only ready-for-agent issues and skips open blockers ([#472](https://github.com/merph518/Overmind/issues/472)) ([#473](https://github.com/merph518/Overmind/issues/473)) ([51fb388](https://github.com/merph518/Overmind/commit/51fb38854026798b77d68cb04113dec75b29a708))

## [0.31.1](https://github.com/merph518/Overmind/compare/v0.31.0...v0.31.1) (2026-11-03)


### Features

* **general:** let oversee-development hand issues to subagents ([#464](https://github.com/merph518/Overmind/issues/464)) ([def2371](https://github.com/merph518/Overmind/commit/def23715f4353b630e8977a7cda1c9a0656b3b17))


### Bug Fixes

* **general:** oversee-development skips issues waiting on triage or a human ([#467](https://github.com/merph518/Overmind/issues/467)) ([68c6f82](https://github.com/merph518/Overmind/commit/68c6f827a192a3271d79b4e24e334f52b73b4e0d))
