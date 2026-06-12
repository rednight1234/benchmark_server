# model/tensorflamingo.py
# 注意, 为了避免多线程引发的端口冲突, 我修改了FLAMINGO_reconstruct.R, 使其接受第六个参数nThread并用于控制线程数量
import subprocess
import os
import pandas as pd
import numpy as np
import shutil
from pathlib import Path
from api.utils import set_task_process_pid,get_and_clear_task_process_pid
TIME_OUT=86400 #24小时超时
FLAMINGO_CODE_PATH='/home/zhangsf/Tensor-FLAMINGO'# 指向FLAMINGO的实际路径
FLAMINGO_ENV='flamingo'# 指向FLAMINGO的实际conda环境,如果不是用conda管理,需要更改下方的cmd中的参数
CHROM_LENGTHS = {
    'hg19': {
        'chr1': 249250621, 'chr2': 243199373, 'chr3': 198022430, 'chr4': 191154276,
        'chr5': 180915260, 'chr6': 171115067, 'chr7': 159138663, 'chr8': 146364022,
        'chr9': 141213431, 'chr10': 135534747, 'chr11': 135006516, 'chr12': 133851895,
        'chr13': 115169878, 'chr14': 107349540, 'chr15': 102531392, 'chr16': 90354753,
        'chr17': 81195210, 'chr18': 78077248, 'chr19': 59128983, 'chr20': 63025520,
        'chrX': 155270560
    },
    'hg38': {
        'chr1': 248956422, 'chr2': 242193529, 'chr3': 198295559, 'chr4': 190214555,
        'chr5': 181538259, 'chr6': 170805979, 'chr7': 159345973, 'chr8': 145138636,
        'chr9': 138394717, 'chr10': 133797422, 'chr11': 135086622, 'chr12': 133275309,
        'chr13': 114364328, 'chr14': 107043718, 'chr15': 101991189, 'chr16': 90338345,
        'chr17': 83257441, 'chr18': 80373285, 'chr19': 58617616, 'chr20': 64444167,
        'chrX': 156040895
    }
}
def convert_flamingo_to_xyz(input_path, output_path, true_coords_file):
    """
    将 FLAMINGO 的 Cell_1.txt(frag_id x y z)转换为纯 XYZ 文件。
    """
    if not os.path.exists(true_coords_file):
        raise FileNotFoundError(f"真实坐标文件不存在: {true_coords_file}")
    true_coords = np.load(true_coords_file) if true_coords_file.endswith('.npy') else np.loadtxt(true_coords_file)
    shape = true_coords.shape

    flamingo_df = pd.read_csv(input_path, sep='\t').sort_values('frag_id')
    pred_coords_raw = flamingo_df[['x', 'y', 'z']].values.astype(np.float64)
    frag_ids = flamingo_df['frag_id'].values.astype(int)

    # 创建与真实坐标相同形状的预测数组，初始化为 NaN
    pred_coords_aligned = np.full(shape, np.nan)

    # 只将有效的 frag_id 对应的预测坐标填入
    valid_mask = (frag_ids >= 0) & (frag_ids < shape[0])
    pred_coords_aligned[frag_ids[valid_mask]] = pred_coords_raw[valid_mask]
    with open(output_path,'w') as fout:
        for row in pred_coords_aligned:
            if np.isnan(row[0]):
                fout.write("NaN NaN NaN\n")
            else:
                fout.write(f'{row[0]:.6f} {row[1]:.6f} {row[2]:.6f}\n')

