---
name: pipeline
description: "Manage remote application deployments. Usage: /pipeline [env] [app] status|redeploy. Env and app are optional — defaults to config default_env and current directory name. Supports Java (Maven+jar) and frontend (Node build+Nginx) deployments via SSH."
---

# Pipeline - Remote App Management

## Language

All output to the user MUST be in Chinese. This includes status messages, error messages, step results, prompts, and summaries. Only keep technical values (file paths, commands, hostnames, timestamps) in their original form.

## Invocation

Args are flexible — all of `{env}`, `{app}` are optional and will be inferred:

```
/pipeline {action}                   # infer env + app
/pipeline {app} {action}             # infer env
/pipeline {env} {app} {action}       # fully explicit
```

Examples:
- `/pipeline redeploy`               — infer env from default_env, infer app from cwd
- `/pipeline ts-service redeploy`    — infer env from default_env
- `/pipeline dev ts-service redeploy`

## Step 0: Load Config

Read `~/.claude/skills/pipeline/config.json`. If missing, create the template below and tell the user to fill it in, then stop.

Template to create if missing:
```json
{
  "default_env": "dev",
  "environments": {
    "dev": {
      "ssh_user": "root",
      "ssh_host": "192.168.1.100",
      "ssh_port": 22,
      "ssh_key": "~/.ssh/id_rsa"
    }
  },
  "apps": {
    "example-java-app": {
      "type": "java",
      "env": "dev",
      "port": 8080,
      "remote_path": "/home/app/example-java-app",
      "local_path": "backend",
      "jar_pattern": "*.jar"
    },
    "example-frontend-app": {
      "type": "frontend",
      "env": "dev",
      "remote_path": "/home/nginx/html/example-frontend-app",
      "local_path": "frontend/example-frontend-app",
      "pkg_manager": "npm",
      "build_cmd": "build",
      "dist_dir": "dist"
    }
  }
}
```

## Step 1: Parse Args

The action is always the last word. Remaining words before it are `{env}` and/or `{app}`.

Parse rules:
1. Last arg = `{action}`. Must be `status` or `redeploy`, else show usage and stop.
2. If 2 args remain before action → first is `{env}`, second is `{app}`.
3. If 1 arg remains → it is `{app}`, env will be inferred.
4. If 0 args remain → both env and app will be inferred.

### Infer `{app}`

If `{app}` not provided:
1. Get current working directory name:
   ```bash
   basename $(pwd)
   ```
2. Check if that name exists as a key in `config.apps`.
3. If yes → use it as `{app}`, tell the user: `Inferred app: {app} (from cwd)`.
4. If no → ask the user to choose from the list of available apps, then stop until answered.

### Infer `{env}`

If `{env}` not provided:
1. Check `app_config.env` — if set, use it.
2. Else use `config.default_env`.
3. Tell the user: `Using env: {env}`.

### Validate

- If resolved `{app}` not in `config.apps` → list available apps and stop.
- If resolved `{env}` not in `config.environments` → list available envs and stop.

Look up:
- `app_config = config.apps[{app}]`
- `env_config = config.environments[{env}]`
- `app_type = app_config.type` — either `"java"` or `"frontend"`

## SSH Authentication Strategy

Try SSH key first. If key auth fails (permission denied), fall back to password:
- Key auth: `ssh -i {ssh_key} -p {ssh_port} -o StrictHostKeyChecking=no -o ConnectTimeout=10`
- Password fallback: use `sshpass -p {password}` prefix — check if `sshpass` is available first. If not, prompt user to install it or enter password manually.
- If password is used successfully, ask user if they want to save it to the config (`ssh_password` field) for future use.

SCP opts mirror SSH opts (replace `ssh` with `scp -P {ssh_port}`).

---

## Action: status

### Java app (`type: "java"`)
Check if the port is listening:
```bash
ssh {ssh_opts} {ssh_user}@{ssh_host} "ss -tlnp | grep :{port} && echo RUNNING || echo NOT_RUNNING"
```

### Frontend app (`type: "frontend"`)
Check if the remote_path directory exists and is non-empty (Nginx serves static files, no port to check):
```bash
ssh {ssh_opts} {ssh_user}@{ssh_host} "[ -d {remote_path} ] && ls {remote_path} | wc -l | xargs -I{} sh -c 'if [ {} -gt 0 ]; then echo DEPLOYED; else echo EMPTY; fi' || echo NOT_FOUND"
```
Also show the last modified time of the directory:
```bash
ssh {ssh_opts} {ssh_user}@{ssh_host} "stat -c '%y' {remote_path} 2>/dev/null || echo unknown"
```

