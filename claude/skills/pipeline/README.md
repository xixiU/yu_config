# Pipeline Skill

通过 SSH 管理远程服务器上的应用，支持 Java 和前端项目的状态查看与重新部署。

## 用法

`{env}` 和 `{app}` 均可省略，会自动推断：

```
/pipeline {action}                 # env 用 default_env，app 从当前目录名推断
/pipeline {app} {action}           # env 用 default_env
/pipeline {env} {app} {action}     # 完整写法
```

**示例：**
```
/pipeline redeploy                 # 在项目目录下直接用
/pipeline ts-service status
/pipeline dev ts-service redeploy
```

## 配置

编辑 `~/.claude/skills/pipeline/config.json`：

```json
{
  "default_env": "dev",
  "environments": {
    "dev": {
      "ssh_user": "root",
      "ssh_host": "192.168.1.100",
      "ssh_port": 22,
      "ssh_key": "~/.ssh/id_rsa",
      "java_home": "/usr/java/jdk1.8.0_361"
    }
  },
  "apps": {
    "ts-service": {
      "type": "java",
      "env": "dev",
      "port": 8686,
      "remote_path": "/home/ts-service",
      "local_path": "backend",
      "jar_pattern": "ts-service*.jar"
    },
    "web-trial": {
      "type": "frontend",
      "env": "dev",
      "remote_path": "/home/nginx/html/web-trial",
      "local_path": "frontend/web-Trial",
      "pkg_manager": "npm",
      "build_cmd": "build",
      "dist_dir": "dist"
    }
  }
}
```

添加新应用只需在 `apps` 下新增条目，通过 `type` 区分类型。

## 应用类型

### `type: "java"`
| 字段 | 说明 |
|------|------|
| `port` | 应用监听端口，用于 status 检查 |
| `remote_path` | 服务器上的应用目录（含 restart.sh） |
| `local_path` | 本地 Maven 项目路径 |
| `jar_pattern` | jar 文件匹配模式，如 `ts-service*.jar` |

redeploy 流程：本地 `mvn clean package` → scp 上传 jar → SSH 执行 `restart.sh` → 验证端口

### `type: "frontend"`
| 字段 | 说明 | 默认值 |
|------|------|--------|
| `remote_path` | Nginx 静态文件目录 | — |
| `local_path` | 本地前端项目路径 | — |
| `pkg_manager` | 包管理器：`npm` 或 `pnpm` | `npm` |
| `build_cmd` | build 脚本名 | `build` |
| `dist_dir` | 构建产物目录 | `dist` |

redeploy 流程：本地 install → build → 清空远程目录 → scp 上传 dist → 验证文件存在

## SSH 认证

优先使用 `ssh_key` 密钥认证；失败时提示输入密码，并询问是否保存到配置文件（`ssh_password` 字段）。

## Java 环境

`java_home`（可选）：指定服务器上的 JDK 路径，配置后执行 `restartup.sh` 时会自动注入 `JAVA_HOME` 和 `PATH`。

- 填了 → `export JAVA_HOME={java_home} && export PATH={java_home}/bin:$PATH`，精确可控
- 不填 → 用 `bash -l` 加载服务器 login shell 环境作为兜底

如果服务器 `~/.bash_profile` 里已经配好了 Java 路径，可以不填；否则建议填上避免 `java: 没有那个文件或目录` 报错。

## 服务器要求

- Java 应用：`remote_path` 下需有可执行的 `restart.sh`
- 前端应用：`remote_path` 需为 Nginx 已配置的静态目录，确保写入权限
