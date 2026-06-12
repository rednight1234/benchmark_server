#!/usr/bin/env python
"""
sic.py
封装 Si-C 模型的运行流程。
"""

import os
import sys
import subprocess
import argparse
import shutil
import numpy as np
from api.utils import set_task_process_pid, get_and_clear_task_process_pid
# ================== 配置 Si‑C 的安装路径 ==================
TIME_OUT = 86400
SIC_HOME = "/home/zhangsf/Si-C/modeling"
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

def chr_name_to_chain(chr_name):
    """将染色体名（如 'chr19'）转换为 PDB 链标识符（如 'S'）"""
    if chr_name.startswith('chr'):
        num = chr_name[3:]
        if num == 'X':
            return 'w' 
        if num == 'Y':
            return 'x'
        else:
            try:
                n = int(num)
                return chr(64 + n).lower()  # 1->A, 2->B, ..., 19->S, 20->T
            except ValueError:
                raise ValueError(f"无法解析染色体名: {chr_name}")
    else:
        raise ValueError(f"染色体名必须以 'chr' 开头: {chr_name}")
def prepare_sic_workdir(work_dir, chr_name, assembly, resolution, input_file):
    """
    在 work_dir 中准备 Si-C 所需的所有文件。
    """
    # 1. 复制整个 Si‑C 模板目录到 work_dir
    sic_work = os.path.join(work_dir, "sic_modeling")
    if os.path.exists(sic_work):
        shutil.rmtree(sic_work)
    shutil.copytree(SIC_HOME, sic_work, symlinks=True)

    # 2. 准备输入接触对文件
    # Si‑C 的 1kb_prepare/do.sh 期望染色体是数字，我们需要将 chr1 转换为 1
    # 要求用户上传的接触对文件格式为 "chrA pos1 chrB pos2"（空格或Tab分隔）
    raw_contacts = os.path.join(work_dir, "contacts_raw.txt")
    shutil.copy2(input_file, raw_contacts)

    # 替换染色体名：chr?? -> 数字，X -> 21
    sic_contacts = os.path.join(sic_work, "cell_contacts.txt")
    with open(raw_contacts, 'r') as fin, open(sic_contacts, 'w') as fout:
        for line in fin:
            if line.strip() == '':
                continue
            parts = line.strip().split()
            # 格式：chr1 pos1 chr2 pos2 
            parts[0] = parts[0].replace('chr', '')
            parts[0] = parts[0].replace('X', '21')
            parts[2] = parts[2].replace('chr', '')
            parts[2] = parts[2].replace('X', '21')
            fout.write('\t'.join(parts) + '\n')

    # 3. 生成 chrlenlist.dat
    chrlen_file = os.path.join(sic_work, "chrlenlist.dat")
    length_dict = CHROM_LENGTHS.get(assembly, {})
    if not length_dict:
        raise ValueError(f"不支持的基因组版本: {assembly}")
    with open(chrlen_file, 'w') as f:
        for key,length in length_dict.items():
            f.write(f"{key}\t{length}\n")
    return sic_work,sic_contacts


def pdb_to_xyz(pdb_path, output_path, chr_name):
    """
    从 PDB 文件中提取 ATOM 坐标，写入 XYZ 文本文件。
    """
    coords = []
    target_chain = chr_name_to_chain(chr_name)
    with open(pdb_path, 'r') as f:
        for line in f:
            if (line.startswith('ATOM') or line.startswith('HETATM'))and (line[19]==target_chain):#TODO sic内部会把chr1映射到a，chr2映射到b，以此类推，需要只保留目标chr）
                x = float(line[30:38].strip())
                y = float(line[38:46].strip())
                z = float(line[46:54].strip())
                coords.append((x, y, z))
    if not coords:
        raise ValueError(
            f"PDB ({pdb_path}) 中没有找到染色体 {chr_name} (链 {target_chain}) 的 ATOM 记录"
        )
    with open(output_path, 'w') as f:
        f.write("# Si-C result: x y z\n")
        for i, (x, y, z) in enumerate(coords, start=1):
            f.write(f"{x:.6f}\t{y:.6f}\t{z:.6f}\n")