Report: app name, env, host, remote_path, and status (DEPLOYED / EMPTY / NOT_FOUND).

---

## Action: redeploy

Execute steps in order, stopping on any failure. Show each step result.

---

### Java app (`type: "java"`)

#### 1. Smart Build Check

Find the existing jar first:
```bash
find {local_path}/target -name "{jar_pattern}" ! -name "*sources*" ! -name "*javadoc*" | sort | tail -1
```

If a jar exists, get its modification timestamp:
```bash
stat -c '%Y' {jar_file}
```

Then check if any source file was modified after the jar:
```bash
find {local_path}/src -newer {jar_file} -type f | head -5
```

Also check `pom.xml`:
```bash
find {local_path} -maxdepth 1 -name "pom.xml" -newer {jar_file} | head -1
```

**Decision:**
- If no jar exists → must build.
- If any source file or pom.xml is newer than the jar → must build. Show the changed files (up to 5) to the user.
- If jar exists and no source changes detected → skip build, tell the user: `⚡ Skipping build — no source changes since last jar (built at {jar_time})`. Proceed directly to step 3.

#### 2. Maven Build (only if needed)
```bash
cd {local_path} && mvn clean package -DskipTests
```
Resolve `local_path` relative to current working directory if not absolute.

#### 3. Find JAR
```bash
find {local_path}/target -name "{jar_pattern}" ! -name "*sources*" ! -name "*javadoc*" | sort | tail -1
```
Stop if no jar found.

#### 4. Upload JAR via SCP
```bash
scp {scp_opts} {jar_file} {ssh_user}@{ssh_host}:{remote_path}/
```

#### 5. Run Restart Script

If `env_config.java_home` is set, prepend the PATH before running the script:
```bash
ssh {ssh_opts} {ssh_user}@{ssh_host} "export JAVA_HOME={java_home} && export PATH={java_home}/bin:$PATH && cd {remote_path} && sh ./restartup.sh"
```

Otherwise use `bash -l` to load the login shell environment:
```bash
ssh {ssh_opts} {ssh_user}@{ssh_host} "bash -l -c 'cd {remote_path} && sh ./restartup.sh'"
```

#### 6. Verify
Wait 3 seconds, then run **status** to confirm the port is up.

---

### Frontend app (`type: "frontend"`)

#### 1. Smart Build Check

Check if dist directory exists and is non-empty:
```bash
ls {local_path}/{dist_dir} 2>/dev/null | wc -l
```

If dist exists, get the newest file's timestamp in dist:
```bash
find {local_path}/{dist_dir} -type f | xargs stat -c '%Y' 2>/dev/null | sort -n | tail -1
```

Then check if any source file was modified after the dist:
```bash
find {local_path}/src -newer {local_path}/{dist_dir} -type f | head -5
```

Also check config files:
```bash
find {local_path} -maxdepth 1 \( -name "package.json" -o -name "vite.config.*" -o -name "vue.config.*" -o -name ".env*" \) -newer {local_path}/{dist_dir} | head -5
```

**Decision:**
- If dist is missing or empty → must build.
- If any `src/` file or config file is newer than dist → must build. Show changed files (up to 5).
- If dist exists and no source changes → skip install + build, tell the user: `⚡ Skipping build — no source changes since last dist`. Proceed directly to step 4.

#### 2. Install Dependencies (only if building)
Use `pkg_manager` field (default: `npm`):
```bash
cd {local_path} && {pkg_manager} install
```

#### 3. Build (only if building)
```bash
cd {local_path} && {pkg_manager} run {build_cmd}
```
`build_cmd` defaults to `"build"`. Stop if build fails.

#### 4. Verify dist exists (local)
```bash
ls {local_path}/{dist_dir}
```
`dist_dir` defaults to `"dist"`. Stop if directory is missing or empty.

#### 5. Clear remote directory
```bash
ssh {ssh_opts} {ssh_user}@{ssh_host} "rm -rf {remote_path}/* && echo cleared"
```

#### 6. Upload dist via SCP
```bash
scp -r {scp_opts} {local_path}/{dist_dir}/* {ssh_user}@{ssh_host}:{remote_path}/
```

#### 7. Verify
Run **status** to confirm the remote directory is non-empty.

---

## Output Format

Always show a clear summary:
```
[pipeline] {env}/{app} ({type}) @ {ssh_host}
Status: RUNNING / DEPLOYED / STOPPED / NOT_FOUND / FAILED
```
For redeploy, list each step with ✓ or ✗.
