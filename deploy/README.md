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

公网回调地址：`https://op-fantasy-bot.branta.dev/qq/webhook`。
Nginx 配置见 `deploy/nginx.conf`，服务器安装位置为
`/www/server/panel/vhost/nginx/op-fantasy-bot.branta.dev.conf`。
只代理精确的 `/qq/webhook` 路径，保留请求体和签名相关请求头；其他 HTTPS 路径返回 404。
证书由 Certbot webroot 签发，验证目录为 `/www/wwwroot/op-fantasy-bot.branta.dev`，
通过现有 `certbot-renew.timer` 自动续期。部署 hook 使用 `/usr/bin/nginx` 检查并重载配置。

已验证公网 TLS、缺少 AppID 时的 403 响应，以及 QQ Webhook challenge 的响应签名。
仍需在 QQ 开放平台填写上述回调地址并订阅群聊 @ 消息事件，在测试群验证
`@机器人 我的身份` 与作业收发。将返回的应用级成员身份配置到 `GW_ADMINS` 后重启服务，
管理员才可设置作业；官方成员 OpenID 不能直接使用 QQ 号替代。

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
