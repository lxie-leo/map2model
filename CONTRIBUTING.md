# Contributing / 贡献指南

Thanks for your interest in improving map2model! / 感谢你想给 map2model 出力!

## Getting started

```bash
git clone https://github.com/lxie-leo/map2model
cd map2model/backend && uv sync && uv run pytest -q        # backend (85 tests)
cd ../frontend && corepack pnpm install && corepack pnpm typecheck && corepack pnpm test
```

Before opening a PR: run the checks above, keep commits small, and follow the existing code style (comments in plain Chinese are the norm in this repo).

## License grant (important)

By submitting a pull request, you agree that your contribution is licensed to this project under the repository's current license (GNU AGPL-3.0-or-later), **and** that the maintainer may additionally use your contribution under the project's commercial license (dual licensing). You retain copyright of your work.

This is what keeps dual licensing legally possible — every line in the repo must belong to someone who has granted these rights.

## 贡献授权(重要)

提交 PR 即表示你同意:你的贡献按仓库当前协议(GNU AGPL-3.0-or-later)授权给本项目使用,并且**同时允许**维护者在项目的商业许可(双许可)场景下使用你的贡献。你的版权仍归你自己。

正是这一条让双许可在法律上可行——仓库里的每一行代码,都必须来自授予过这两项权利的人。
