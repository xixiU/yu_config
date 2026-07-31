## 全局规则
1. Always respond in 中文
2. 禁止重复写文档
3. 应该是先施工，实现功能再写文档
4. 所有的bug修复都要列出重要的总结复现步骤，后续修改要避免导致原始bug的二次出现
5. 使用第一性原理进行思考，先思考可行性、重要步骤、最后再施工
6. 研发实施完成之后，不需要编译，只需要代码静测即可， 所有的编译打包等操作，提醒人工进行

## 全局约定
### docker相关
统一设置时区为UTC+8,亚洲

## git相关
当前工程是WSL与windows、linux混合开发环境，在查看代码差异的时候使用
git diff --ignore-cr-at-eol 或 git diff -w

## 目录结构
相关文档统一写在docs目录下，并按照二级目录归类，如下是常见的类别，可在此基础上扩充，非必要不要写文档
docs/design             设计相关
docs/plan               计划
docs/implementation     实施细节
docs/summary            总结文档
