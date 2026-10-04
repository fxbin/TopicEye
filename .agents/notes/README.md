# Agent Notes

决策语料。回答**为什么**这样定、放弃了什么、何时再议。

## 与其它记录的分工

| 位置 | 回答什么 | 变更频率 | 入库 |
|---|---|---|---|
| GitHub issue / PR | 什么坏了、什么时候修的、谁修的 | 随事件 | 是 |
| `AGENTS.md` | 跑测安全守则、验证命令、项目背景 | 少改 | 是 |
| `.agents/notes/`（本目录） | **为什么**这样定、放弃了什么、何时再议 | 生命周期迁移 | 是 |
| `.vidt/` | 本轮工作记忆、待办、临时结论 | 高频覆写 | **否**（被 gitignore） |

真源优先顺序：状态看 GitHub，命令与背景看 AGENTS.md，理由看这里。

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
