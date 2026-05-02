# Discuz 自动回复 Agent：HTTP 模拟登录路线实现说明

> 目标：通过模拟普通用户登录 Discuz 前台页面，自动读取任务队列并以机器人账号回帖。
> 路线：`requests.Session` 登录 → 保存 Cookie → 解析 `formhash` → POST 回复表单 → 校验回复是否成功。
> 注意：本方案不改 Discuz 源码，不写 Discuz 内部接口，不直接插入 `forum_post` 表。

---

## 1. 项目目标

实现一个可运行的 Discuz 自动回复 Agent，具备以下能力：

1. 使用机器人账号登录 Discuz。
2. 持久化 Cookie，避免频繁登录。
3. 从任务表读取待回复任务。
4. 打开帖子页面，解析当前页面中的 `formhash`。
5. 使用 Discuz 前台回复接口提交回复。
6. 提交后校验回复是否真的出现在帖子页面。
7. 记录任务状态、错误原因、重试次数。
8. 单账号串行执行，避免并发导致登录态或表单状态混乱。

---

## 2. 技术栈

建议使用：

```text
Python 3.10+
requests
beautifulsoup4
pymysql
python-dotenv
filelock
loguru
```

安装依赖：

```bash
pip install requests beautifulsoup4 pymysql python-dotenv filelock loguru
```

---

## 3. 推荐目录结构

```text
discuz-auto-reply-agent/
  README.md
  .env.example
  requirements.txt
  main.py
  config.py
  db.py
  discuz_client.py
  worker.py
  agent.py
  models.py
  utils.py
  cookies/
    .gitkeep
  logs/
    .gitkeep
  sql/
    create_tables.sql
```

---

## 4. 环境变量

创建 `.env`：

```env
DISCUZ_BASE_URL=https://example.com
DISCUZ_USERNAME=bot_user
DISCUZ_PASSWORD=bot_password

DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=discuz_user
DB_PASSWORD=your_password
DB_NAME=discuz_db
DB_CHARSET=utf8mb4

BOT_COOKIE_FILE=cookies/bot_user.cookies.json
BOT_LOCK_FILE=bot_user.lock

WORKER_SLEEP_SECONDS=3
MAX_RETRY_COUNT=3
```

---

## 5. 数据表设计

### 5.1 自动回复任务表

```sql
CREATE TABLE IF NOT EXISTS bot_reply_jobs (
  id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  tid INT UNSIGNED NOT NULL,
  fid INT UNSIGNED NOT NULL,
  source_pid INT UNSIGNED DEFAULT NULL,
  source_authorid INT UNSIGNED DEFAULT NULL,
  source_subject VARCHAR(255) DEFAULT '',
  source_message MEDIUMTEXT,
  reply_message MEDIUMTEXT NOT NULL,
  status TINYINT NOT NULL DEFAULT 0,
  retry_count INT UNSIGNED NOT NULL DEFAULT 0,
  last_error TEXT,
  created_at INT UNSIGNED NOT NULL,
  updated_at INT UNSIGNED NOT NULL,
  UNIQUE KEY uniq_source_pid (source_pid),
  KEY idx_status_created (status, created_at),
  KEY idx_tid (tid)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

状态说明：

```text
0 = 待发送
1 = 发送中
2 = 已发送
3 = 失败，可重试
4 = 放弃
```

---

## 6. 核心流程

```text
启动 worker
  ↓
加载配置
  ↓
加载 cookie
  ↓
检测登录态
  ↓
未登录则执行登录
  ↓
循环读取待处理任务
  ↓
加账号锁
  ↓
打开帖子页面
  ↓
解析 formhash
  ↓
提交回复
  ↓
重新打开帖子页面校验
  ↓
