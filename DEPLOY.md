# 部署指南

针对 **甲骨文云 ARM + Debian 12 + AMH面板 + MySQL 5.7** 环境优化。

---

## 一、前置准备

### 1.1 安装系统依赖

```bash
apt update
apt install -y python3-pip python3-venv python3-dev build-essential pkg-config curl wget git
```

### 1.2 创建专用 MySQL 数据库和用户

```bash
mysql -h 127.0.0.1 -P 3306 -u root -p
```

进入 mysql 后执行（**自己想个强密码代替 YOUR_STRONG_PASSWORD**）：

```sql
CREATE DATABASE gupiao
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER 'gupiao_app'@'127.0.0.1' IDENTIFIED BY 'YOUR_STRONG_PASSWORD';

GRANT ALL PRIVILEGES ON gupiao.* TO 'gupiao_app'@'127.0.0.1';
FLUSH PRIVILEGES;

EXIT;
```

### 1.3 验证数据库可用

```bash
mysql -h 127.0.0.1 -P 3306 -u gupiao_app -p -e "SELECT VERSION();"
```

---

## 二、部署应用

### 2.1 克隆代码（或上传）

```bash
mkdir -p /opt/gupiao
cd /opt/gupiao
# 方式A：从 git 拉
git clone <your-repo-url> .
# 方式B：直接上传 v2/ 目录到 /opt/gupiao

# 进入项目目录（v2 文件夹是项目根）
cd v2
```

### 2.2 创建虚拟环境并安装依赖

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

ARM架构 + 纯 Python 包（PyMySQL），不需要编译，5分钟以内完成。

### 2.3 配置 .env

```bash
cp .env.example .env
nano .env
```

修改以下字段：

```ini
TUSHARE_TOKEN=你的tushare实际token
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=gupiao_app
MYSQL_PASSWORD=你刚才设置的密码
MYSQL_DATABASE=gupiao

WEB_HOST=0.0.0.0
WEB_PORT=8000
DEBUG=false
```

### 2.4 测试启动

```bash
# 在 venv 已激活的状态
python -m app.main
```

看到 `MySQL 连接正常` 和 `启动完成` 即成功。

按 `Ctrl+C` 停止。

---

## 三、放行端口

### 3.1 iptables 放行 8000

```bash
iptables -I INPUT -p tcp --dport 8000 -j ACCEPT

# 持久化（避免重启失效）
apt install -y iptables-persistent
netfilter-persistent save
```

### 3.2 甲骨文云控制台开放端口

1. 登录甲骨文云
2. 网络 → 虚拟云网络 → 你的VCN → 安全列表 → 默认安全列表
3. 添加入站规则：
   - **来源 CIDR**：`0.0.0.0/0`
   - **IP 协议**：TCP
   - **目标端口范围**：`8000`
   - **描述**：股票分析系统

### 3.3 测试访问

浏览器打开：
```
http://你的服务器公网IP:8000
```

应该能看到黑底主题的网页。

---

## 四、配置 systemd 开机自启

### 4.1 创建 service 文件

```bash
nano /etc/systemd/system/gupiao.service
```

填入（**注意修改 WorkingDirectory 和 User**）：

```ini
[Unit]
Description=Gupiao Stock Analysis System v2.0
After=network.target mysql.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/gupiao/v2
Environment="PATH=/opt/gupiao/v2/venv/bin"
ExecStart=/opt/gupiao/v2/venv/bin/python -m app.main
Restart=on-failure
RestartSec=10
StandardOutput=append:/opt/gupiao/v2/logs/systemd.log
StandardError=append:/opt/gupiao/v2/logs/systemd.log

[Install]
WantedBy=multi-user.target
```

### 4.2 启用并启动

```bash
systemctl daemon-reload
systemctl enable gupiao
systemctl start gupiao
systemctl status gupiao
```

看到 `Active: active (running)` 即成功。

### 4.3 查看日志

```bash
# 应用日志
tail -f /opt/gupiao/v2/logs/app.log

# systemd 日志
journalctl -u gupiao -f
```

### 4.4 常用命令

```bash
systemctl restart gupiao   # 重启
systemctl stop gupiao      # 停止
systemctl status gupiao    # 状态
```

---

## 五、首次数据初始化

### 5.1 浏览器打开 → 设置 Tab

```
http://你的IP:8000/settings
```

### 5.2 点击"一键初始化"

- 系统会创建所有表
- 拉取全市场股票元信息
- 拉取近 500 个交易日的全部数据（日线、基本面、资金流、复权因子）
- 拉取核心指数数据

**预计耗时 30~60 分钟**。期间页面会实时显示进度和日志。

### 5.3 验证

完成后到"设置"页面看"数据库状态"，应该有：
- 股票数：约 5300
- 日线记录：约 250 万
- 资金流记录：约 130 万
- 最新数据：今天或最近交易日

---

