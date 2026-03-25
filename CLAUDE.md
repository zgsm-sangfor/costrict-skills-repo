# CLAUDE.md

## 提交规范

使用原子化提交，格式：`[type] 中文描述`

类型：
- `[feat]` 新功能
- `[fix]` 修复
- `[refactor]` 重构
- `[docs]` 文档
- `[ci]` CI/CD
- `[chore]` 杂项

示例：
```
[feat] 新增 skill 子命令拆分为独立 commands
[fix] 修复去重逻辑误删同源不同条目的问题
[ci] 添加 Tier 2 LLM 评估环境变量
```

规则：
- 每个提交只做一件事
- 描述用中文，简洁直白
- 不写 Co-Authored-By（除非协作场景）