更新任务状态
```

---

## 7. DiscuzClient 设计

文件：`discuz_client.py`

### 7.1 类职责

`DiscuzClient` 负责所有 Discuz 前台 HTTP 交互：

1. 维护 `requests.Session`。
2. 加载和保存 Cookie。
3. 判断是否已登录。
4. 登录账号。
5. 获取帖子页面。
6. 解析 `formhash`。
7. 提交回复。
8. 校验回复是否成功。

---

### 7.2 方法设计

```python
class DiscuzClient:
    def __init__(self, base_url: str, username: str, password: str, cookie_file: str):
        pass

    def load_cookies(self) -> None:
        pass

    def save_cookies(self) -> None:
        pass

    def is_logged_in(self) -> bool:
        pass

    def login(self) -> None:
        pass

    def ensure_logged_in(self) -> None:
        pass

    def get_thread_page(self, tid: int) -> str:
        pass

    def extract_formhash(self, html: str) -> str:
        pass

    def reply_thread(self, fid: int, tid: int, message: str) -> str:
        pass

    def verify_reply(self, tid: int, message: str) -> bool:
        pass
```

---

## 8. HTTP 请求细节

### 8.1 登录页

通常入口：

```text
/member.php?mod=logging&action=login
```

流程：

1. `GET` 登录页。
2. 从 HTML 中解析 `formhash`。
3. `POST` 登录表单。
4. 保存 Cookie。
5. 再访问首页或用户页确认登录状态。

### 8.2 回复帖子

通常入口：

```text
/forum.php?mod=post&action=reply&fid={fid}&tid={tid}&replysubmit=yes
```

常见表单字段：

```text
formhash
message
subject
usesig
replysubmit
```

建议提交：

```python
payload = {
    "formhash": formhash,
    "message": message,
    "subject": "",
    "usesig": "1",
    "replysubmit": "true",
}
```

不同模板或版本可能需要额外字段，例如：

```text
posttime
wysiwyg
handlekey
inajax
infloat
```

实现时应保留可扩展字段。

---

## 9. Cookie 持久化

```python
import json
import requests


