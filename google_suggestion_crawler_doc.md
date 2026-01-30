# Google Suggestion Crawler 技术文档

## 概述

`google_suggestion_crawler.py` 是一个用于批量获取 Google 搜索建议词的爬虫工具。它通过 Google Suggest API 进行 BFS（广度优先搜索）扩展，收集与指定关键词相关的所有搜索建议，适用于关键词研究、SEO 分析、流量挖掘等场景。

## 功能特性

- **BFS 深度扩展**：从初始关键词出发，逐层扩展获取长尾关键词
- **多线程并发**：支持配置并发线程数，提高采集效率
- **深度限制**：可配置最大搜索深度，防止无限扩展
- **线程安全**：使用锁机制保证多线程环境下的数据一致性
- **优雅退出**：支持 Ctrl+C 中断并安全退出
- **结果持久化**：实时保存结果到文件，支持断点续传
- **进度显示**：使用 tqdm 显示实时采集进度

## 环境要求

- Python 3.7+
- 依赖库：`requests`, `tqdm`

安装依赖：

```bash
pip install requests tqdm
```

## 使用方法

### 基础用法

```bash
python3 google_suggestion_crawler.py
```

按提示输入主要关键词即可开始采集。

### 高级用法

如需修改并发数或深度限制，可编辑 `main()` 函数中的参数：

```python
crawler = SuggestionWorker(
    main_keyword=main_keyword,
    num_workers=2,      # 并发线程数
    max_depth=5         # 最大搜索深度
)
```

## 核心设计

### 类结构

```
SuggestionWorker
├── __init__: 初始化配置
├── get_suggestions: 获取单个关键词的建议
├── save_suggestion: 保存建议词到文件
├── worker: 工作线程函数
├── cleanup: 清理资源(进度条、队列等)
└── run: 启动爬虫
```

### 数据结构

| 数据                | 类型                     | 说明                           |
| ------------------- | ------------------------ | ------------------------------ |
| `queue`             | `Queue[Tuple[str, int]]` | 待处理队列,存储 (关键词, 深度) |
| `results`           | `Set[str]`               | 已收集的建议词集合             |
| `processed_queries` | `Set[str]`               | 已处理的查询词集合             |
| `lock`              | `Lock`                   | 线程锁,保护共享数据            |
| `max_depth`         | `int`                    | 最大搜索深度                   |
| `pbar`              | `tqdm`                   | 进度条对象(可选)               |
| `shutdown_flag`     | `bool`                   | 优雅退出标志,用于控制线程退出  |

### 工作流程

```
1. 初始化
   ├── 创建输出目录
   ├── 创建带时间戳的输出文件
   └── 初始化队列，将 (main_keyword, 0) 入队

2. 启动线程
   ├── 创建指定数量的工作线程
   └── 每个线程执行 worker() 函数

3. BFS 处理循环
   ├── 从队列取出 (query, depth)
   ├── 检查深度限制
   ├── 调用 Google Suggest API
   ├── 过滤包含主关键词的建议
   ├── 保存新建议并入队 (suggestion, depth+1)
   └── 重复直到队列为空

4. 结束清理
   ├── 发送停止信号
   └── 等待所有线程退出
```

### 深度扩展示例

以 `ai` 为例，max_depth=5 时的扩展过程：

```
depth=0: ai
    └── depth=1: ai generator, ai image, ai chat
            └── depth=2: best ai generator, free ai image
                    └── depth=3: best free ai image generator
                            └── depth=4: best free ai image generator online
                                    └── depth=5: best free ai image generator online 2025
                                            └── depth=6: (不再处理)
```

## API 详解

### SuggestionWorker.**init**

```python
def __init__(self, main_keyword: str, output_dir: str = "results",
             num_workers: int = 2, max_depth: int = 5):
```