## 六、可选：通过 AMH 配域名 + HTTPS

### 6.1 在 AMH 面板添加站点

- 进入 AMH 网站管理
- 新建站点（域名指向你的服务器IP）
- 不需要 PHP，纯反向代理

### 6.2 配置 nginx 反代（关键配置）

编辑 `/usr/local/nginx/conf/vhost/你的域名.conf`，**核心反代规则**：

```nginx
# 主反代
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;

    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # WebSocket 兼容（虽然本项目不用WS，但保险起见）
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}

# 重要：SSE 流式响应（一键初始化进度推送依赖这个）
location /api/admin/init {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;

    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

    # SSE 关键设置：禁用缓冲
    proxy_buffering off;
    proxy_cache off;

    # 长连接超时（初始化要跑1小时）
    proxy_read_timeout 7200s;
    proxy_send_timeout 7200s;

    # 不让 nginx 修改响应
    chunked_transfer_encoding on;
    proxy_set_header Connection '';
}

# 静态资源缓存（提速）
location /static/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_cache_valid 200 1h;
    expires 1h;
    add_header Cache-Control "public, immutable";
}
```

重载 nginx：
```bash
nginx -t && nginx -s reload
```

### 6.3 申请 Let's Encrypt 证书（AMH 自带工具）

按 AMH 面板指引操作即可。配好后 https://你的域名 直接可用。

### 6.4 反代后的访问入口

- HTTP: `http://你的域名` → 自动跳转 HTTPS
- HTTPS: `https://你的域名`
- 安全列表里 8000 端口可以**关闭**（因为外部不直连了）

---

## 七、故障排查

### MySQL 连接失败

```bash
# 测试 MySQL 是否运行
systemctl status mysqld 2>/dev/null || systemctl status mysql

# 测试用户能否登录
mysql -h 127.0.0.1 -P 3306 -u gupiao_app -p

# 看应用日志
tail -100 /opt/gupiao/v2/logs/app.log
```

### tushare 调用失败

检查：
1. token 是否正确填入 `.env`
2. 网络能否访问：`curl -I https://api.tushare.pro`
3. 调用频率是否撞上限：日志里搜索"频率超限"
4. 积分是否够（5000积分支持本系统所有接口）

### Web 服务无法访问

1. `systemctl status gupiao` 看应用是否启动
2. `ss -tlnp | grep 8000` 看端口是否监听
3. `iptables -L INPUT -n | grep 8000` 看防火墙是否放行
4. 甲骨文云控制台确认安全列表已开 8000

### 调度任务没跑

```bash
# 查看任务日志
grep "调度器\|批" /opt/gupiao/v2/logs/app.log

# 系统时区是否正确
date
timedatectl
```

时区必须是 `Asia/Shanghai (CST, +0800)`，否则定时任务时间会错。

---

## 八、备份建议

### 8.1 数据库备份

每周备份一次：

```bash
# 创建备份目录
mkdir -p /opt/backups

# 写一个备份脚本
cat > /opt/backups/backup_gupiao.sh << 'EOF'
#!/bin/bash
DATE=$(date +%Y%m%d)
mysqldump -h 127.0.0.1 -u gupiao_app -p'YOUR_PASSWORD' \
  --single-transaction --quick \
  gupiao | gzip > /opt/backups/gupiao_${DATE}.sql.gz

# 保留最近 4 周
find /opt/backups -name "gupiao_*.sql.gz" -mtime +28 -delete
EOF
chmod +x /opt/backups/backup_gupiao.sh

# 添加每周日凌晨3点备份
crontab -e
# 添加这一行：
# 0 3 * * 0 /opt/backups/backup_gupiao.sh
```

### 8.2 代码与配置备份

`.env` 文件包含密码，单独保管：
```bash
cp /opt/gupiao/v2/.env ~/.gupiao.env.backup
```

---

## 九、升级流程

```bash
cd /opt/gupiao
git pull   # 或重新上传代码
cd v2
source venv/bin/activate
pip install -r requirements.txt --upgrade
systemctl restart gupiao
```

数据库表结构有更新时，重新点击"一键初始化"会自动 `CREATE TABLE IF NOT EXISTS`，
旧表数据保留。

---

## 十、性能预估（基于你的环境）

| 项目 | 预估 |
|---|---|
| 内存占用 | 200~500 MB（5.8GB 内存绰绰有余）|
| CPU 占用 | 平时 < 5%，分析时 50~80% |
| 磁盘占用 | < 2GB（30GB 可用磁盘绰绰有余） |
| 首次初始化耗时 | 30~60 分钟 |
| 每日增量更新耗时 | 5~10 分钟（5次接口调用） |
| 全市场分析耗时 | 3~5 分钟（5300只票） |
| Web 响应时间 | < 100ms（带索引查询） |

---

## 完成。 

如有问题，按"故障排查"章节逐项检查。
