# Contributing to Zhijian MetaAssessment / 贡献指南

感谢您为“知见”元认知测评系统提供改进。为保护研究数据、参与者隐私和项目的双重许可能力，请在提交贡献前阅读以下规则。

## 1. 开始之前

- 对较大的功能、数据结构或研究流程调整，请先创建 Issue 说明目标与影响范围。
- 不要在 Issue、Pull Request、测试样例或提交历史中上传真实录音、转录、问卷、姓名、微信名、账号密码、API Key、数据库备份或其他敏感数据。
- 新增依赖、模型、字体、图片或数据集时，必须说明来源、版本和许可证。
- 涉及测评协议、心理测量解释、隐私、安全或许可的修改，需要额外审查。

## 2. 贡献许可

除非另有书面约定，您提交并获接受的贡献将依据本仓库的 AGPL-3.0 许可证提供；该贡献不会自动授权项目所有者将其纳入闭源商业版本。

您必须确认自己有权提交相关内容。如果您的雇主、学校、客户或其他组织可能拥有相关权利，请在提交前取得必要授权。

## 3. 开发与验证

```powershell
# 启动本地环境
./dev.ps1 -OpenBrowser

# 前端构建
cd frontend
pnpm build

# 后端测试
cd ../backend
./.venv/Scripts/python.exe -m unittest discover -s tests -p "test_*.py" -v
```

请为行为变更补充相应测试，并确保数据库迁移保持幂等。不要覆盖 ASR 原文、AI 结果、专家原始编码或历史模型版本。

## 4. Pull Request 要求

- 标题清楚说明变更目的；
- 描述问题、实现方式、测试结果和部署影响；
- 数据库变更应列出迁移与回滚注意事项；
- UI 变更应说明桌面端和移动端验证情况；
- 不混入无关格式化、构建产物、虚拟环境、依赖目录或导出压缩包；
- 确认有权依据 AGPL-3.0 提交相关贡献。

## 5. 许可证

被接受的外部贡献将依据 [AGPL-3.0](LICENSE) 发布。项目所有者签发的单独商业许可证只覆盖其有权进行商业许可的代码和材料，详情见 [商业许可说明](COMMERCIAL_LICENSE.md)。

---

Thank you for contributing. Do not submit real participant data, credentials, secrets, confidential information, or third-party material without a compatible license. Unless separately agreed in writing, accepted external contributions are provided under AGPL-3.0 and are not automatically covered by the Project Owner's proprietary commercial licenses.
