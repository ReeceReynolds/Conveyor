# Changelog

## 0.1.0 (2026-11-10)


### Features

* add the agent registry and versioning (milestone 2) ([#24](https://github.com/ReeceReynolds/Conveyor/issues/24)) ([2639102](https://github.com/ReeceReynolds/Conveyor/commit/263910299bde2373dd14fd4f460290904c69188d))
* **model:** add factory and agent configuration models with validate command ([#3](https://github.com/ReeceReynolds/Conveyor/issues/3)) ([ab3266f](https://github.com/ReeceReynolds/Conveyor/commit/ab3266f124805bf2ea736a0ce6aea1af00fe180c))
* **registry:** add agent list, read-only registry commands, readable show and Windows CI ([#31](https://github.com/ReeceReynolds/Conveyor/issues/31)) ([671895e](https://github.com/ReeceReynolds/Conveyor/commit/671895ed058d42e3015b07b91f0b13c863c31266))


### Bug Fixes

* **model:** report unprintable characters, cap alias expansion, contain Windows paths ([#4](https://github.com/ReeceReynolds/Conveyor/issues/4)) ([118bffa](https://github.com/ReeceReynolds/Conveyor/commit/118bffa72f39545c85be6c2517863abae682b329))
* **model:** report YAML nested too deeply instead of crashing ([#33](https://github.com/ReeceReynolds/Conveyor/issues/33)) ([f0e8e6e](https://github.com/ReeceReynolds/Conveyor/commit/f0e8e6ed78e1a4c1664c0126b627df52f406f54c))
* **storage:** wait out a concurrent replace when checking an object on Windows ([#41](https://github.com/ReeceReynolds/Conveyor/issues/41)) ([2438aac](https://github.com/ReeceReynolds/Conveyor/commit/2438aac4e46f2d0b430b3a29c958bbc0c7fc161e))


### Performance Improvements

* **cli:** import the registry and storage only in agent commands ([#34](https://github.com/ReeceReynolds/Conveyor/issues/34)) ([f3d73be](https://github.com/ReeceReynolds/Conveyor/commit/f3d73be9013e5135bcbe5748c1c40909198a5577))
* **contracts:** import each contract module once per run ([#36](https://github.com/ReeceReynolds/Conveyor/issues/36)) ([a8f47ab](https://github.com/ReeceReynolds/Conveyor/commit/a8f47aba15fb25bbc32b992c07e9722ff89b5999))
* **registry:** diff large texts in near-linear time ([#35](https://github.com/ReeceReynolds/Conveyor/issues/35)) ([8424eee](https://github.com/ReeceReynolds/Conveyor/commit/8424eee1bc9c4f9cd47ce02de22c4156d1460a28))


### Documentation

* add the pre-M3 bug and performance sweep report ([#32](https://github.com/ReeceReynolds/Conveyor/issues/32)) ([b9c3bea](https://github.com/ReeceReynolds/Conveyor/commit/b9c3bea71450f4bfe0084415d658ec1e5041a5ff))
