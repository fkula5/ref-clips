# Changelog

## [1.9.0](https://github.com/fkula5/ref-clips/compare/v1.8.0...v1.9.0) (2026-11-12)


### Features

* **groups:** explain an empty coach or referee picker ([b2fe6bd](https://github.com/fkula5/ref-clips/commit/b2fe6bdea3348a6288f9fbea486fc30346ff11f3))
* **groups:** let group managers remove a coach ([1bed9f5](https://github.com/fkula5/ref-clips/commit/1bed9f5de959854dc0d874afc64acf00cad5d03e))


### Bug Fixes

* **errors:** show the logged-in user on error pages ([e219061](https://github.com/fkula5/ref-clips/commit/e219061d31ce5ac494077ca5de7124891ea7917f))
* **groups:** coach picker 404, coach removal, user on error pages ([fc402cd](https://github.com/fkula5/ref-clips/commit/fc402cd535af6afcd9510e7cb9c1a51a086243f7))
* **groups:** post the coach picker to /groups/{id}/coaches ([4c76b85](https://github.com/fkula5/ref-clips/commit/4c76b8573e0a6b729143fb25ea2fc903a629f238))
* **security:** pass names to inline confirm() as JSON strings ([2917ef5](https://github.com/fkula5/ref-clips/commit/2917ef57c38ab9e9ec09d70268f2bd2fae477bbb))

## [1.8.0](https://github.com/fkula5/ref-clips/compare/v1.7.0...v1.8.0) (2026-11-12)


### Features

* **db:** add match scoresheets table ([97182e1](https://github.com/fkula5/ref-clips/commit/97182e1648712f6f9b45aab91fd021a4f7ca6d40))
* match scoresheet files on the match page ([cd51630](https://github.com/fkula5/ref-clips/commit/cd516300c24dadfc664da50a5b6f6a4f38d3135b))


### Bug Fixes

* **deploy:** back up match scoresheet files ([2e64abc](https://github.com/fkula5/ref-clips/commit/2e64abc6d1387ced0947bddadeab014a2aef23c1))
* **ui:** collapse the header into a menu on phones and fix mobile overflow ([598f7c9](https://github.com/fkula5/ref-clips/commit/598f7c9a940cc12da5ca84dc56b4ca560ee0dd5c))

## [1.7.0](https://github.com/fkula5/ref-clips/compare/v1.6.0...v1.7.0) (2026-11-12)


### Features

* **db:** add training sets tables ([b011e20](https://github.com/fkula5/ref-clips/commit/b011e2052225ad2deac2e817d78b7065afec430b))
* training sets with notes, ordering and group pins ([9f893c7](https://github.com/fkula5/ref-clips/commit/9f893c709fbfc41a1f2890bac6743eb376d78402))

## [1.6.0](https://github.com/fkula5/ref-clips/compare/v1.5.0...v1.6.0) (2026-11-11)


### Features

* paginate the lists that grow without bound ([2bb245f](https://github.com/fkula5/ref-clips/commit/2bb245f66d7791b94fd3f4efad4d91792ab96024))


### Bug Fixes

* keep opened notifications read, and paginate long lists ([813a197](https://github.com/fkula5/ref-clips/commit/813a197ab57adf1993c66daffcdcb42e3b1a1848))
* **notifications:** keep opened notifications read after going back ([ca1dd1d](https://github.com/fkula5/ref-clips/commit/ca1dd1d9da2b36f1ff6ce3c23b61a03da2615dd4))

## [1.5.0](https://github.com/fkula5/ref-clips/compare/v1.4.0...v1.5.0) (2026-11-11)


### Features

* **clips:** record who described a clip ([b8ad2ea](https://github.com/fkula5/ref-clips/commit/b8ad2ea6f472fd9d1b4ec8ffa4d4666830eb592a))
* **groups:** add the groups pages, activity table, review queue and list filters ([21cd6d3](https://github.com/fkula5/ref-clips/commit/21cd6d3919c5a8268f506a8d92993d2297245992))
* **groups:** add training group tables and the group_added notification ([90ca319](https://github.com/fkula5/ref-clips/commit/90ca319ca40a1d7c0bc99a6b92328038936bf145))
* **groups:** training groups ([2b58c99](https://github.com/fkula5/ref-clips/commit/2b58c99e44e7d0c1ee65db4b94069c4a11e91a6e))

## [1.4.0](https://github.com/fkula5/ref-clips/compare/v1.3.1...v1.4.0) (2026-11-10)


### Features

* **logs:** keep watch room ids out of the logs ([99f101a](https://github.com/fkula5/ref-clips/commit/99f101a4f74d6340cb803237b6a3c69fe6479d72))
* **notify:** add the bell and the notifications page ([f565bdc](https://github.com/fkula5/ref-clips/commit/f565bdced54930622cca5882d6e5711dd6acc2e5))
* **notify:** create notifications for ratings, comments and published sheets ([e6592ec](https://github.com/fkula5/ref-clips/commit/e6592ec5b21a4e766786598af560873942c75314))
* **notify:** in-app notifications ([66419b3](https://github.com/fkula5/ref-clips/commit/66419b354fec29e5911482455efed9c82fd26dee))
* **watch:** add the Oglądaj razem room panel to the player ([2508586](https://github.com/fkula5/ref-clips/commit/2508586c8089eea39f1708ba640e6762128178eb))
* **watch:** in-memory rooms and a WebSocket endpoint ([e3ed0f2](https://github.com/fkula5/ref-clips/commit/e3ed0f211c588e55bac6873b3a5fab9c56fa395c))

## [1.3.1](https://github.com/fkula5/ref-clips/compare/v1.3.0...v1.3.1) (2026-11-10)


### Bug Fixes

* **ui:** show every user-facing date as dd.mm.yyyy ([e6da35d](https://github.com/fkula5/ref-clips/commit/e6da35da68801ee86d98108a9df8550b7a9fa67a))

## [1.3.0](https://github.com/fkula5/ref-clips/compare/v1.2.1...v1.3.0) (2026-11-09)


### Features

* **sheet:** add assessment sheet tables and seed the standard elements ([8b17747](https://github.com/fkula5/ref-clips/commit/8b1774747fc7b6b8a5a21be0e580bf6db892e64a))
* **sheet:** add permission rules for assessment sheets ([f4519cb](https://github.com/fkula5/ref-clips/commit/f4519cb0defc672f51654b8b02dcbfc9d0ef0a61))
* **sheet:** add the qualifier assessment sheet ([5d3a567](https://github.com/fkula5/ref-clips/commit/5d3a5673ca355219d3cac562b9901b8b0cd18e3c))
* **sheet:** edit the assessment elements in the admin panel ([e77a77a](https://github.com/fkula5/ref-clips/commit/e77a77a5612ce6db1dcd48334cdc48e3e0c2801f))
* **sheet:** fill in, publish and read the assessment sheet ([cd7384d](https://github.com/fkula5/ref-clips/commit/cd7384d53ed5d429d354e7c9d1106e398e99fa56))


### Bug Fixes

* **sheet:** keep published sheets safe when a match is deleted ([f9dff5e](https://github.com/fkula5/ref-clips/commit/f9dff5ea74228a0061098e65fa79de9f1a266ea6))

## [1.2.1](https://github.com/fkula5/ref-clips/compare/v1.2.0...v1.2.1) (2026-11-09)


### Bug Fixes

* **ci:** keep a release from failing on the release PR test step ([643c3a0](https://github.com/fkula5/ref-clips/commit/643c3a0d25fbf0268bc7a1e161b13dc00d37d5b0))
* **ci:** keep a release from failing on the release PR test step ([1b7e4d4](https://github.com/fkula5/ref-clips/commit/1b7e4d4b48942245c0bb287908fe9baacc9dd3ad))
* **player:** ignore play() interrupted by a quick pause ([d69ee20](https://github.com/fkula5/ref-clips/commit/d69ee202fcbdf0068bedc425c7297629ffffdc41))
* **player:** ignore play() interrupted by a quick pause ([faaf9d4](https://github.com/fkula5/ref-clips/commit/faaf9d47471b4a4c60835cce4f4932ea034282d1))

## [1.2.0](https://github.com/fkula5/ref-clips/compare/v1.1.0...v1.2.0) (2026-11-09)


### Features

* **app:** numer wersji w stopce i build-arg REFCLIPS_VERSION ([f2e194f](https://github.com/fkula5/ref-clips/commit/f2e194f87ef1c3c6506793b077e2baff8b36b526))
* **deploy:** ci-entry.sh, wymuszone polecenie klucza CI na serwerze ([0e83efb](https://github.com/fkula5/ref-clips/commit/0e83efbff6c715f8eb24f13d7e8eb1eed4a1cc0b))
* **deploy:** deploy.sh jako wyjście awaryjne obok obrazów z GHCR ([2c4c423](https://github.com/fkula5/ref-clips/commit/2c4c423fe72cba1f42cd2a0a96b22608972b177d))


### Bug Fixes

* **ci:** gałąź PR-a wydania z wyjścia release-please ([4244d24](https://github.com/fkula5/ref-clips/commit/4244d248981c7f757921c06aacedf9338d6e1bad))
* **ci:** repozytorium dla gh w jobie bez checkoutu ([96f5fdf](https://github.com/fkula5/ref-clips/commit/96f5fdfdb02205ca32d0f048aa495a6ee1cec0f4))
