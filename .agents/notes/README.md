# Agent Notes

决策语料。回答**为什么**这样定、放弃了什么、何时再议。

## 与其它记录的分工

| 位置 | 回答什么 | 变更频率 | 入库 |
|---|---|---|---|
| GitHub issue / PR | 什么坏了、什么时候修的、谁修的 | 随事件 | 是 |
| `AGENTS.md` | 权限、安全、架构边界、验证入口与交付约定 | 少改 | 是 |
| 指定长期文档（如 AGENT_API.md / DEPLOYMENT.md） | 接口与部署合同 | 随功能 | 是 |
| `.agents/notes/`（本目录） | **为什么**这样定、放弃项，以及同主题的有效合同 | 随合同与生命周期 | 是 |
| `.vidt/` | 本轮工作记忆、待办、临时结论 | 高频覆写 | **否**（被 gitignore） |

职责入口：状态看 GitHub，长期协作约定看 AGENTS.md，运行合同看指定 owning note / 长期文档，理由看这里。

## 生命周期

```
proposed ──────────► implemented ──► archived
   │                      │
   └──────────► rejected  （仅当仍能阻止诱人错误）
```

`rejected/` 的保留标准是「删掉它，下一个人会再犯同样的错」。

## 写作约束

- 中文单文件，`{lifecycle}/{class}/yyyy-mm-dd-slug.md`
- `Status:` 行必填，且须与所在目录一致
- 决策被推翻时**新建**笔记并双向链接，不改写旧文
- 实现细节只写到「能理解决策与边界」为止

契约全文见 virtual-intelligent-dev-team skill 的 `references/agent-notes-contract.md`。

## 何时记录与如何收尾

范围裁剪、否决方案、接受残余风险、证据不足和其它可复用的长期取舍需要沉淀。
机械改动、瞬时进度不新增笔记；已有 owning note 时更新原篇，避免同一决策重复维护。
每次交付说明一种结果：**新建笔记、更新已有笔记、或无长期结论及简短理由**。

已有设计或运行文档仍保留时写薄指针并注明权威位置；原文退役前迁移有效合同并更新现用引用；不把既有文档批量重写为 notes，也不以笔记维护当前 ship/hold。
当前目录分类遵守上述 lifecycle/class 结构；分类修正可移动文件并更新当前引用，历史正文不随当前代码重写。

按已启用 virtual-intelligent-dev-team skill 的 agent-notes 契约执行校验器，显式传入本仓库作为 repo-root。
校验目录、Status、Markdown 链接及 .vidt 边界；它不判断是否遗漏了应写的长期决策，也不把历史正文中的代码路径当作当前运行命令。
代码 CI 全绿不能替代这一收尾判断。新增笔记须明确是否已纳入提交，不能默认本地笔记已经交付。

职责分工的历史与本次局部调整分别见 [长期规则与决策理由](implemented/process/2026-10-24-agent-guidance-and-decision-notes.md) 和 [入口收敛决定](implemented/process/2026-10-24-knowledge-entry-consolidation.md)。
