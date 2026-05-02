## 修改 SQLite 数据库的方法

macOS 自带 `sqlite3` 命令行工具，直接在终端操作即可。

### 打开数据库

```bash
sqlite3 data/bot.db
```

### 插入一条测试任务（指定板块 + 标明 AI 测试）

进入 sqlite3 交互界面后，粘贴以下 SQL：

```sql
INSERT INTO bot_reply_jobs
(tid, fid, source_pid, source_subject, source_message, reply_message, status, retry_count, created_at, updated_at)
VALUES
(4204,      -- 帖子的 tid（帖子里任意修改替换）
 40,        -- 版块的 fid（改成你目标版块的数字 ID）
 456,      -- 原帖楼层 pid（可选，改或不改都行）
 '测试标题',
 '这是原始帖子的内容',
 '【本回复由 AI 助手自动生成，仅供测试】收到，我来帮你看一下。',
 0,        -- 0=待发送
 0,
 CAST(strftime('%s', 'now') AS INTEGER),
 CAST(strftime('%s', 'now') AS INTEGER)
);
```

### 常用查询命令

```sql
-- 查看所有任务
SELECT id, tid, fid, status, reply_message FROM bot_reply_jobs;

-- 只查看待发送的
SELECT * FROM bot_reply_jobs WHERE status = 0;

-- 重置某个失败任务为待发送
UPDATE bot_reply_jobs SET status = 0, retry_count = 0 WHERE id = 1;

-- 删除所有任务（清空队列）
DELETE FROM bot_reply_jobs;
```

### 退出

```
.quit
```

### 关键字段说明

| 字段 | 含义 | 说明 |
|------|------|------|
| `tid` | 帖子ID | Discuz 帖子的数字ID |
| `fid` | 版块ID | 指定发到哪个版块 |
| `reply_message` | 回复内容 | 机器人实际发出的文字 |
| `status` | 状态 | 0=待发送, 1=发送中, 2=已发送, 3=失败可重试, 4=放弃 |

插入完任务后，启动 `python main.py`，Worker 会在 3 秒内检测到并自动执行发帖。

>-- 把全部任务重置为待发送
UPDATE bot_reply_jobs SET status = 0, retry_count = 0, last_error = NULL;

>-- 确认
SELECT id, tid, fid, status, retry_count FROM bot_reply_jobs;