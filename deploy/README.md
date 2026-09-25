# CentOS Stream 9 部署

服务器目录：`/srv/op-fantasy-guild-war-bot`。
服务名：`op-fantasy-guild-war-bot`。
Python 3.11 虚拟环境：项目内 `.venv`。
部署分支：`codex/qq-official-deploy`。

进程以专用用户 `guildwar-bot` 运行，监听 `127.0.0.1:18080`。
源码和虚拟环境由 root 管理，运行用户仅可写入 `data` 目录。

## 配置与检查

编辑服务器项目目录中的 `.env`，填入 `QQ_BOTS` 和 `GW_ADMINS`。
没有官方凭据时使用 `QQ_BOTS=[]`：服务可启动，但不会接收实际 QQ 应用的事件。
配置文件权限应为 `root:guildwar-bot`、`0640`，不要将密钥提交进 Git。

```bash
systemctl restart op-fantasy-guild-war-bot
systemctl status op-fantasy-guild-war-bot --no-pager
journalctl -u op-fantasy-guild-war-bot -n 80 --no-pager
curl -i -X POST http://127.0.0.1:18080/qq/webhook -H 'Content-Type: application/json' -d '{}'
```

最后一个请求没有 AppID，预期返回 `403 Missing X-Bot-Appid header`，用于确认官方适配器路由可达。
它不等价于 QQ 实际联调通过。

需要为一个明确指定的域名配置 HTTPS 反向代理，转发 `/qq/webhook` 到
`http://127.0.0.1:18080/qq/webhook`，保留请求体和签名相关请求头。
公网回调和 QQ 后台设置完成后，再在测试群中验证 `@机器人 我的身份` 与作业收发。

## 更新

确认发布分支包含要部署的修改后，以 root 执行：

```bash
cd /srv/op-fantasy-guild-war-bot
git status --short
git pull --ff-only origin codex/qq-official-deploy
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
systemctl restart op-fantasy-guild-war-bot
systemctl status op-fantasy-guild-war-bot --no-pager
```

有数据结构变更时，先停止服务并备份整个 `data` 目录，再更新。
`.env` 和 `data` 不受 Git 更新覆盖。
需要修改 unit 时，将仓库中的 `.service` 文件复制到 `/etc/systemd/system/`，
执行 `systemctl daemon-reload` 后重启服务。