def save_cookies(session: requests.Session, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(requests.utils.dict_from_cookiejar(session.cookies), f, ensure_ascii=False, indent=2)


def load_cookies(session: requests.Session, path: str) -> None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            cookies = json.load(f)
        session.cookies.update(cookies)
    except FileNotFoundError:
        return
```

---

## 10. 登录态检测

登录态检测不要只看 HTTP 200。

建议方式：

1. 访问首页。
2. 判断页面是否包含用户名。
3. 判断是否出现退出链接。
4. 判断是否仍出现登录表单。

示例逻辑：

```python
def is_logged_in(self) -> bool:
    url = f"{self.base_url}/forum.php"
    r = self.session.get(url, timeout=15)
    r.raise_for_status()

    html = r.text
    if self.username in html and "mod=logging&action=logout" in html:
        return True

    return False
```

---

## 11. formhash 解析

`formhash` 可能出现在：

1. `<input name="formhash" value="...">`
2. JS 变量中
3. 页面链接参数中

优先从 input 中取：

```python
from bs4 import BeautifulSoup
import re


def extract_formhash(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    item = soup.find("input", {"name": "formhash"})
    if item and item.get("value"):
        return item["value"]

    match = re.search(r"formhash=([a-zA-Z0-9]+)", html)
    if match:
        return match.group(1)

    raise RuntimeError("formhash not found")
```

---

## 12. 回复提交

```python
def reply_thread(self, fid: int, tid: int, message: str) -> str:
    html = self.get_thread_page(tid)
    formhash = self.extract_formhash(html)

    url = (
        f"{self.base_url}/forum.php"
        f"?mod=post&action=reply&fid={fid}&tid={tid}&replysubmit=yes"
    )

    payload = {
        "formhash": formhash,
        "message": message,
        "subject": "",
        "usesig": "1",
        "replysubmit": "true",
    }

    headers = {
        "Referer": f"{self.base_url}/forum.php?mod=viewthread&tid={tid}",
        "User-Agent": self.user_agent,
    }

    r = self.session.post(url, data=payload, headers=headers, timeout=30)
    r.raise_for_status()
    return r.text
```

---

## 13. 回复结果校验

不要只判断提交请求成功。必须重新打开帖子页校验。

```python
def verify_reply(self, tid: int, message: str) -> bool:
    html = self.get_thread_page(tid)
    snippet = message.strip()[:30]
    return snippet in html
```

如果帖子分页很多，首页可能看不到最后回复。可以：

1. 访问 `&extra=page%3D1`。
2. 访问最后一页。
3. 使用 `author=bot_user` 和内容片段一起判断。

基础版先用内容片段判断。

---

## 14. Worker 设计

文件：`worker.py`

职责：

1. 从数据库取一条待发送任务。
2. 将任务状态改为发送中。
3. 调用 `DiscuzClient` 发送回复。
4. 校验成功后标记已发送。
5. 失败则记录错误和重试次数。

### 14.1 取任务 SQL

```sql
SELECT *
FROM bot_reply_jobs
WHERE status IN (0, 3)
  AND retry_count < %s
ORDER BY created_at ASC
LIMIT 1
FOR UPDATE;
```

### 14.2 Worker 循环

```python
while True:
    job = fetch_next_job()

    if not job:
        time.sleep(WORKER_SLEEP_SECONDS)
        continue

    try:
        process_job(job)
    except Exception as e:
        mark_failed(job["id"], str(e))
```

---

## 15. 单账号锁

同一个账号不要并发发帖。

```python
from filelock import FileLock

with FileLock(config.BOT_LOCK_FILE):
    client.ensure_logged_in()
    client.reply_thread(fid, tid, message)
```

---

## 16. 最小可运行 main.py

```python
from config import settings
from discuz_client import DiscuzClient
from worker import Worker


def main():
    client = DiscuzClient(
        base_url=settings.DISCUZ_BASE_URL,
        username=settings.DISCUZ_USERNAME,
        password=settings.DISCUZ_PASSWORD,
        cookie_file=settings.BOT_COOKIE_FILE,
    )

    worker = Worker(client=client)
    worker.run_forever()


if __name__ == "__main__":
    main()
```

---

## 17. 错误处理要求

必须处理以下异常：

```text
网络超时
登录失败
formhash 不存在
验证码拦截
权限不足
帖子关闭
回复间隔限制
内容被拦截
提交后找不到回复
数据库连接失败
Cookie 失效
```

失败策略：

1. 第一次失败：标记为 `status = 3`，`retry_count + 1`。
2. 达到最大重试次数：标记为 `status = 4`。
3. 如果疑似登录态失效：清理 Cookie，重新登录。
4. 如果疑似验证码：停止 worker，不要死循环。

---

## 18. 日志要求

每个任务至少记录：

```text
job_id
tid
fid
source_pid
status
retry_count
error
request_url
response_snippet
```

建议使用 `loguru`：

```python
from loguru import logger

logger.add("logs/worker.log", rotation="50 MB", retention="14 days")
```

---

## 19. Agent 回复生成

第一版可以先不接 LLM，直接用固定回复测试链路：

```python
def generate_reply(job):
    return "收到，我来帮你看一下。请补充一下具体报错截图、环境版本和复现步骤。"
```

第二版再接 LLM：

```text
帖子标题
帖子正文
论坛版块
历史上下文
用户问题
```

生成回复后要做清洗：

1. 去掉过长内容。
2. 去掉 Markdown 中 Discuz 不支持的格式。
3. 转义危险 HTML。
4. 限制最大字符数，例如 1000 字以内。

---

## 20. Discuz 内容格式注意事项

默认用纯文本或 BBCode，不要提交 HTML。

建议输出：

```text
你好，建议你按下面步骤排查：

1. 检查 PHP 版本。
2. 检查数据库连接配置。
3. 打开 Discuz 的调试日志。
4. 把完整报错贴出来。

如果方便，请补充你的 Discuz 版本和插件列表。
```

避免输出：

```html
<script>alert(1)</script>
<div style="color:red">...</div>
```

---

## 21. 手动插入测试任务

```sql
INSERT INTO bot_reply_jobs
(tid, fid, source_pid, source_subject, source_message, reply_message, status, retry_count, created_at, updated_at)
VALUES
(123, 2, 456, '测试标题', '测试正文', '这是一条机器人测试回复。', 0, 0, UNIX_TIMESTAMP(), UNIX_TIMESTAMP());
```

---

## 22. 开发顺序

### Step 1：实现配置读取

文件：

```text
config.py
.env
```

目标：程序能正确读取站点地址、账号、数据库配置。

---

### Step 2：实现 DiscuzClient 登录

文件：

```text
discuz_client.py
```

目标：

```text
能打开登录页
能解析 formhash
能提交登录
能保存 cookie
能判断登录态
```

---

### Step 3：实现回帖

目标：

```text
能打开帖子页
能解析 formhash
能提交回复
能校验回复出现在帖子页面
```

---

### Step 4：实现数据库任务队列

文件：

```text
db.py
worker.py
```

目标：

```text
读取待回复任务
锁定任务
处理成功后更新状态
处理失败后记录错误
```

---

### Step 5：实现完整 worker

目标：

```text
python main.py
```

可以持续运行并自动处理任务。

---

### Step 6：接入 Agent

文件：

```text
agent.py
```

目标：

```text
根据 source_subject 和 source_message 生成 reply_message
```

第一版可以让任务表里已经存好 `reply_message`。
第二版再由 worker 现场生成回复。

---

## 23. 验收标准

第一阶段验收：

```text
1. 可以登录论坛。
2. Cookie 可以保存并复用。
3. 可以对指定 tid/fid 发一条回复。
4. 回复后页面能看到内容。
5. 任务表状态从 0 变成 2。
6. 失败任务能记录错误。
```

第二阶段验收：

```text
1. worker 可以常驻运行。
2. 登录态失效后可以自动重新登录。
3. formhash 失效可以重新打开页面获取。
4. 重复任务不会重复发帖。
5. 同一个机器人账号不会并发发帖。
```

---

## 24. 重要限制

本方案依赖 Discuz 前台页面结构和表单行为，因此必须接受以下现实：

1. 模板改动可能导致选择器失效。
2. 验证码开启会导致登录或回帖失败。
3. 回帖间隔限制会导致提交失败。
4. 站点安全插件可能拦截异常请求。
5. HTTP 200 不代表发帖成功。
6. 不同 Discuz 版本的参数可能不同。

---

## 25. 后续增强

可以逐步加入：

```text
多账号轮换
按版块分配账号
按用户限流
按关键词触发
读取帖子上下文
读取同主题最近 N 楼
接入向量知识库
管理员后台面板
任务重放
失败原因分类
自动暂停机制
```

---

## 26. 给代码生成工具的实现提示

请按以下约束生成代码：

1. 使用 Python 3.10+。
2. 所有配置从 `.env` 读取。
3. HTTP 请求统一使用 `requests.Session`。
4. 所有请求设置合理 timeout。
5. 所有数据库写操作使用事务。
6. 一个机器人账号同一时间只能处理一个任务。
7. 不要直接写 Discuz 的 `forum_post` 表。
8. 不要忽略异常。
9. 不要只根据 HTTP 状态码判断发帖成功。
10. 提交后必须二次打开帖子页面校验。
11. Cookie 持久化到本地 JSON 文件。
12. 日志写入 `logs/worker.log`。
13. 所有模块都要有清晰的类型标注。
14. 代码应尽量简单，不要过度抽象。

---

## 27. 最小 MVP 范围

MVP 只需要完成：

```text
登录
保存 Cookie
读取一条任务
回复指定帖子
校验成功
更新任务状态
```

不要一开始就做：

```text
多账号
多线程
验证码识别
复杂后台
复杂 RAG
复杂权限系统
```

先跑通链路，再逐步增强。
