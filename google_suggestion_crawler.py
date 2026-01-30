import requests
import xml.etree.ElementTree as ET
from typing import List, Set, Tuple
from queue import Queue, Empty
from threading import Thread, Lock
import time
import os
from datetime import datetime
import signal
import os
try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False


class SuggestionWorker:
    """
    Google 搜索建议爬虫
    """

    # 常量配置
    SUGGESTION_URL = "https://suggestqueries.google.com/complete/search"
    DEFAULT_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    REQUEST_TIMEOUT = 5
    QUEUE_TIMEOUT = 60
    WORKER_SLEEP = 1

    def __init__(self, main_keyword: str, output_dir: str = "results",
                 num_workers: int = 2, max_depth: int = 5):
        """
        初始化搜索建议爬虫

        Args:
            main_keyword: 主要关键词,必须包含在结果中
            output_dir: 输出目录
            num_workers: 并发工作线程数
            max_depth: 最大搜索深度
        """
        self.main_keyword = main_keyword.lower()
        self.num_workers = num_workers
        self.max_depth = max_depth

        # 创建输出目录
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

        # 创建带时间戳的输出文件
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_file = os.path.join(output_dir, f"suggestions_{main_keyword}_{timestamp}.txt")

        # 初始化队列和集合
        self.queue: Queue[Tuple[str, int]] = Queue()
        self.results: Set[str] = set()
        self.processed_queries: Set[str] = set()

        # 线程锁
        self.lock = Lock()

        # 进度条
        self.pbar = None
        
        # 优雅退出标志
        self.shutdown_flag = False

    def get_suggestions(self, query: str) -> List[str]:
        """获取 Google 搜索建议"""
        params = {
            "output": "toolbar",
            "hl": "en",
            "q": query
        }

        try:
            response = requests.get(
                self.SUGGESTION_URL,
                params=params,
                headers=self.DEFAULT_HEADERS,
                timeout=self.REQUEST_TIMEOUT
            )
            response.raise_for_status()

            root = ET.fromstring(response.text)
            suggestions = [suggestion.get('data') for suggestion in root.findall('.//suggestion')]

            # 只保留包含主关键词的建议
            return [s for s in suggestions if self.main_keyword in s.lower()]

        except requests.RequestException as e:
            print(f"网络错误 '{query}': {type(e).__name__}")
            return []
        except ET.ParseError as e:
            print(f"XML解析错误 '{query}': {e}")
            return []

    def save_suggestion(self, suggestion: str):
        """保存建议词到文件"""
        with open(self.output_file, 'a', encoding='utf-8') as f:
            f.write(f"{suggestion}\n")
        if self.pbar is not None:
            self.pbar.update(1)

    def worker(self):
        """工作线程函数"""
        while not self.shutdown_flag:
            try:
                query, depth = self.queue.get(timeout=self.QUEUE_TIMEOUT)

                # 停止信号或已处理过的查询
                if query is None or query in self.processed_queries:
                    self.queue.task_done()
                    if query is None:
                        break
                    continue

                # 深度限制检查
                if depth >= self.max_depth:
                    self.queue.task_done()
                    continue

                print(f"正在处理 (depth={depth}): {query}")
                self.processed_queries.add(query)
                suggestions = self.get_suggestions(query)

                # 使用锁保证线程安全
                with self.lock:
                    for suggestion in suggestions:
                        if suggestion not in self.results:
                            self.results.add(suggestion)
                            self.save_suggestion(suggestion)
                            self.queue.put((suggestion, depth + 1))

                time.sleep(self.WORKER_SLEEP)
                self.queue.task_done()

            except Empty:
                if self.queue.empty() or self.shutdown_flag:
                    break
            except Exception as e:
                print(f"处理时出错: {type(e).__name__}: {e}")
                self.queue.task_done()

    def cleanup(self):
        """清理资源"""
        # 关闭进度条
        if self.pbar is not None:
            try:
                self.pbar.close()
            except:
                pass
        
        # 设置退出标志
        self.shutdown_flag = True
        
        # 清空队列并发送停止信号
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
                self.queue.task_done()
            except Empty:
                break
        
        # 发送停止信号
        for _ in range(self.num_workers):
            try:
                self.queue.put((None, 0), block=False)
            except:
                pass

    def run(self):
        """运行爬虫"""
        print(f"开始收集包含 '{self.main_keyword}' 的搜索建议...")
        print(f"最大深度: {self.max_depth}")
        print(f"结果将保存到: {self.output_file}")

        """
        准备输出文件
        - 清空文件并写入表头
        """
        with open(self.output_file, 'w', encoding='utf-8') as f:
            f.write("关键词\n")

        # 添加初始关键词 (depth=0)
        self.queue.put((self.main_keyword, 0))

        # 初始化进度条
        if HAS_TQDM:
            self.pbar = tqdm(desc="收集进度", unit="词")
        else:
            self.pbar = None
            print("提示: 安装 tqdm 可显示进度条 (pip install tqdm)")

        """
        启动工作线程并等待完成
        - 创建并启动指定数量的工作线程
        - 等待队列中所有任务完成
        - 发送停止信号并等待线程退出
        """
        threads = []
        for _ in range(self.num_workers):
            t = Thread(target=self.worker)
            t.daemon = True  # 设置为守护线程
            t.start()
            threads.append(t)

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

        print(f"\n已完成! 共收集到 {len(self.results)} 个建议关键词")
        print(f"结果已保存到: {self.output_file}")


def main():
    main_keyword = input("请输入主要关键词: ").strip()

    crawler = SuggestionWorker(
        main_keyword=main_keyword,
        num_workers=2,
        max_depth=5
    )

    crawler.run()


if __name__ == "__main__":
    main()
