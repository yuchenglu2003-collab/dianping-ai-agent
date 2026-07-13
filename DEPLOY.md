# 云端部署（Streamlit Community Cloud）

## 已准备好的文件

| 文件 | 作用 |
|------|------|
| `src/ui/app.py` | Main file path |
| `requirements.txt` | Python 依赖 |
| `packages.txt` | 系统字体（中文词云） |
| `runtime.txt` | Python 3.11 |
| `.streamlit/config.toml` | 服务端配置 |
| `.streamlit/secrets.toml.example` | Secrets 模板 |

## 重要：必须手动选 Python 版本

Streamlit Cloud **不会读** `runtime.txt`。

日志里如果是 `Using Python 3.14.x`，装包会卡住/失败。

### 正确做法

1. 打开 https://share.streamlit.io → 删掉当前 App（或 New app 重新部署）
2. **New app** → 选仓库 `dianping-ai-agent`
3. Main file path：`src/ui/app.py`
4. 点 **Advanced settings**
5. **Python version 选 `3.12`（或 `3.11`）**，不要用默认 3.14
6. Secrets 粘贴：

```toml
DEEPSEEK_API_KEY = "sk-你的密钥"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL = "deepseek-chat"
```

7. Deploy

若已在装包卡住：先 **Reboot 无效**，请删除 App 后按上面用 3.12 重部署。

### 依赖装包失败？

1. 点 **Manage app** → 看终端最后出现的 `ERROR:` / `No matching distribution`
2. 仓库已删除 `packages.txt`（apt 失败也会显示成 requirements 错误）
3. `requirements.txt` 已改为精简锁定版本；推送后点 **Reboot app**