def run(info: dict, progress_callback) -> dict:
    """
    Si-C 模型入口。
    参数:
        info:{
            chr_name:  目标染色体chrA
            assembly:    hg19或hg38
            input_file:  输入接触数据文件的绝对路径（由前端上传后保存得到）
            resolution:  目标分辨率 (bp)
            work_dir:    该任务专用的临时工作目录，所有中间文件都应放在这里
            true_coords_file: 目标文件的路径
        }
            progress_callback:  回调函数，签名为 callback(percent, message)
                                percent 是 0-100 的整数, message 是描述字符串
    返回:
        dict: {
            'status': 'success' 或 'error',
            'message': '简短描述',
            'output_file': 坐标文件的绝对路径 txt格式,
        }
    """
    process = None
    try:
        progress_callback(5, "正在准备 Si-C 工作目录...")
        sic_work, sic_contacts = prepare_sic_workdir(
            info['work_dir'], info['chr_name'], info['assembly'],
            info['resolution'], info['input_file']
        )
        log_dir = os.path.join(sic_work, "sic_logs")
        os.makedirs(log_dir, exist_ok=True)
        log_file_path = os.path.join(log_dir, "sic_run.log")

        # ---------- 步骤1: 1kb 预处理 ----------
        progress_callback(10, "正在将接触对分配到 1kb bin...")
        target_dir = os.path.join(sic_work, "contact", "1kb_prepare")
        os.makedirs(target_dir, exist_ok=True)
        with open(log_file_path, "w") as log_file:
            subprocess.run(
                ["bash", "do.sh", sic_contacts, "21"],
                cwd=target_dir,
                stdout=log_file, stderr=subprocess.STDOUT,
                check=True, text=True
            )

        # ---------- 步骤2: 多分辨率聚合 ----------
        progress_callback(30, "正在进行多分辨率聚合...")
        finalres = info['resolution'] // 1000
        chrlen_file = os.path.join(sic_work, "chrlenlist.dat")
        # 复制模板目录 target_bk 为 {finalres}kb_target
        contact_dir = os.path.join(sic_work, "contact")
        template = os.path.join(contact_dir, "target_bk")
        target_dir = os.path.join(contact_dir, f"{finalres}kb_target")
        if os.path.exists(target_dir):
            shutil.rmtree(target_dir)
        shutil.copytree(template, target_dir)
        with open(log_file_path, "a") as log_file:
            subprocess.run(
                ["bash", "doall.sh", "21", str(finalres), chrlen_file],
                cwd=target_dir,
                stdout=log_file, stderr=subprocess.STDOUT,
                check=True, text=True
            )

        # ---------- 步骤3: 合并接触矩阵 ----------
        progress_callback(50, "正在合并接触矩阵...")
        contactall_dir = os.path.join(target_dir, "contactall")
        os.makedirs(contactall_dir, exist_ok=True)
        # 确保 do.sh 存在 (从模板复制)
        src_do = os.path.join(contact_dir, "target_bk", "contactall", "do.sh")
        dst_do = os.path.join(contactall_dir, "do.sh")
        if not os.path.exists(dst_do):
            shutil.copy(src_do, dst_do)
        with open(log_file_path, "a") as log_file:
            subprocess.run(
                ["bash", "do.sh", "21"],
                cwd=contactall_dir,
                stdout=log_file, stderr=subprocess.STDOUT,
                check=True, text=True
            )

        # ---------- 步骤4: 准备 MD 模拟文件 ----------
        progress_callback(60, "正在准备 MD 模拟文件...")
        md_dir = os.path.join(sic_work, "MD_simulation", f"{finalres}kb_1replica")
        os.makedirs(md_dir, exist_ok=True)
        replica_bk = os.path.join(sic_work, "MD_simulation", "replica", "bk")
        replica_dir = os.path.join(md_dir, "1")
        if os.path.exists(replica_dir):
            shutil.rmtree(replica_dir)
        shutil.copytree(replica_bk, replica_dir)

        # ---------- 步骤5: 执行 MD 模拟 (长时任务，使用 Popen) ----------
        progress_callback(70, "正在进行 MD 模拟...")
        with open(log_file_path, "a") as log_file:
            process = subprocess.Popen(
                ["bash", "doall.sh", "21", str(finalres), "1"],
                cwd=replica_dir,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True
            )
        set_task_process_pid(info.get('task_id', ''), process.pid)
        returncode = process.wait(timeout=TIME_OUT)
        if returncode != 0:
            raise RuntimeError(f"Si-C MD 模拟失败，详见日志: {log_file_path}")

        # ========== 直接处理最终坐标，跳过平滑和 PDB 生成 ==========
        progress_callback(90, "正在处理最终坐标...")

        # 找到 MD 模拟的输出目录
        md_run_dir = os.path.join(md_dir, "1")

        temp_file = os.path.join(md_run_dir, "temp.dat")
        if not os.path.exists(temp_file):
            # 如果没有 temp.dat，尝试从最后一个 outputall_*.dat 中提取
            # 寻找最新的 outputall_*.dat 文件
            import glob
            output_files = sorted(glob.glob(os.path.join(md_run_dir, "outputall_*.dat")))
            if output_files:
                assign_file = os.path.join(md_run_dir, "assign.dat")
                with open(assign_file, 'r') as f:
                    statenum = len(f.readlines())
                with open(output_files[-1], 'r') as fin:
                    lines = fin.readlines()
                    last_lines = lines[-statenum:]  # 取最后 statenum 行
                with open(temp_file, 'w') as fout:
                    fout.writelines(last_lines)
            else:
                raise FileNotFoundError("找不到 MD 模拟的输出文件，无法生成最终坐标")
        coords = []
        with open(temp_file, 'r') as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 3:
                    coords.append([float(parts[0]), float(parts[1]), float(parts[2])])

        if not coords:
            raise ValueError("无法从 MD 输出中读取有效坐标")

        # 直接写入 XYZ 文件（跳过平滑）
        xyz_output = os.path.join(info['work_dir'], "sic_output.txt")
        with open(xyz_output, 'w') as f:
            f.write("# Si-C result: x y z (smoothed by MD only)\n")
            for x, y, z in coords:
                f.write(f"{x:.6f}\t{y:.6f}\t{z:.6f}\n")

        progress_callback(100, "Si-C 重建完成")
        return {
            'status': 'success',
            'message': 'Si-C 3D 重建完成',
            'output_file': xyz_output,
            'format': 'txt'
        }

    except subprocess.TimeoutExpired:
        if process and isinstance(process, subprocess.Popen) and process.poll() is None:
            process.kill()
            process.wait()
        return {'status': 'error', 'message': 'Si-C 运行超时', 'output_file': None}
    except Exception as e:
        if process and isinstance(process, subprocess.Popen) and process.poll() is None:
            process.kill()
            process.wait()
        return {'status': 'error', 'message': str(e), 'output_file': None}
    finally:
        get_and_clear_task_process_pid(info.get('task_id', ''))