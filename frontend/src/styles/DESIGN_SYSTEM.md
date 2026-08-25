# 元认知测评系统设计系统

本项目以 `src/styles/main.css` 中的设计令牌为唯一视觉基础。业务页面优先使用 Bootstrap 布局能力，并通过以下项目组件保持一致：

- `AppPageHeader`：页面层级、标题、说明与操作区。
- `AppMetricPill`：紧凑型数量和状态摘要。
- `AppEmptyState`：空数据、完成状态和下一步操作。

## 基本规则

- 页面背景、文字、边框、状态色不得在新页面中重复定义十六进制颜色，应使用 `--color-*` 令牌。
- 普通卡片统一使用 `--radius-lg`、`--shadow-sm` 和 `--color-border`。
- 普通控件高度为 `--control-height`，紧凑控件高度为 `--control-height-sm`。
- 危险操作只使用 danger；需要注意但可继续的状态使用 warning；主流程动作使用 primary。
- 表格、筛选栏和批量操作栏应放在同一表面容器中，移动端操作按钮最小高度 42px。
- 高频交互只保留快速颜色和按压反馈；弹窗、抽屉和 Toast 使用 180-220ms 的进入过渡，并支持减少动态效果。
