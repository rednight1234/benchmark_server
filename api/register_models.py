# api/model_loader.py
import os
import importlib.util
from pathlib import Path

def register_models(model_dir: str = "models"):
    """
    扫描 model_dir 目录下的所有 .py 文件，将其中的 run 函数注册到字典中。
    返回: dict,键为模型名（文件名去掉 .py),值为 run 函数
    对于每一个run
    参数:
        info:{
            chr_name:  目标染色体chrA
            assembly:    hg19或hg38
            input_file:  输入接触数据文件的绝对路径（由前端上传后保存得到）
            resolution:  目标分辨率 (bp)
            work_dir:    该任务专用的临时工作目录，所有中间文件都应放在这里
            shape:  (n_beads,3)目标形状
        }
            progress_callback:  回调函数，签名为 callback(percent, message)
                                percent 是 0-100 的整数, message 是描述字符串
    返回:
        dict: {
            'status': 'success' 或 'error',
            'message': '简短描述',
            'output_file': 坐标文件的绝对路径 (例如 .pdb 或 .npy),
            'format': 'pdb' 或 'npy'
        }
    """
    model_registry = {}
    models_path = Path(model_dir)
    if not models_path.exists():
        raise FileNotFoundError(f"模型目录 {model_dir} 不存在")
    
    for file in models_path.glob("*.py"):
        if file.name.startswith("_"):
            continue  # 跳过 __init__.py 等内部文件
        model_name = file.stem  # 文件名（去掉扩展名）作为模型名
        
        # 动态导入模块
        spec = importlib.util.spec_from_file_location(model_name, str(file))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        if not hasattr(module, 'run'):
            print(f"警告: {file} 缺少 run 函数，跳过")
            continue
        
        model_registry[model_name] = module.run
        print(f"已注册模型: {model_name}")
    
    return model_registry