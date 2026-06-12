# api/logger.py
import logging
import os
import traceback
from datetime import datetime

def setup_logger(name: str, log_dir: str = "logs") -> logging.Logger:
    """配置并返回一个日志记录器，同时输出到控制台和文件"""
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    # 日志格式：时间、级别、模块名、文件名:行号、消息
    formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s [%(name)s] [%(filename)s:%(lineno)d] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 控制台 handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # 普通日志文件（INFO级别，按天切割）
    log_file = os.path.join(log_dir, f'{datetime.now().strftime("%Y-%m-%d")}.log')
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    # 错误日志文件（ERROR级别，单独存放错误信息）
    error_log_file = os.path.join(log_dir, f'{datetime.now().strftime("%Y-%m-%d")}_error.log')
    error_file_handler = logging.FileHandler(error_log_file, encoding='utf-8')
    error_file_handler.setLevel(logging.ERROR)  # 只记录ERROR及以上
    error_file_handler.setFormatter(formatter)


    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    logger.addHandler(error_file_handler)
    return logger
def log_exception(logger, e, context: str = ""):
    """
    记录异常的完整堆栈信息。
    
    参数:
        logger: logging.Logger 实例
        e: Exception 对象
        context: 额外的上下文信息（如当前处理的文件名、用户ID等）
    """
    error_msg = f"异常: {type(e).__name__}: {str(e)}"
    if context:
        error_msg = f"[{context}] {error_msg}"
    
    # 记录错误消息
    logger.error(error_msg)
    
    # 记录完整的堆栈跟踪到DEBUG级别
    logger.debug(f"完整堆栈:\n{traceback.format_exc()}")