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

## 你需要完成的 3 步

### 1. 登录 GitHub（本机终端执行）

```bash
gh auth login
```

按提示用浏览器完成授权后告诉我，我会帮你：创建仓库 → 推送代码 → 给出部署链接。

或手动：在 GitHub 新建空仓库，然后：

```bash
cd "/Users/lyc/Desktop/美团ai-agent"
git init
git add .
git commit -m "Prepare Streamlit cloud deploy"
git branch -M main
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main
```

### 2. 在 Streamlit Cloud 新建应用

1. 打开 https://share.streamlit.io 并用 GitHub 登录
2. **New app**
3. 选择刚推送的仓库
4. **Main file path** 填：`src/ui/app.py`
5. **Advanced settings → Secrets** 粘贴：

```toml
DEEPSEEK_API_KEY = "sk-你的真实密钥"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL = "deepseek-chat"
```

6. 点 **Deploy**

### 3. 等待构建

首次安装依赖约 3–8 分钟。成功后会得到类似：

`https://xxx.streamlit.app`

### 依赖装包失败？

常见原因是 `xgboost` / `gensim` / `kaleido` 过重。仓库已将云端依赖裁剪到 `requirements.txt`。

修改并推送后，在 Streamlit Cloud 点 **Reboot app** / **Rerun**。
