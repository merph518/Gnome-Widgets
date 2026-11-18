# Changelog

## [0.32.4](https://github.com/merph518/Overmind-Mod/compare/v0.32.3...v0.32.4) (2026-11-18)


### Features

* add the pin-drift mod for pending releases and consumers behind the latest tag ([ffcdbbd](https://github.com/merph518/Overmind-Mod/commit/ffcdbbdf65294a6d2b2383fff76257420ca698e5))
* add worktree-sweeper, a band and pane that remove finished worktrees ([#91](https://github.com/merph518/Overmind-Mod/issues/91)) ([6b83e2e](https://github.com/merph518/Overmind-Mod/commit/6b83e2e2eb381ae6b2db6d29ecdc72938bfc748a))
* open a pane from the oversee loop row listing its queue and results ([00c6ee3](https://github.com/merph518/Overmind-Mod/commit/00c6ee3739f926a04e993b3cb100890e4eae2235))
* open a pane from the oversee loop row listing its queue and results ([#93](https://github.com/merph518/Overmind-Mod/issues/93)) ([0a516f6](https://github.com/merph518/Overmind-Mod/commit/0a516f6fa48407b25a23b7d06e9d0d6082248e37))
* pin-drift band for pending releases and consumers behind the latest tag ([#90](https://github.com/merph518/Overmind-Mod/issues/90)) ([c08a0fb](https://github.com/merph518/Overmind-Mod/commit/c08a0fb1b9c7f29d4d9fd2504b6ee9f6fe07a445))
* review-queue fast paths for merges, labels and shared dismiss ([dc1296b](https://github.com/merph518/Overmind-Mod/commit/dc1296b4e09b6fc9c41772cc6e2597919b1747e8))
* review-queue fast paths for merges, labels and shared dismiss ([#106](https://github.com/merph518/Overmind-Mod/issues/106)) ([a10b150](https://github.com/merph518/Overmind-Mod/commit/a10b15040e243f863eaff533a6b03b877dc43f03))


### Bug Fixes

* address the first self review of the oversee loop pane ([ccfc15c](https://github.com/merph518/Overmind-Mod/commit/ccfc15cc0c9e61447d221b812a78f33ce02db91a))
* check list numbers against Word's render and pair only items that read alike ([02f8278](https://github.com/merph518/Overmind-Mod/commit/02f827895dfb160eab54b418f39db5fd9edf9b2d))
* check list numbers against Word's render and pair only items that read alike ([#31](https://github.com/merph518/Overmind-Mod/issues/31)) ([b88b93f](https://github.com/merph518/Overmind-Mod/commit/b88b93f05e61c33f12f884046588b590a349f1dc))
* compare only letters and digits past the key, and fall back when the render cannot be read ([6f2d514](https://github.com/merph518/Overmind-Mod/commit/6f2d51442c4fc1c09e6717ca1498fd35586474f3))
* keep the words around a recovered picture and steady its line spacing ([7404b7c](https://github.com/merph518/Overmind-Mod/commit/7404b7c24d1985f4c96ab2c7ec0174f0fcba4dc4))
* read a picture and its fallback once, and keep a link's other pictures ([c5e43eb](https://github.com/merph518/Overmind-Mod/commit/c5e43eb7dc968d4d3ec4b7a86e36c4a160310644))
* recover the text of EMF and WMF pictures in Word files ([cfd6f47](https://github.com/merph518/Overmind-Mod/commit/cfd6f47e43a249eea44ceaaa533e8bbc639de66b))
* recover the text of EMF and WMF pictures in Word files ([#29](https://github.com/merph518/Overmind-Mod/issues/29)) ([042db4d](https://github.com/merph518/Overmind-Mod/commit/042db4d16b5562fc3ef28763c2a00fd6a99fe16d))
* report pin-drift read failures instead of hiding them ([a5b2154](https://github.com/merph518/Overmind-Mod/commit/a5b2154abee4548fbf05cc093aa632bb600bd561))
* review-queue checks the label command inside a gh pr compound ([8cc1c4e](https://github.com/merph518/Overmind-Mod/commit/8cc1c4e7bfb5c10046e84c21e6afd3471f8a24bd))
* review-queue stamps only changes, matches gh placeholders ([21df12e](https://github.com/merph518/Overmind-Mod/commit/21df12ead73e537106f40a9a92996feec3a1a466))
* take a style-numbered label's style off, and draw a legal level's numbers as decimals ([0b11bdd](https://github.com/merph518/Overmind-Mod/commit/0b11bdd04b2e3bcc97fbba1cc143f2aeb327528f))
* write the text a level drawn without a number draws ([#103](https://github.com/merph518/Overmind-Mod/issues/103)) ([3c4245c](https://github.com/merph518/Overmind-Mod/commit/3c4245c31a8e8dfa97bca3e12b229cfc6f7a778e))
* write the text a level drawn without a number draws, instead of numbering it 1. ([92e29cc](https://github.com/merph518/Overmind-Mod/commit/92e29cc614f0f108e7e91b23497454e7f593c175))

## [0.32.3](https://github.com/merph518/Overmind-Mod/compare/v0.32.2...v0.32.3) (2026-11-18)


### Features

* add a ready-label gate that blocks a ready report on an unlabeled pull request ([#89](https://github.com/merph518/Overmind-Mod/issues/89)) ([2fdb5ae](https://github.com/merph518/Overmind-Mod/commit/2fdb5ae600e9a7b21b7d121f221b9388bb580467))
* add a ready-label gate that blocks a ready report on an unlabeled pull request ([#89](https://github.com/merph518/Overmind-Mod/issues/89)) ([cf5c7f6](https://github.com/merph518/Overmind-Mod/commit/cf5c7f644b4f501b942de6763637f4e5ecd99707))
* add review-queue band for pull requests waiting on review ([c3badba](https://github.com/merph518/Overmind-Mod/commit/c3badba97fcbcc1db5bd0a425bc8905abf49afc8))
* add runner-health, a band for an offline or starved self-hosted runner ([8cef000](https://github.com/merph518/Overmind-Mod/commit/8cef00083cd377849137db716b230923ed8c2e83))
* add runner-health, a band for an offline or starved self-hosted runner ([#92](https://github.com/merph518/Overmind-Mod/issues/92)) ([2bd0f36](https://github.com/merph518/Overmind-Mod/commit/2bd0f364b2590a69dfac7cb201a85b7d7b132807))
* review-queue band for pull requests waiting on review ([#88](https://github.com/merph518/Overmind-Mod/issues/88)) ([07a34af](https://github.com/merph518/Overmind-Mod/commit/07a34af29af83e54c9938a63d2ac1ef34e6c03d6))
* route subagent models in the background and drop the selector pane ([3ea1dee](https://github.com/merph518/Overmind-Mod/commit/3ea1deee8404460f20a3c584ac4bfcda6e4935e5))
* route subagent models in the background and drop the selector pane ([#81](https://github.com/merph518/Overmind-Mod/issues/81)) ([0e42229](https://github.com/merph518/Overmind-Mod/commit/0e422298a9606bef85507e6ac7872658d2caccef))


### Bug Fixes

* bound the pin waits and fail closed on an unreadable lock ([3bc9ce2](https://github.com/merph518/Overmind-Mod/commit/3bc9ce21033c048bbc49eb8ffe99cc03b7ab19d5))
* drop stale pane wording from the model-router license, README and tsconfig ([2b2779d](https://github.com/merph518/Overmind-Mod/commit/2b2779d9aac50a1834fe4e02a730405c422fe811))
* expand variables and skip options in cd targets for the ready-label gate ([b193dad](https://github.com/merph518/Overmind-Mod/commit/b193dad06c5eb4b2c6809b97c9364667c84a942d))
* find the pin run and compare minor versions per consumer ([c5ba33a](https://github.com/merph518/Overmind-Mod/commit/c5ba33a868f4966d2521bfbd425b289f49e5eb1d))
* flag a rule only when the text it quotes changed ([#73](https://github.com/merph518/Overmind-Mod/issues/73)) ([19501b9](https://github.com/merph518/Overmind-Mod/commit/19501b931c67a5560b439e8af77c865ff947800d))
* give every unreadable pin run the rerun command and a report line ([864d92d](https://github.com/merph518/Overmind-Mod/commit/864d92dc88e3fa78c059349396146f98bf560769))
* hedge the replaced-run cause and skip the tag poll for an unmerged release ([04ae3e1](https://github.com/merph518/Overmind-Mod/commit/04ae3e16725b3466f7bf6b4fadb3082d2692ef77))
* keep a comment opener written as code from swallowing later text ([2419d38](https://github.com/merph518/Overmind-Mod/commit/2419d38a5daa678b13b182ec31f9ad83483a5c7f))
* keep a slow pin run from skipping healthy consumers and the report ([ef8cf0a](https://github.com/merph518/Overmind-Mod/commit/ef8cf0a665ccb110e7898a4077445a039fa3b29e))
* keep review-queue refreshes from overlapping across a reload ([eb3ec91](https://github.com/merph518/Overmind-Mod/commit/eb3ec916e37a6e56bda28e3cfca3df3dce3ae2f3))
* keep the placeholder strip linear on a long body ([#63](https://github.com/merph518/Overmind-Mod/issues/63)) ([3ffcb07](https://github.com/merph518/Overmind-Mod/commit/3ffcb07664ddf2ec063057623ae630d0ffed2582))
* keep the ready-label gate on the turn across notifications and odd commands ([94ee6da](https://github.com/merph518/Overmind-Mod/commit/94ee6da1ff5490760af4b7b6fa9e9aebfc612696))
* leave consumer pin bumps to the automation app in the implement skill ([91532e7](https://github.com/merph518/Overmind-Mod/commit/91532e747ca45c949fc325b1f78cbd6b3c7fdae0))
* leave consumer pin bumps to the automation app in the implement skill ([#80](https://github.com/merph518/Overmind-Mod/issues/80)) ([4161be3](https://github.com/merph518/Overmind-Mod/commit/4161be3a978995f81e1a7e588bfbf2a0c0524de8))
* leave picture placeholders out of the text pages.py searches ([#63](https://github.com/merph518/Overmind-Mod/issues/63)) ([4935716](https://github.com/merph518/Overmind-Mod/commit/4935716942aed7b0abd7cf8f43a07ce53bb46b6f))
* leave picture placeholders out of the text pages.py searches ([#63](https://github.com/merph518/Overmind-Mod/issues/63)) ([3aa57e0](https://github.com/merph518/Overmind-Mod/commit/3aa57e058adc5b70e4ba114f0af471eba3f10a2b))
* match style types and keep the list order check in hidden-text ([#32](https://github.com/merph518/Overmind-Mod/issues/32)) ([7a70cb1](https://github.com/merph518/Overmind-Mod/commit/7a70cb15537f68c5c7f01124115e11d03f6b85ae))
* name the release merge commit and the replaced-run case in the pin step ([f5ecb16](https://github.com/merph518/Overmind-Mod/commit/f5ecb166281e0b0dcb87970284790054ef35467f))
* name the stopped runners in the start command and say a job waits for a runner ([68ad3e7](https://github.com/merph518/Overmind-Mod/commit/68ad3e74f23d9d0728eafcee286438c5d49caa79))
* read every repository when one times out, and drop the list on hide ([2ad01b1](https://github.com/merph518/Overmind-Mod/commit/2ad01b1c432f5d5a2376e9bb1d57534746dcf4df))
* read table styles, the default paragraph style and defaults with toggles in hidden-text ([#32](https://github.com/merph518/Overmind-Mod/issues/32)) ([898dde2](https://github.com/merph518/Overmind-Mod/commit/898dde2a35ea70dab708b728122253d1da287ec6))
* read table styles, the default paragraph style and defaults with toggles in hidden-text ([#32](https://github.com/merph518/Overmind-Mod/issues/32)) ([1e9be1c](https://github.com/merph518/Overmind-Mod/commit/1e9be1c89523c2169638b1241c8377910cd991ad))
* report a hand-cut tag instead of chasing a dispatched run ([1ae956a](https://github.com/merph518/Overmind-Mod/commit/1ae956ae693504f0e0bbca86d8228cc07f4d87ab))
* resolve relative cd and -C, keep gh -R on branch lookups, narrow future-tense words ([b048756](https://github.com/merph518/Overmind-Mod/commit/b048756aa7a045158690e71cf14f715e97adebdb))
* skip the living-wiki page beside a Future folder as a source ([dcb9bb3](https://github.com/merph518/Overmind-Mod/commit/dcb9bb3eaccc7cc1bca5f81149d43e27cc48036b))
* skip the living-wiki page beside a Future folder as a source ([#20](https://github.com/merph518/Overmind-Mod/issues/20)) ([6f31504](https://github.com/merph518/Overmind-Mod/commit/6f3150491f22d99e519c78904579f43f3d2d4fe9))
* strip only markup the quote check can tell from wording ([c5be669](https://github.com/merph518/Overmind-Mod/commit/c5be669656b9450c662b5e4f2f53c03b7241bff0))
* strip tags with bare attributes and multi-line comments in the quote check ([61ff2e9](https://github.com/merph518/Overmind-Mod/commit/61ff2e9e45a2a2e698bc9111b9934febe2ac7a08))
* wait for the tag and the pin jobs before judging the pin run ([fb31a28](https://github.com/merph518/Overmind-Mod/commit/fb31a285b7f8babe3b16efafd747ef34894e6268))

## [0.32.2](https://github.com/merph518/Overmind-Mod/compare/v0.32.1...v0.32.2) (2026-11-18)


### Features

* check that every plugin has its marketplace and release-please entries ([#58](https://github.com/merph518/Overmind-Mod/issues/58)) ([add5784](https://github.com/merph518/Overmind-Mod/commit/add5784fbaf3d37d6ca839e0275c17e4fb6d65a9))


### Bug Fixes

* catch Python and shell cross-skill references in test selection ([d6c6fcd](https://github.com/merph518/Overmind-Mod/commit/d6c6fcd5429dddc3c9e47fa5e8027ff5100df706))
* do not trust Word page marks that disagree with its stored count ([#35](https://github.com/merph518/Overmind-Mod/issues/35)) ([3b22b3c](https://github.com/merph518/Overmind-Mod/commit/3b22b3ce4dca84376ea9973a22cc1d27569b6810))
* do not trust Word page marks that disagree with its stored page count ([e424bfc](https://github.com/merph518/Overmind-Mod/commit/e424bfc526d081bcafec565d9bda0e8a56c1faf2))
* read an escaped list marker as the plain marker in the rule diff ([105fe7e](https://github.com/merph518/Overmind-Mod/commit/105fe7e8c00b059d37e173f9467d8bda235a9ac0))
* read an escaped list marker as the plain marker in the rule diff ([#33](https://github.com/merph518/Overmind-Mod/issues/33)) ([098aedd](https://github.com/merph518/Overmind-Mod/commit/098aeddbf3a841e88dc5bfcee3b26ed8d4ebe05b))

## [0.32.1](https://github.com/merph518/Overmind-Mod/compare/v0.32.0...v0.32.1) (2026-11-18)


### Features

* add efficient-browser-use, a screenshot shrinker for Linux ([9d3803b](https://github.com/merph518/Overmind-Mod/commit/9d3803b5c711306b58073f30a71254ae9b308204))
* add efficient-browser-use, a screenshot shrinker for Linux ([#5](https://github.com/merph518/Overmind-Mod/issues/5)) ([3e15ac9](https://github.com/merph518/Overmind-Mod/commit/3e15ac9239beb77e88c30f125c18fe9d5b3f71bc))
* add model-router, a plugin that picks each subagent's model ([#9](https://github.com/merph518/Overmind-Mod/issues/9)) ([2c655d4](https://github.com/merph518/Overmind-Mod/commit/2c655d40adab82e9d649765b5d362f787255a035))
* add the cache-clock plugin, a prompt-cache countdown above the prompt ([cb90557](https://github.com/merph518/Overmind-Mod/commit/cb9055734fedcaaf1ea3c57db5d24cad4fe045e2)), closes [#8](https://github.com/merph518/Overmind-Mod/issues/8)
* add the handoff plugin, a Linux port of the Refresh handoff mod ([b3fd32c](https://github.com/merph518/Overmind-Mod/commit/b3fd32cb6e29984934bbc1af5854de4b0d1557bc))
* add the mods plugin, a /mods switchboard pane ([0a902c9](https://github.com/merph518/Overmind-Mod/commit/0a902c96ca50ff56fa0be5ec7578343e444076cb))
* add the mods switchboard plugin ([#4](https://github.com/merph518/Overmind-Mod/issues/4)) ([7fa683e](https://github.com/merph518/Overmind-Mod/commit/7fa683efedaae473a30dc503fdf0d70c2d68e49b))
* list the handoff plugin in the marketplace and release config ([c9aee70](https://github.com/merph518/Overmind-Mod/commit/c9aee70fdaa5d3a382e3c55d18a030c9bd112e6d))
* list the handoff plugin in the marketplace and release config ([#45](https://github.com/merph518/Overmind-Mod/issues/45)) ([3c118da](https://github.com/merph518/Overmind-Mod/commit/3c118da81ef2684d245cba305762181ab5786eba))
* re-read switches.json every 3 seconds in effort-optimizer ([9a8e061](https://github.com/merph518/Overmind-Mod/commit/9a8e0616ddbbca4ff45f3a500af1f7f3cd502111))


### Bug Fixes

* a table still ends a top-level list for the body column rule ([abcc50f](https://github.com/merph518/Overmind-Mod/commit/abcc50f1eed7d768d39358e8c15fdcef173f641a))
* block a second handoff press before the first await ([cbabf47](https://github.com/merph518/Overmind-Mod/commit/cbabf47fd375974b9f81ae43836da43ef7623e37)), closes [#8](https://github.com/merph518/Overmind-Mod/issues/8)
* count only a lettered item that takes the list up past a table ([bc9b9fe](https://github.com/merph518/Overmind-Mod/commit/bc9b9fee6e8d4975713294f3be58a1ca2a47d955))
* count pictures made smaller even when the ledger cannot be written ([4462fc9](https://github.com/merph518/Overmind-Mod/commit/4462fc984b69f8c2fffdc03eb4449c2aded44878))
* give a same-tag repo= move its own branch and plain notes ([bdf511f](https://github.com/merph518/Overmind-Mod/commit/bdf511f4a5223daee179520548d1364b4d85c22d))
* harden cache-clock keep warm and the handoff request ([1fd56d6](https://github.com/merph518/Overmind-Mod/commit/1fd56d687eee07b03510263e78ce38415e6f5b83)), closes [#8](https://github.com/merph518/Overmind-Mod/issues/8)
* keep a turn's count when it runs during a keep-warm ping ([d6905d6](https://github.com/merph518/Overmind-Mod/commit/d6905d6b5dc771a4e09cda051dc7d0fde80b7e54)), closes [#8](https://github.com/merph518/Overmind-Mod/issues/8)
* keep tables in items and resumed notes out of the body column rule ([0d52ef5](https://github.com/merph518/Overmind-Mod/commit/0d52ef5f2e80cbb809be74f83dac1202aab99e21))
* keep the describer hidden while it is spawned, and test the defaults ([747095e](https://github.com/merph518/Overmind-Mod/commit/747095e732ebc03fb2d6a573d8619f819a9e83c7)), closes [#53](https://github.com/merph518/Overmind-Mod/issues/53)
* keep the describer hidden while it is spawned, and test the defaults ([#53](https://github.com/merph518/Overmind-Mod/issues/53)) ([d67b1e7](https://github.com/merph518/Overmind-Mod/commit/d67b1e79cb657d9f8fb00619b95f90a0c8a2f0aa))
* leave a placeholder where convert-docs drops a picture ([7ccfb32](https://github.com/merph518/Overmind-Mod/commit/7ccfb32f24c91851e2434a5653abf2f523aae8f7))
* leave a placeholder where convert-docs drops a picture ([#36](https://github.com/merph518/Overmind-Mod/issues/36)) ([d96cdc4](https://github.com/merph518/Overmind-Mod/commit/d96cdc44a445787b804394a0f8acd43483fd7bf8))
* let a second secret scrub leave removed values alone ([c9208bb](https://github.com/merph518/Overmind-Mod/commit/c9208bbee8ade7249803721b6e5a12b72e953052))
* list the mods plugin in the marketplace and release-please config ([52dcb67](https://github.com/merph518/Overmind-Mod/commit/52dcb67c02e89faa024d6cd2e9883eb360e5f734))
* list the mods plugin in the marketplace and release-please config ([#47](https://github.com/merph518/Overmind-Mod/issues/47)) ([980aaf1](https://github.com/merph518/Overmind-Mod/commit/980aaf15bfdd082adf4134bbb57cb1cb62ddae29))
* **model-router:** describe the port as it works now in shipped text ([287e51b](https://github.com/merph518/Overmind-Mod/commit/287e51b0ef68eb4b9c8bfc05a3d6de94c1f2a0df))
* **model-router:** one model table, Fable ranked with the deep tier ([601f416](https://github.com/merph518/Overmind-Mod/commit/601f4162ce7a62de5f0168ab32873815863cb628))
* **mods:** keep a switch press from being undone, and refresh after a reload ([693be7c](https://github.com/merph518/Overmind-Mod/commit/693be7c16b7e804696ad0920f0a8f7d025cee4bb))
* **mods:** offer Reopen only with a chat, and read nested hook sources ([4e6f392](https://github.com/merph518/Overmind-Mod/commit/4e6f3928a26323265be3a8919e19ab25b5b85a48))
* move repo= for a consumer already on the pinned tag ([262e795](https://github.com/merph518/Overmind-Mod/commit/262e79574eed134db8561f2c92e7651b08fe9c59))
* read a leading ~ in CLAUDE_CONFIG_DIR in effort-optimizer too ([341a722](https://github.com/merph518/Overmind-Mod/commit/341a722038327a2ab9d1483980019325fcec8d07))
* read a slide equation's Office Math text ([1cbd0fe](https://github.com/merph518/Overmind-Mod/commit/1cbd0fe4cc80e722a046fe5909a0bf9950b56a4b))
* read deck text from the slide XML so text boxes and rectangles survive ([645b4b2](https://github.com/merph518/Overmind-Mod/commit/645b4b263307fe11772355777cfc0d72122c9c6b))
* read deck text from the slide XML so text boxes and rectangles survive ([#28](https://github.com/merph518/Overmind-Mod/issues/28)) ([8c6364a](https://github.com/merph518/Overmind-Mod/commit/8c6364ac5d5d00ef5be4e2858938b58e15495fe1))
* read Strict decks, equations and symbol titles, and keep escaped slide text intact ([1d8f5b3](https://github.com/merph518/Overmind-Mod/commit/1d8f5b3d02ff9c3c5f98ceaa0a6b34b7df3711a3))
* read Strict math and keep a multi-line equation's lines apart ([689b581](https://github.com/merph518/Overmind-Mod/commit/689b581cb78700e1908674f44d161a8cc63b97b4))
* return the size parse from sizeOf and tidy the tests ([6d75c3b](https://github.com/merph518/Overmind-Mod/commit/6d75c3be8344396841bd49a948818a35d2db0ac2)), closes [#53](https://github.com/merph518/Overmind-Mod/issues/53)
* say what happens without ImageMagick in describe mode, and keep words when a ledger write fails ([dae6915](https://github.com/merph518/Overmind-Mod/commit/dae69155ea08806c498b6f3242583a77307ad761))
* scrub before cutting, and keep a request that arrives during a run ([1ed9ce3](https://github.com/merph518/Overmind-Mod/commit/1ed9ce3f8e0d2433dfbbea06478e7ece0cda7d54))
* shrink to 75% with a 768 px floor, and keep describe mode working without ImageMagick ([83864bd](https://github.com/merph518/Overmind-Mod/commit/83864bdc14bd5694ba7c36783a5a6ad6657b3998))
* skip Word's newer alt text and test every picture shape ([51b0876](https://github.com/merph518/Overmind-Mod/commit/51b087647b3ac5e60f2f02dc283d06471e9e59f9))

## [0.32.0](https://github.com/merph518/Overmind-Mod/compare/v0.31.38...v0.32.0) (2026-11-18)


### ⚠ BREAKING CHANGES

* **voice:** remove the voice plugin and the Baton tooling

### Features

* add effort-optimizer, a plugin that suggests an effort level per prompt ([95dbe35](https://github.com/merph518/Overmind-Mod/commit/95dbe35872e3f20c6fb9a461a0ebdd97f0fe2833))
* **general:** run the repository hooks from a hooks module ([fe0a422](https://github.com/merph518/Overmind-Mod/commit/fe0a4225673d4ace74a5891cd7695f05e1781f2e))
* **general:** run the repository hooks from a hooks module ([#1](https://github.com/merph518/Overmind-Mod/issues/1)) ([8fc9ac6](https://github.com/merph518/Overmind-Mod/commit/8fc9ac6a5c06e84dd573f1ea43fe25778b335e6b))
* move consumers and releases to merph518/Overmind-Mod ([17781fb](https://github.com/merph518/Overmind-Mod/commit/17781fb8be63b4049eec7597778ea89de50a0c28))
* **voice:** remove the voice plugin and the Baton tooling ([df20496](https://github.com/merph518/Overmind-Mod/commit/df204961a333de828e17d4af4b05284c341c9452)), closes [#11](https://github.com/merph518/Overmind-Mod/issues/11)
* **voice:** run the voice hooks from a hooks module, with a speech pane ([86ee39e](https://github.com/merph518/Overmind-Mod/commit/86ee39ea3cba142b4576bb601969b4df010b0418))


### Bug Fixes

* **general:** keep context from beneath on a gate's deny ([0d794a3](https://github.com/merph518/Overmind-Mod/commit/0d794a35106fd8a873afd0aa20d09b0b0b8e608b))
* **general:** keep loop state out of repositories that never ran a loop ([620de74](https://github.com/merph518/Overmind-Mod/commit/620de74f256e8a2b1201ed77f9b1bf65b2f1f781))
* keep effort-optimizer off scripted runs and fix holds from the second review ([75990e4](https://github.com/merph518/Overmind-Mod/commit/75990e4f95fd24df62593d314f13e6345771a63b))
* refuse a repo= move the check cannot fetch ([a32126c](https://github.com/merph518/Overmind-Mod/commit/a32126c119de6d2ed246c0568357c13d30164174))
* say when auto mode lets an older effort level go, and test it ([c6cea4b](https://github.com/merph518/Overmind-Mod/commit/c6cea4bbe2a411714eee9d924ba56b26f17c24cf))
* tighten effort-optimizer from the first self review ([900b92a](https://github.com/merph518/Overmind-Mod/commit/900b92af8dcfc6779f8f5a1e62acbee06768c6a8))
* **voice:** name the messaging socket for the scripts, and stop the answer form once decided ([520282c](https://github.com/merph518/Overmind-Mod/commit/520282ca6482cf8fae28ac849570c289d32f6377))
* **voice:** read the session file with isolated Python ([7e3bad5](https://github.com/merph518/Overmind-Mod/commit/7e3bad5daf569edd0ae360b9f52d3b7662f1d737))

## [0.31.38](https://github.com/merph518/Overmind/compare/v0.31.37...v0.31.38) (2026-11-15)


### Bug Fixes

* **convert-docs:** count a list level that names no start from 0 ([de76659](https://github.com/merph518/Overmind/commit/de76659fdf4c1484c8b340278c05b05d60800b2c))
* **convert-docs:** count the spaces typed ahead of a hanging paragraph's first words ([501f3a1](https://github.com/merph518/Overmind/commit/501f3a10f44d1d500662ab75a27c8051c0d36c1c))
* **convert-docs:** end an item at a paragraph Word starts short of its text ([5b3b01b](https://github.com/merph518/Overmind/commit/5b3b01ba33c93db2548f375691d01d3cb7a97e81))
* **convert-docs:** follow a paragraph's own tab stops when placing a paragraph after a sub-list ([749d1d8](https://github.com/merph518/Overmind/commit/749d1d8de29e76efca35d845c6de3f428d912955))
* **convert-docs:** keep a digit list apart from the one before it when it starts its own count ([3319e0b](https://github.com/merph518/Overmind/commit/3319e0b2a8f7ac2c8a0a2cdcf31c57e962f65e0e))
* **convert-docs:** keep an indented paragraph in its list item across a blank paragraph ([329417c](https://github.com/merph518/Overmind/commit/329417ce2eff12a62223ae5d8149e95b734b24b1))
* **convert-docs:** keep an indented paragraph in its list item across a blank paragraph ([e8877e9](https://github.com/merph518/Overmind/commit/e8877e9d5559d3fdc1890ae5bc892cb0d3ac905a))
* **convert-docs:** number top-level lists the way Word prints them ([c108882](https://github.com/merph518/Overmind/commit/c108882aa5aaead75955f6cb7cf86ddf188d46d1))
* **convert-docs:** take a list LibreOffice copied onto a paragraph off it when the Word file gives it none ([e74308f](https://github.com/merph518/Overmind/commit/e74308f88f39b15bb9f421bf9744b7a713fd8029))
* **convert-docs:** write a paragraph after a sub-list under the item Word draws it under ([b104ba4](https://github.com/merph518/Overmind/commit/b104ba405cec75e7cdff64f84d32ce305fd49b75))
* **convert-docs:** write a paragraph after a sub-list under the item Word draws it under ([c1b5816](https://github.com/merph518/Overmind/commit/c1b58161c0a6f6a406f5af1ba2c7aef35462d3b5))

## [0.31.37](https://github.com/merph518/Overmind/compare/v0.31.36...v0.31.37) (2026-11-15)


### Bug Fixes

* **convert-docs:** count a Word list across its overrides and keep a heading Word numbers as an item ([14419db](https://github.com/merph518/Overmind/commit/14419db4baf33ff8d4006c21068342095a83afcd))
* **convert-docs:** count a Word list across its overrides and keep a heading Word numbers as an item ([f7973c5](https://github.com/merph518/Overmind/commit/f7973c5be4c9d2ff4931acd65266b76168ebc715))
* **convert-docs:** fall back to LibreOffice's copy and lay pages out from the rebuilt lists ([6286869](https://github.com/merph518/Overmind/commit/6286869121ba40bc656514e34d5bfe460c737ffd))
* **convert-docs:** keep tracked-deleted text and the byte-order mark out of the list-number check ([20f9100](https://github.com/merph518/Overmind/commit/20f9100c1cc5bd4fe32ca42d0040114265fa61cc))
* **convert-docs:** lay pages out with the copied list taken off the blank ([e1639ee](https://github.com/merph518/Overmind/commit/e1639ee3e57190f5fdf9635cf1a8776c79313389))
* **convert-docs:** map the layout copy's blanks back through the tree, not by paragraph order ([b8b49e3](https://github.com/merph518/Overmind/commit/b8b49e39ab51c697b322b9305587d6adcece62f9))
* **convert-docs:** read the list-number check's source without tracked deletions ([cab9220](https://github.com/merph518/Overmind/commit/cab9220aab48568a85fd58879eba8ed099139511))
* **convert-docs:** take a blank paragraph LibreOffice gave a deleted item's list out of it ([28ebfd0](https://github.com/merph518/Overmind/commit/28ebfd03bcca8e9c559917e22311578a9bb5e7e7))
* **convert-docs:** take a blank paragraph LibreOffice gave a deleted item's list out of it ([8184f0b](https://github.com/merph518/Overmind/commit/8184f0b253f7dee886b52d3841515c9c608b5270))
* **convert-docs:** write a table nested in a cell one row per line ([7c63bda](https://github.com/merph518/Overmind/commit/7c63bda0a9e8c7632c1dd7e9390c90589da80021))
* **convert-docs:** write a table nested in a cell one row per line ([4bcd2ad](https://github.com/merph518/Overmind/commit/4bcd2ad1ee7a3d6286ec52f515e03201b21c2430))
* **convert-docs:** write letter and roman items as labeled bullets, drop tracked-deleted items ([4f7801e](https://github.com/merph518/Overmind/commit/4f7801e250ea8c000abab7affce48fd4b8bb1ee8))
* **convert-docs:** write letter and roman items as labeled bullets, drop tracked-deleted items ([d5f5b99](https://github.com/merph518/Overmind/commit/d5f5b99da4b41940c61663cb857ed1eaa85f385b))

## [0.31.36](https://github.com/merph518/Overmind/compare/v0.31.35...v0.31.36) (2026-11-13)


### Bug Fixes

* **convert-docs:** drop Word hidden text, write letter and roman list labels, keep a leading o ([#681](https://github.com/merph518/Overmind/issues/681)) ([#684](https://github.com/merph518/Overmind/issues/684)) ([339674b](https://github.com/merph518/Overmind/commit/339674bc53ac1c9b167747b5929310c8557cf09f))
* **convert-docs:** keep the list number check from wrapping onto an earlier item ([#677](https://github.com/merph518/Overmind/issues/677)) ([2fb0abb](https://github.com/merph518/Overmind/commit/2fb0abb338b662c16af5227bd18ab690f3597f9d))

## [0.31.35](https://github.com/merph518/Overmind/compare/v0.31.34...v0.31.35) (2026-11-13)


### Bug Fixes

* **convert-docs:** draw Word list numbers and nesting through Pandoc ([#675](https://github.com/merph518/Overmind/issues/675)) ([0dad792](https://github.com/merph518/Overmind/commit/0dad792b5792684652b2dec9a1f394c4c1b83e0a))
* gate every local model run in build-test-pack on the user's yes ([#665](https://github.com/merph518/Overmind/issues/665)) ([#666](https://github.com/merph518/Overmind/issues/666)) ([5dd5621](https://github.com/merph518/Overmind/commit/5dd56214409409b4ca27e294e8b13bf42513412c))
* give each revalidation finding a repair call of its own, sized by cards ([#656](https://github.com/merph518/Overmind/issues/656)) ([#657](https://github.com/merph518/Overmind/issues/657)) ([0fb4b06](https://github.com/merph518/Overmind/commit/0fb4b06299cc916399e6b141b0eb31a5f22bf393))
* hold the overall confidence to the builder's confidence ceiling ([#650](https://github.com/merph518/Overmind/issues/650)) ([#652](https://github.com/merph518/Overmind/issues/652)) ([dd97b0c](https://github.com/merph518/Overmind/commit/dd97b0ceeab1c23f206229dcfff5d69ea14134f0))
* name both hosts in the report's advice for a repeatedly cut step ([#653](https://github.com/merph518/Overmind/issues/653)) ([#663](https://github.com/merph518/Overmind/issues/663)) ([7e7970e](https://github.com/merph518/Overmind/commit/7e7970e281a0f88f826fe6fb54c61660fc1c6501))
* recommend a server thinking budget and warn in the setup check when it is missing ([#651](https://github.com/merph518/Overmind/issues/651)) ([#654](https://github.com/merph518/Overmind/issues/654)) ([9ac186b](https://github.com/merph518/Overmind/commit/9ac186b111429ce63dd374d24263b0514ef18232))
* state the design rules to the checklist reads ([#661](https://github.com/merph518/Overmind/issues/661)) ([#664](https://github.com/merph518/Overmind/issues/664)) ([f97b76b](https://github.com/merph518/Overmind/commit/f97b76b0b6edc13e407f6a271d10a4d0391397c5))
* state the design rules to the revalidation walk and put repaired cards back through the sets ([#659](https://github.com/merph518/Overmind/issues/659)) ([#660](https://github.com/merph518/Overmind/issues/660)) ([abeb642](https://github.com/merph518/Overmind/commit/abeb6427b11b10e18c85f4611af5690e3ac93100))

## [0.31.34](https://github.com/merph518/Overmind/compare/v0.31.33...v0.31.34) (2026-11-09)


### Bug Fixes

* keep the partial clone mark when a signal lands during the restore ([#645](https://github.com/merph518/Overmind/issues/645)) ([#648](https://github.com/merph518/Overmind/issues/648)) ([e3829f3](https://github.com/merph518/Overmind/commit/e3829f3040027658f596ce05b6187ff9ec3cc808))

## [0.31.33](https://github.com/merph518/Overmind/compare/v0.31.32...v0.31.33) (2026-11-09)


### Bug Fixes

* ask build-test-pack reply fields in the order they are worked out ([#545](https://github.com/merph518/Overmind/issues/545)) ([#640](https://github.com/merph518/Overmind/issues/640)) ([0a85974](https://github.com/merph518/Overmind/commit/0a85974fb5d466cfca40ba40335adef30ef52458))
* carry each card's scenario kind on pack.testCards ([#563](https://github.com/merph518/Overmind/issues/563)) ([#644](https://github.com/merph518/Overmind/issues/644)) ([10bcf62](https://github.com/merph518/Overmind/commit/10bcf6241c4574fbdb0f72b26a073d3960ed8dfa))
* end the build-test-pack break-only pass when its reply is cut off ([#557](https://github.com/merph518/Overmind/issues/557)) ([#641](https://github.com/merph518/Overmind/issues/641)) ([7608e33](https://github.com/merph518/Overmind/commit/7608e33c6f086bffb23374ff615ce7241bdbad71))
* stop build-test-pack model calls reusing a closed connection, bound the inventory reply, and order step rows ([#639](https://github.com/merph518/Overmind/issues/639), [#642](https://github.com/merph518/Overmind/issues/642), [#643](https://github.com/merph518/Overmind/issues/643)) ([#647](https://github.com/merph518/Overmind/issues/647)) ([0484125](https://github.com/merph518/Overmind/commit/04841253235ddd64af38b5142cbbb3841f55d63a))
* stop queue add promising a restore that sudoers will refuse ([#539](https://github.com/merph518/Overmind/issues/539)) ([#637](https://github.com/merph518/Overmind/issues/637)) ([dff268c](https://github.com/merph518/Overmind/commit/dff268ca94442b85119778742783fb850e34071f))

## [0.31.32](https://github.com/merph518/Overmind/compare/v0.31.31...v0.31.32) (2026-11-09)


### Features

* log check verdicts, repairs, progress and call usage to status.log ([#635](https://github.com/merph518/Overmind/issues/635)) ([39ed3e3](https://github.com/merph518/Overmind/commit/39ed3e3e23ca2e3fe21b9c2ad1c1d7221fee3457))

## [0.31.31](https://github.com/merph518/Overmind/compare/v0.31.30...v0.31.31) (2026-11-09)


### Features

* split the revalidation walk and the senior review into one call per group or part ([#488](https://github.com/merph518/Overmind/issues/488)) ([#632](https://github.com/merph518/Overmind/issues/632)) ([3631a30](https://github.com/merph518/Overmind/commit/3631a30ecf27129f6becf0fe555a0472b514a49e))


### Bug Fixes

* fail acronym verify when a cited source file is missing ([#631](https://github.com/merph518/Overmind/issues/631)) ([de8bb3b](https://github.com/merph518/Overmind/commit/de8bb3b468be0e2e7287ed39b4383622735161b3))

## [0.31.30](https://github.com/merph518/Overmind/compare/v0.31.29...v0.31.30) (2026-11-09)


### Features

* Warn when the Baton tool snapshot is behind Code Conductor ([#529](https://github.com/merph518/Overmind/issues/529)) ([#628](https://github.com/merph518/Overmind/issues/628)) ([1b8706d](https://github.com/merph518/Overmind/commit/1b8706da0a4f171341c3b98273edb6bfc59a097f))

## [0.31.29](https://github.com/merph518/Overmind/compare/v0.31.28...v0.31.29) (2026-11-08)


### Features

* **general:** add the azdo-sync skill ([#590](https://github.com/merph518/Overmind/issues/590)) ([#625](https://github.com/merph518/Overmind/issues/625)) ([e378bc0](https://github.com/merph518/Overmind/commit/e378bc08d48855471ea8f0f32b7528333a01ab0d))

## [0.31.28](https://github.com/merph518/Overmind/compare/v0.31.27...v0.31.28) (2026-11-08)


### Features

* **general:** add the azdo-stories skill ([#589](https://github.com/merph518/Overmind/issues/589)) ([#624](https://github.com/merph518/Overmind/issues/624)) ([045591d](https://github.com/merph518/Overmind/commit/045591dee65968d33124fd9c9eb95fe2188981bc))

## [0.31.27](https://github.com/merph518/Overmind/compare/v0.31.26...v0.31.27) (2026-11-08)


### Features

* **general:** add the azdo-build-issue skill ([#586](https://github.com/merph518/Overmind/issues/586)) ([#617](https://github.com/merph518/Overmind/issues/617)) ([6c11dd2](https://github.com/merph518/Overmind/commit/6c11dd2ec1775fefccbf57c2cb1233577914fd9f))
* **general:** add the azdo-digest skill ([#587](https://github.com/merph518/Overmind/issues/587)) ([#621](https://github.com/merph518/Overmind/issues/621)) ([c205fe4](https://github.com/merph518/Overmind/commit/c205fe4dac72cc4c5e2a697de7d2b045a5f32a36))
* **general:** add the azdo-review skill ([#588](https://github.com/merph518/Overmind/issues/588)) ([#623](https://github.com/merph518/Overmind/issues/623)) ([528de8c](https://github.com/merph518/Overmind/commit/528de8c23fea7fd72f19833dc29c8b64f7432dc2))
* **general:** add the wyatt-review-phase-1 skill ([#593](https://github.com/merph518/Overmind/issues/593)) ([#619](https://github.com/merph518/Overmind/issues/619)) ([2599c0a](https://github.com/merph518/Overmind/commit/2599c0a0bb62b6fa436f64134de3d8a073ed0424))
* **general:** add the wyatt-review-phase-2 skill ([#618](https://github.com/merph518/Overmind/issues/618)) ([#622](https://github.com/merph518/Overmind/issues/622)) ([5c1d1dc](https://github.com/merph518/Overmind/commit/5c1d1dc8bd560420fb75cac296617e6fa3af93d5))

## [0.31.26](https://github.com/merph518/Overmind/compare/v0.31.25...v0.31.26) (2026-11-08)


### Features

* **general:** add runs and resume to the oversee ledger ([#611](https://github.com/merph518/Overmind/issues/611)) ([#614](https://github.com/merph518/Overmind/issues/614)) ([9181c12](https://github.com/merph518/Overmind/commit/9181c12bf296d5431d3d8e17da377bf0536a7a77))
* **general:** add the sql-discovery-learning-log skill ([#612](https://github.com/merph518/Overmind/issues/612)) ([e94a6bb](https://github.com/merph518/Overmind/commit/e94a6bba23ce551007771532c245fc76934228c6))
* **general:** add the wyatt-regression-issue skill ([#592](https://github.com/merph518/Overmind/issues/592)) ([#615](https://github.com/merph518/Overmind/issues/615)) ([366e71c](https://github.com/merph518/Overmind/commit/366e71cbe548e9d7181278f34d2075fcb6a53757))

## [0.31.25](https://github.com/merph518/Overmind/compare/v0.31.24...v0.31.25) (2026-11-08)


### Features

* **general:** add the new-branch skill ([#591](https://github.com/merph518/Overmind/issues/591)) ([#610](https://github.com/merph518/Overmind/issues/610)) ([f89c484](https://github.com/merph518/Overmind/commit/f89c4842c8a992f6b725678c98543be4e570dcfa))
* **general:** add the sql-lookup skill ([#584](https://github.com/merph518/Overmind/issues/584)) ([#608](https://github.com/merph518/Overmind/issues/608)) ([b3b0427](https://github.com/merph518/Overmind/commit/b3b0427743e9dc366ef1c6d44c85e22d697debe9))

## [0.31.24](https://github.com/merph518/Overmind/compare/v0.31.23...v0.31.24) (2026-11-08)


### Features

* **general:** add the sweep-suite skill ([#583](https://github.com/merph518/Overmind/issues/583)) ([#606](https://github.com/merph518/Overmind/issues/606)) ([cd942eb](https://github.com/merph518/Overmind/commit/cd942eb99852de531a5a056cd0ac34b0e404a80e))

## [0.31.23](https://github.com/merph518/Overmind/compare/v0.31.22...v0.31.23) (2026-11-08)


### Bug Fixes

* show needs you only for a question to the user, add waiting on a partner ([#601](https://github.com/merph518/Overmind/issues/601)) ([#604](https://github.com/merph518/Overmind/issues/604)) ([6381647](https://github.com/merph518/Overmind/commit/638164728612e74c38733868debfbdc57986aa08))

## [0.31.22](https://github.com/merph518/Overmind/compare/v0.31.21...v0.31.22) (2026-11-08)


### Features

* **att-docs:** add the skip-ledger skill ([#600](https://github.com/merph518/Overmind/issues/600)) ([e9643b1](https://github.com/merph518/Overmind/commit/e9643b12d5d8416789ae2d8c943aeb8ec0c6a583))
* **general:** add the manual-spec skill ([#581](https://github.com/merph518/Overmind/issues/581)) ([#599](https://github.com/merph518/Overmind/issues/599)) ([932eec4](https://github.com/merph518/Overmind/commit/932eec4526a9b5814dac3286ce88b212adcbdc17))

## [0.31.21](https://github.com/merph518/Overmind/compare/v0.31.20...v0.31.21) (2026-11-08)


### Features

* **general:** add the debug-spec skill ([#580](https://github.com/merph518/Overmind/issues/580)) ([#597](https://github.com/merph518/Overmind/issues/597)) ([db02183](https://github.com/merph518/Overmind/commit/db021837d94bc98051c48c885c2953ff8dba28bd))

## [0.31.20](https://github.com/merph518/Overmind/compare/v0.31.19...v0.31.20) (2026-11-08)


### Features

* **att-docs:** add the manual-validation-walkthrough skill ([#596](https://github.com/merph518/Overmind/issues/596)) ([f0c941e](https://github.com/merph518/Overmind/commit/f0c941eaf24f90be86f4e9705bfdb87268087ca9))


### Bug Fixes

* cut a long list of document numbers so a gate stop still writes its fail line ([#413](https://github.com/merph518/Overmind/issues/413)) ([#577](https://github.com/merph518/Overmind/issues/577)) ([77a8d79](https://github.com/merph518/Overmind/commit/77a8d795b2198c3abdbbd3421f3a8310eee84dce))
* let the revalidation repair build the new cards a finding names ([#487](https://github.com/merph518/Overmind/issues/487)) ([#574](https://github.com/merph518/Overmind/issues/574)) ([3b09445](https://github.com/merph518/Overmind/commit/3b094450c4d158095f6a2db5bd00c7b0d2b36c92))

## [0.31.19](https://github.com/merph518/Overmind/compare/v0.31.18...v0.31.19) (2026-11-06)


### Features

* **att-docs:** add the sir-housekeeping skill ([#569](https://github.com/merph518/Overmind/issues/569)) ([6775ead](https://github.com/merph518/Overmind/commit/6775ead1a0c8d3cd1a21f2914533fb9d09d7ad73))

## [0.31.18](https://github.com/merph518/Overmind/compare/v0.31.17...v0.31.18) (2026-11-05)


### Bug Fixes

* offer flagged break cards to the core objective pass when the pack has no BREAK IT set ([#567](https://github.com/merph518/Overmind/issues/567)) ([b5badc4](https://github.com/merph518/Overmind/commit/b5badc42b8c46dc55ba0276a9edf0c5871cdb7df)), closes [#565](https://github.com/merph518/Overmind/issues/565)

## [0.31.17](https://github.com/merph518/Overmind/compare/v0.31.16...v0.31.17) (2026-11-05)


### Bug Fixes

* keep BREAK IT and plain cards apart in the design tidy ([#560](https://github.com/merph518/Overmind/issues/560)) ([#564](https://github.com/merph518/Overmind/issues/564)) ([7dfce07](https://github.com/merph518/Overmind/commit/7dfce0706d7c25e845b97825758248ef4c91b78d))

## [0.31.16](https://github.com/merph518/Overmind/compare/v0.31.15...v0.31.16) (2026-11-05)


### Features

* Let the build supervisor answer a job's questions while it waits ([#542](https://github.com/merph518/Overmind/issues/542)) ([#549](https://github.com/merph518/Overmind/issues/549)) ([82bcb06](https://github.com/merph518/Overmind/commit/82bcb06fba1b97538229d44e22c5f25b5efcb334))
* Send build calls at temperature 0 with a fixed seed and record the seed ([#541](https://github.com/merph518/Overmind/issues/541)) ([#547](https://github.com/merph518/Overmind/issues/547)) ([249b2a5](https://github.com/merph518/Overmind/commit/249b2a505901c89a43d1b1c48de94f5d28220f94))


### Bug Fixes

* Run phase 1 understanding with thinking off and flag repeated budget cuts ([#540](https://github.com/merph518/Overmind/issues/540)) ([#543](https://github.com/merph518/Overmind/issues/543)) ([52c9e86](https://github.com/merph518/Overmind/commit/52c9e868d4cf8276a9c85524782cf851598d9719))
* Settle phase 3 review questions from the change description before stopping ([#538](https://github.com/merph518/Overmind/issues/538)) ([#546](https://github.com/merph518/Overmind/issues/546)) ([6edeb18](https://github.com/merph518/Overmind/commit/6edeb18dd96a56a9f1fe1ac35856e65d2ee54d76))
* State that scenario kind stays inside Phase 6 ([#559](https://github.com/merph518/Overmind/issues/559)) ([fc6dba6](https://github.com/merph518/Overmind/commit/fc6dba6be7891bed6f919298d5a728f42e80f586))
* Stream model calls so a cancel stops generation and the unload passes ([#552](https://github.com/merph518/Overmind/issues/552)) ([#556](https://github.com/merph518/Overmind/issues/556)) ([42e67dd](https://github.com/merph518/Overmind/commit/42e67ddbbb5756f6d0502423ecfbdc861391cfca))
* Write one Phase 6 assumption per document for empty scenario kinds ([#551](https://github.com/merph518/Overmind/issues/551)) ([#558](https://github.com/merph518/Overmind/issues/558)) ([db1ed9b](https://github.com/merph518/Overmind/commit/db1ed9b02a0b309469a1fbdb2123c656b250d07e))
* Write the Draft workbook at Phase 8 and drop the Phase 9 summary fallback ([#553](https://github.com/merph518/Overmind/issues/553)) ([#555](https://github.com/merph518/Overmind/issues/555)) ([e412768](https://github.com/merph518/Overmind/commit/e412768712b99bc3c917ed92566ad89bc0aee1a8))

## [0.31.15](https://github.com/merph518/Overmind/compare/v0.31.14...v0.31.15) (2026-11-04)


### Features

* claim shared files so concurrent sessions in one repo do not collide ([#257](https://github.com/merph518/Overmind/issues/257)) ([#528](https://github.com/merph518/Overmind/issues/528)) ([44b8456](https://github.com/merph518/Overmind/commit/44b84562ee31e604c2b37be86035e26c65662f79))
* replay recorded model calls with --model replay: ([#492](https://github.com/merph518/Overmind/issues/492)) ([#536](https://github.com/merph518/Overmind/issues/536)) ([3439d38](https://github.com/merph518/Overmind/commit/3439d38d35be0ae579dbce8069c389f05b16da3f))

## [0.31.14](https://github.com/merph518/Overmind/compare/v0.31.13...v0.31.14) (2026-11-04)


### Features

* Check that skills name only Baton tools and arguments that exist ([#134](https://github.com/merph518/Overmind/issues/134)) ([#531](https://github.com/merph518/Overmind/issues/531)) ([c9edb20](https://github.com/merph518/Overmind/commit/c9edb2035953391bf53f0645c63109a54d08af99))

## [0.31.13](https://github.com/merph518/Overmind/compare/v0.31.12...v0.31.13) (2026-11-04)


### Bug Fixes

* cover a partial-clone Overmind checkout in the pin tests ([#508](https://github.com/merph518/Overmind/issues/508)) ([#526](https://github.com/merph518/Overmind/issues/526)) ([6c91a8b](https://github.com/merph518/Overmind/commit/6c91a8babf046b18fe7162247e4ca81cb2bfb1af))

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