def run(info: dict, progress_callback) -> dict:
    """
    执行 3D 重建。

    参数:
        info:{
            chr_name:  目标染色体chrA
            assembly:    hg19或hg38
            input_file:  输入接触数据文件的绝对路径（由前端上传后保存得到）
            true_coords_file: 目标文件的路径
            resolution:  目标分辨率 (bp)
            work_dir:    该任务专用的临时工作目录，所有中间文件都应放在这里
        }
            progress_callback:  回调函数，签名为 callback(percent, message)
                                percent 是 0-100 的整数, message 是描述字符串
    返回:
        dict: {
            'status': 'success' 或 'error',
            'message': '简短描述',
            'output_file': 坐标文件的绝对路径 txt格式

        }
    """
    log_dir = os.path.join(info['work_dir'], "Tensor-FLAMINGO_logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file_path = os.path.join(log_dir, 'log.txt')
    try:
        # ===== 步骤 1: 准备输入文件夹 =====
        progress_callback(5, "正在准备 FLAMINGO 输入数据...")
        
        # FLAMINGO 要求输入是一个文件夹，里面包含该细胞的接触对文件
        input_folder = os.path.join(info['work_dir'], "input")
        os.makedirs(input_folder, exist_ok=True)
        
        # 将选择文件复制到输入文件夹中（FLAMINGO 会读取该文件夹下的所有文件）
        dest_file = os.path.join(input_folder, os.path.basename(info['input_file']))
        shutil.copy2(info['input_file'], dest_file)
        
        # ===== 步骤 2: 设置参数 =====
        # 染色体名称
        chr_name = info['chr_name']
        # 低分辨率通常是高分辨率的 10 倍
        low_res = str(int(info['resolution']) * 10)  # 例如 20000 -> 200000
        high_res = str(info['resolution'])
        assembly = info['assembly']  # 基因组版本
        outputs_folder = info['work_dir']
        
        # ===== 步骤 3: 数据预处理 =====
        with open(log_file_path, 'a') as log_file:
            progress_callback(10, "正在进行数据预处理...")
            log_file.write("=== 数据预处理 ===\n")
            log_file.flush()

            cmd_preprocess = [
                "conda", "run", "-n", FLAMINGO_ENV,
                "Rscript",
                os.path.join(FLAMINGO_CODE_PATH, "data_preprocess.R"),
                input_folder,
                chr_name,
                low_res,
                high_res,
                assembly,
                outputs_folder,
                FLAMINGO_CODE_PATH
            ]
            subprocess.run(cmd_preprocess, check=True, stdout=log_file,
                   stderr=subprocess.STDOUT, text=True)   
            # ===== 步骤 4: 张量补全 =====
            progress_callback(20, "正在进行低分辨率张量补全...")
            log_file.write("\n=== 低分辨率张量补全 ===\n")
            log_file.flush()

            cmd_lowres_tensor = [
                "conda", "run", "-n", FLAMINGO_ENV,
                "python",
                os.path.join(FLAMINGO_CODE_PATH, "src", "Paralized_Low_rank_tensor_completion_FFTW.py"),
                "-i", os.path.join(outputs_folder, "lowres_contact_maps_transformed"),
                "-o", os.path.join(outputs_folder, "LRTC_low_res_contact_maps"),
                "-s", "low_resolution",
                "-max_iter", "150",
                "-n_core", "10"
            ]
            subprocess.run(cmd_lowres_tensor, check=True, stdout=log_file,
                   stderr=subprocess.STDOUT, text=True)
            
            # 提取低分辨率结果
            progress_callback(30, "正在提取低分辨率结果...")
            log_file.write("\n=== 提取低分辨率结果 ===\n")
            log_file.flush()

            cmd_extract_low = [
                "conda", "run", "-n", FLAMINGO_ENV,
                "python",
                os.path.join(FLAMINGO_CODE_PATH, "src", "Extract_matrix_from_LRTC.py"),
                "-i", os.path.join(outputs_folder, "LRTC_low_res_contact_maps", "low_resolution.npy"),
                "-o", os.path.join(outputs_folder, "low_res_contact_maps_FLAMINGO")
            ]
            subprocess.run(cmd_extract_low, check=True, stdout=log_file,
                   stderr=subprocess.STDOUT, text=True)
            
            # 高分辨率张量补全
            progress_callback(40, "正在进行高分辨率张量补全...")
            log_file.write("\n=== 高分辨率张量补全 ===\n")
            log_file.flush()

            cmd_highres_tensor = [
                "conda", "run", "-n", FLAMINGO_ENV,
                "python",
                os.path.join(FLAMINGO_CODE_PATH, "src", "Paralized_Low_rank_tensor_completion_FFTW.py"),
                "-i", os.path.join(outputs_folder, "highres_contact_maps_transformed"),
                "-o", os.path.join(outputs_folder, "LRTC_high_res_contact_maps"),
                "-s", "high_resolution",
                "-max_iter", "150",
                "-n_core", "2"
            ]
            subprocess.run(cmd_highres_tensor, check=True, stdout=log_file,
                   stderr=subprocess.STDOUT, text=True)
            
            # 提取高分辨率结果
            progress_callback(45, "正在提取高分辨率结果...")
            log_file.write("\n=== 提取高分辨率结果 ===\n")
            log_file.flush()

            cmd_extract_high = [
                "conda", "run", "-n", FLAMINGO_ENV,
                "python",
                os.path.join(FLAMINGO_CODE_PATH, "src", "Extract_matrix_from_LRTC.py"),
                "-i", os.path.join(outputs_folder, "LRTC_high_res_contact_maps", "high_resolution.npy"),
                "-o", os.path.join(outputs_folder, "high_res_contact_maps_FLAMINGO")
            ]
            subprocess.run(cmd_extract_high, check=True, stdout=log_file,
                   stderr=subprocess.STDOUT, text=True)
            
            # ===== 步骤 5: 3D 结构重建 =====
            progress_callback(50, "正在进行 3D 结构重建, 这可能花费较长时间...")
            log_file.write("\n=== 3D 结构重建 ===\n")
            log_file.flush()

            cmd_reconstruct = [
                "conda", "run", "-n", FLAMINGO_ENV,
                "Rscript",
                os.path.join(FLAMINGO_CODE_PATH, "FLAMINGO_reconstruct.R"),
                outputs_folder,
                chr_name,
                low_res,
                high_res,
                "5"# 注意, 为了避免多线程引发的端口冲突, 我修改了FLAMINGO_reconstruct.R, 使其接受第六个参数nThread并用于控制线程数量
            ]
            process = subprocess.Popen(
                cmd_reconstruct,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True
            )
            
            try:
                set_task_process_pid(info.get('task_id', ''), process.pid)
                returncode = process.wait(timeout=TIME_OUT)  # 24小时超时
                if returncode != 0:
                    # 读取日志最后 20 行作为错误信息
                    error_tail = ""
                    if os.path.exists(log_file_path):
                        with open(log_file_path, 'r') as f:
                            lines = f.readlines()
                            error_tail = ''.join(lines[-20:]) if lines else "(empty log)"
                    raise RuntimeError(f"FLAMINGO 3D重建失败 (详见 {log_file_path}):\n{error_tail}")

            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                error_msg = f"FLAMINGO 3D重建超时: >{TIME_OUT}"
                raise RuntimeError(error_msg)
            except Exception as e:
                # 如果进程还在运行，尝试终止它
                if process and process.poll() is None:
                    process.kill()
                    process.wait()
                raise e
            finally:
                # 清理 Redis 中的 PID 记录
                get_and_clear_task_process_pid(info.get('task_id', ''))
                    
            # ===== 步骤 6: 收集结果 =====
            progress_callback(95, "正在整理结果文件...")
            
            # FLAMINGO 的输出在 Tensor-FLAMINGO_results/Cell_1.txt
            result_file = os.path.join(
                outputs_folder, "Tensor-FLAMINGO_results", "Cell_1.txt"
            )
            
            if not os.path.exists(result_file):
                raise FileNotFoundError(f"FLAMINGO 结果文件未生成: {result_file}")
            
            # 生成纯 XYZ 文件
            xyz_output_file = os.path.join(info["work_dir"], "flamingo_output.txt")
            convert_flamingo_to_xyz(result_file, xyz_output_file,true_coords_file=info['true_coords_file'])

            progress_callback(100, "FLAMINGO 重建完成")

            return {
                'status': 'success',
                'message': 'FLAMINGO 3D 重建完成',
                'output_file': xyz_output_file,
            }
            
    except subprocess.CalledProcessError as e:
        error_msg = f"FLAMINGO 执行失败: {e.stderr if e.stderr else str(e)}"
        return {
            'status': 'error',
            'message': error_msg,
            'output_file': None,
        }
    except Exception as e:
        return {
            'status': 'error',
            'message': str(e),
            'output_file': None,
        }