| 参数           | 类型  | 默认值      | 说明                         |
| -------------- | ----- | ----------- | ---------------------------- |
| `main_keyword` | `str` | -           | 主要关键词，结果必须包含此词 |
| `output_dir`   | `str` | `"results"` | 输出目录                     |
| `num_workers`  | `int` | `2`         | 并发工作线程数               |
| `max_depth`    | `int` | `5`         | 最大搜索深度                 |

### SuggestionWorker.get_suggestions

```python
def get_suggestions(self, query: str) -> List[str]:
```

调用 Google Suggest API 获取指定查询的建议词列表。

**请求参数**：

- `query`: 查询词

**返回值**：

- `List[str]`: 包含主关键词的建议词列表

**API 端点**：

```
https://suggestqueries.google.com/complete/search?output=toolbar&hl=en&q={query}
```

**请求头**：

```python
{
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}
```

### SuggestionWorker.worker

工作线程主函数,处理队列中的任务。

**处理逻辑**:

1. 循环检查 `shutdown_flag`,支持优雅退出
2. 从队列获取 `(query, depth)`,超时 60 秒
3. 检查是否已处理,若已处理则跳过
4. 检查深度限制,超过 max_depth 则跳过
5. 调用 `get_suggestions` 获取建议
6. 线程安全地保存新建议并入队
7. 休眠 1 秒避免请求过快
8. 在异常处理中检查 `shutdown_flag`,确保能及时退出

### SuggestionWorker.cleanup

清理资源的方法,在程序退出时调用。

**清理步骤**:

1. 安全关闭 tqdm 进度条(使用 `is not None` 检查)
2. 设置 `shutdown_flag = True` 通知所有线程退出
3. 清空队列中的所有待处理任务
4. 向所有工作线程发送停止信号 `(None, 0)`

### SuggestionWorker.run

启动爬虫的主入口。

**执行步骤**:

1. 创建/清空输出文件
2. 初始关键词入队
3. 启动工作线程(设置为守护线程)
4. 使用 `try-except-finally` 结构处理:
   - **正常流程**: 等待队列处理完成,发送停止信号
   - **中断处理**: 捕获 `KeyboardInterrupt`,调用 `cleanup()` 清理资源
   - **最终清理**: 在 `finally` 块中确保进度条被关闭
5. 打印统计结果

## 线程安全设计

### 锁的使用

在多线程环境下，`results` 和 `processed_queries` 的读写操作使用 `Lock` 保证原子性：

```python
with self.lock:
    for suggestion in suggestions:
        if suggestion not in self.results:
            self.results.add(suggestion)
            self.save_suggestion(suggestion)
            self.queue.put((suggestion, depth + 1))
```

### 队列操作

- 使用 `queue.get(timeout=60)` 避免无限阻塞
- 使用 `queue.task_done()` 标记任务完成
- 使用 `queue.join()` 等待所有任务完成

### 优雅退出机制

脚本使用 `KeyboardInterrupt` 异常处理机制实现优雅退出,而不是信号处理器:

```python
try:
    self.queue.join()
    time.sleep(2)

    # 正常结束,发送停止信号
    for _ in range(self.num_workers):
        self.queue.put((None, 0))
    for t in threads:
        t.join(timeout=5)

except KeyboardInterrupt:
    print("\n收到中断信号,正在清理资源...")
    self.cleanup()
    # 等待线程退出
    for t in threads:
        t.join(timeout=2)
finally:
    # 确保进度条被关闭
    if self.pbar is not None:
        try:
            self.pbar.close()
        except:
            pass
```

**优势**:

- ✅ 正确清理所有资源(进度条、队列、线程)
- ✅ 不会产生资源泄漏警告
- ✅ 使用守护线程(`daemon=True`)确保主进程退出时线程自动终止
- ✅ 使用 `is not None` 检查 tqdm 对象,避免 `TypeError`

## 错误处理

### 网络错误

```python
except requests.RequestException as e:
    print(f"网络错误 '{query}': {type(e).__name__}")
    return []
```

