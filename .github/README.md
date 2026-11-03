# 轻量 Skill 发布

主分支保存完整项目，`skill` 分支只分发 skill 本身，避免安装时拉取插件示例。编辑 `skills/ulanzi-plugin/`，生成分支由工作流维护。

将仓库公开并推送到 `main` 后，启用 [publish-skill.yml](workflows/publish-skill.yml)。工作流使用 `GITHUB_TOKEN` 和 `contents: write` 更新 `skill` 分支，无需发布 npm 包或配置个人访问令牌。仓库或组织的规则须允许写入该分支。

首次发布后，确认 `skill` 分支根目录存在 `SKILL.md`，再验证项目 README 的安装命令。插件示例默认从 `main` 按需获取，修改插件无需重新发布 skill。

本地生成与检查（从仓库根目录执行，输出目录须不存在）：

```bash
python3 tools/build_skill_distribution.py --out ./dist/skill
npx skills add ./dist/skill --list
```

# Lightweight skill publishing

Main contains the full project. The generated `skill` branch distributes only the skill, avoiding plugin example downloads during installation. Edit `skills/ulanzi-plugin/`; let the workflow maintain the distribution branch.

After making the repository public and pushing to `main`, enable [publish-skill.yml](workflows/publish-skill.yml). It uses `GITHUB_TOKEN` with `contents: write`, without a custom npm package or personal access token. Repository or organization rules must allow writes to the branch.

After the first run, confirm that `skill` has a root `SKILL.md`, then verify the README installation command. Examples are fetched from `main` on demand, so plugin-only changes do not require republishing the skill. Use the commands above from the repository root to build and inspect a local distribution; its output directory must not exist.
