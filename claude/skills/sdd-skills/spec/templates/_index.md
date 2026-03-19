# Spec 模板索引

## 可用模板

| 模板名 | 文件 | 适用场景 | 贡献者 |
|--------|------|---------|--------|
| crud | crud.md | 标准增删改查功能 | - |
| permission-fix | permission-fix.md | 权限漏洞修复 | - |
| report-query | report-query.md | 报表/统计查询 | - |

## 如何使用

```
/spec "需求描述" --template crud
```

系统会加载模板预填 spec.md 骨架，你只需补充具体细节。

## 如何贡献新模板

1. 在 `templates/` 目录下创建 `{模板名}.md`
2. 在本文件中添加一行索引
3. 提交到 dj-skills 仓库