### XML 解析错误

```python
except ET.ParseError as e:
    print(f"XML解析错误 '{query}': {e}")
    return []
```

### 队列空超时

```python
except Empty:
    if self.queue.empty():
        break
    continue
```

## 输出格式

结果保存在 `results/suggestions_{关键词}_{时间戳}.txt`：

```
关键词
ai generator
best ai generator
free ai image generator
...
```

每行一个建议词，带表头 `关键词`。

## 性能优化

### 请求间隔

每个请求后休眠 1 秒，避免触发 Google 的速率限制：

```python
time.sleep(1)
```

### 深度限制

通过 `max_depth` 控制搜索范围，平衡覆盖度和效率：

| max_depth | 预计结果数 | 耗时 |
| --------- | ---------- | ---- |
| 3         | ~数百      | 短   |
| 5         | ~数千      | 中   |
| 10        | ~数万      | 长   |

### 并发数

增加 `num_workers` 可提高采集速度，但可能触发 Google 的反爬机制。建议：

- 开发测试：`num_workers=1`
- 正式采集：`num_workers=2`
- 高速采集：`num_workers=3+`（风险较高）

## 扩展建议

### 支持多语言

修改 `get_suggestions` 的 `hl` 参数：

```python
params = {
    "output": "toolbar",
    "hl": "zh",      # 中文
    "q": query
}
```

### 自定义过滤规则

修改 `get_suggestions` 中的过滤逻辑：

```python
# 原逻辑：包含主关键词
filtered_suggestions = [s for s in suggestions if self.main_keyword in s.lower()]

# 可扩展：添加长度限制
filtered_suggestions = [
    s for s in suggestions
    if self.main_keyword in s.lower() and 3 <= len(s) <= 100
]

# 可扩展：排除特定模式
exclude_patterns = ['download', 'free download']
filtered_suggestions = [
    s for s in suggestions
    if self.main_keyword in s.lower()
    and not any(p in s.lower() for p in exclude_patterns)
]
```

### 进度显示

脚本使用 `tqdm` 库实时显示采集进度：

**初始化进度条**（在 `run()` 中）：

```python
if HAS_TQDM:
    self.pbar = tqdm(desc="收集进度", unit="词")
else:
    print("提示: 安装 tqdm 可显示进度条 (pip install tqdm)")
```

**更新进度条**(在 `save_suggestion()` 中):

```python
def save_suggestion(self, suggestion: str):
    with open(self.output_file, 'a', encoding='utf-8') as f:
        f.write(f"{suggestion}\n")
    # 更新进度条
    if self.pbar is not None:
        self.pbar.update(1)
```

**关闭进度条**(在 `run()` 结束时和 `cleanup()` 中):

```python
# 使用 is not None 检查,避免 tqdm 的 __bool__ 抛出 TypeError
if self.pbar is not None:
    try:
        self.pbar.close()
    except:
        pass
```

> **重要提示**: tqdm 进度条在某些状态下(如 `iterable == total == None`)直接使用 `if self.pbar:` 会抛出 `TypeError: bool() undefined when iterable == total == None`。因此必须使用 `if self.pbar is not None:` 来检查。

**效果展示**：

```
收集进度: 100%|████████████████| 1234词 [00:30<02:00, 41.2词/秒]
```

## 注意事项

1. **合规使用**:请遵守 Google 的服务条款,避免过度请求
2. **频率控制**:适当设置请求间隔,防止 IP 被封禁
3. **深度选择**:根据实际需求选择合适的 max_depth
4. **结果去重**:自动去重,但多次运行可能产生重复文件
5. **优雅退出**:按 Ctrl+C 可安全退出,程序会自动清理资源,不会产生警告
6. **tqdm 检查**:在代码中检查 tqdm 对象时必须使用 `is not None`,不能直接用布尔检查

## 许可证

本项目仅供学习和研究使用。
