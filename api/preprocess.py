# api/preprocess.py
import os
import numpy as np
import pandas as pd
from .logger import setup_logger, log_exception

logger = setup_logger('preprocess')

# 染色体长度参考（之前已有，保持不变）
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

# 染色体到PDB链标识符的映射
CHROM_TO_PDB_CHAIN = {
    'chr1': 'a', 'chr2': 'b', 'chr3': 'c', 'chr4': 'd',
    'chr5': 'e', 'chr6': 'f', 'chr7': 'g', 'chr8': 'h',
    'chr9': 'i', 'chr10': 'j', 'chr11': 'k', 'chr12': 'l',
    'chr13': 'm', 'chr14': 'n', 'chr15': 'o', 'chr16': 'p',
    'chr17': 'q', 'chr18': 'r', 'chr19': 's', 'chr20': 't',
    'chr21': 'u', 'chr22': 'v', 'chrX': 'w', 'chrY': 'x'
}


def load_dipc_coords(file_path, chrom, region_start, region_end, resolution):
    """
    统一加载坐标，自动识别 .3dg.txt 或 .pdb 格式。
    """
    if file_path.endswith('.pdb'):
        return _load_pdb_coords(file_path, chrom, region_start, region_end, resolution)
    else:
        return _load_3dg_coords(file_path, chrom, region_start, region_end, resolution)


def _load_3dg_coords(file_path, chrom, region_start, region_end, resolution):
    """.3dg.txt 加载逻辑"""
    data = pd.read_csv(file_path, sep='\t')
    
    if chrom == 'all':
        chrom_data = data.copy()
    else:
        chrom_data = data[data['chr'] == chrom].copy()
    
    if region_end == -1:
        region_end = chrom_data['Genomic_Index'].max()
    
    n_bins = int((region_end - region_start) / resolution) + 1
    chrom_data = chrom_data[
        (chrom_data['Genomic_Index'] >= region_start) & 
        (chrom_data['Genomic_Index'] <= region_end)
    ]
    
    coords = np.zeros((n_bins, 3))
    if len(chrom_data) == 0:
        logger.warning(f"警告: {os.path.basename(file_path)} 中 {chrom}:{region_start}-{region_end} 无数据")
        return coords
    
    bin_indices = ((chrom_data['Genomic_Index'] - region_start) // resolution).astype(int)
    chrom_data = chrom_data.assign(bin=bin_indices)
    grouped = chrom_data.groupby('bin')[['mat_x', 'mat_y', 'mat_z']].mean()
    
    for bin_idx, row in grouped.iterrows():
        if int(bin_idx) < n_bins:
            coords[int(bin_idx)] = row.values
    return coords


def _load_pdb_coords(file_path, chrom, region_start, region_end, resolution):
    """新增的 PDB 加载逻辑"""
    target_chain = CHROM_TO_PDB_CHAIN.get(chrom)
    if target_chain is None:
        logger.error(f"未知染色体 {chrom}，无法从 PDB 提取")
        return np.zeros((0, 3))

    atoms = []
    with open(file_path, 'r') as f:
        for line in f:
            if line.startswith('ATOM') or line.startswith('HETATM'):
                chain = line[20:22].strip().lower()
                if chain != target_chain:
                    continue
                try:
                    x = float(line[30:38].strip())
                    y = float(line[38:46].strip())
                    z = float(line[46:54].strip())
                    # 基因组位置：优先最后一列
                    parts = line.split()
                    pos = int(parts[-1]) if len(parts) >= 10 else int(line[22:26].strip()) * 1000000
                    atoms.append((pos, x, y, z))
                except (ValueError, IndexError):
                    continue

    if not atoms:
        logger.warning(f"警告: PDB 中 {chrom}:{region_start}-{region_end} 无数据")
        return np.zeros((0, 3))

    atoms.sort(key=lambda x: x[0])
    positions = np.array([a[0] for a in atoms])
    coords_raw = np.array([[a[1], a[2], a[3]] for a in atoms])

    if region_end == -1:
        region_end = positions.max() + resolution

    mask = (positions >= region_start) & (positions < region_end)
    positions = positions[mask]
    coords_raw = coords_raw[mask]

    if len(positions) == 0:
        return np.zeros((0, 3))

    n_bins = int((region_end - region_start) / resolution) + 1
    result = np.zeros((n_bins, 3))
    bin_indices = ((positions - region_start) // resolution).astype(int)
    
    for i in range(len(positions)):
        if 0 <= bin_indices[i] < n_bins:
            if result[bin_indices[i]].sum() == 0:
                result[bin_indices[i]] = coords_raw[i]
            else:
                result[bin_indices[i]] = (result[bin_indices[i]] + coords_raw[i]) / 2

    return result


def load_hic_contacts(file_path, chrom, region_start, region_end, resolution):
    """Hi-C 接触对加载（保持原逻辑）"""
    # 识别文件格式
    try:
        # 尝试读取表头，判断是 .con.txt 还是普通 pairs 格式
        first_line = pd.read_csv(file_path, sep='\t', nrows=0, header=None)
        num_cols = len(first_line.columns)
        
        if num_cols >= 6:
            # .con.txt 格式：Chrom0, Genomic Index0, Haplotype0, Chrom1, Genomic Index1, Haplotype1
            data = pd.read_csv(file_path, sep='\t', header=0)
            data['Chrom0'] = data['Chrom0'].astype(str)
            data['Chrom1'] = data['Chrom1'].astype(str)
            data['Genomic Index0'] = data['Genomic Index0'].astype(int)
            data['Genomic Index1'] = data['Genomic Index1'].astype(int)
        elif num_cols ==4:
            # pairs 格式：chr1 pos1 chr2 pos2
            data = pd.read_csv(file_path, sep='\t', header=0, names=['chrom0', 'pos0', 'chrom1', 'pos1'],comment=None)
            data['Chrom0'] = data['chrom0'].astype(str)
            data['Chrom1'] = data['chrom1'].astype(str)
            data['Genomic Index0'] = data['pos0'].astype(int)
            data['Genomic Index1'] = data['pos1'].astype(int)
        else:
            raise ValueError(f"无法识别 Hi-C 文件格式({num_cols}coloums): {file_path}")
    except Exception as e:
        raise ValueError(f"处理Hi-C文件发生错误:{e}")

    # 染色体过滤
    if chrom != 'all':
        chrom_num = chrom.replace('chr', '')
        data = data[(data['Chrom0'] == chrom_num) | (data['Chrom0'] == chrom)]
        data = data[(data['Chrom1'] == chrom_num) | (data['Chrom1'] == chrom)]

    # 区域过滤
    if region_end != -1:
        data = data[
            (data['Genomic Index0'] >= region_start) & (data['Genomic Index0'] <= region_end) &
            (data['Genomic Index1'] >= region_start) & (data['Genomic Index1'] <= region_end)
        ]

    # 输出格式：chr1 pos1 chr2 pos2
    pairs = []
    for _, row in data.iterrows():
        chr1 = 'chr' + str(row['Chrom0']) if not str(row['Chrom0']).startswith('chr') else str(row['Chrom0'])
        chr2 = 'chr' + str(row['Chrom1']) if not str(row['Chrom1']).startswith('chr') else str(row['Chrom1'])
        pairs.append([chr1, int(row['Genomic Index0']), chr2, int(row['Genomic Index1'])])

    return np.array(pairs, dtype=object) if pairs else np.zeros((0, 4), dtype=object)


def process_cell(input_dir, output_dir, chrom, region_start, region_end, resolution, assembly='hg19', rep_type='original'):
    """
    处理细胞数据，自动识别输入文件类型。
    支持: .3dg.txt + .con.txt 或 .pdb + .pairs.txt 等组合。
    """
    logger.info(f"开始处理细胞: {input_dir}")
    try:
        os.makedirs(output_dir, exist_ok=True)
        region_start = max(0, region_start)

        # 查找坐标文件（.3dg.txt 或 .pdb）
        coord_files = []
        hic_files = []
        for root, dirs, files in os.walk(input_dir):
            for f in files:
                if f.endswith('.3dg.txt') or f.endswith('.pdb'):
                    coord_files.append(os.path.join(root, f))
                if f.endswith('.con.txt') or f.endswith('_contact_pairs.txt') or f.endswith('_pairs.txt'):
                    hic_files.append(os.path.join(root, f))

        if not coord_files:
            raise FileNotFoundError(f"在 {input_dir} 中未找到坐标文件 (.3dg.txt 或 .pdb)")
        if not hic_files:
            raise FileNotFoundError(f"在 {input_dir} 中未找到 Hi-C 文件 (.con.txt 或 pairs 文件)")

        # 使用第一个找到的文件
        dipc_file = coord_files[0]
        hic_file = hic_files[0]

        # 提取数据
        coords = load_dipc_coords(dipc_file, chrom, region_start, region_end, resolution)
        hic_pairs = load_hic_contacts(hic_file, chrom, region_start, region_end, resolution)

        if len(coords) == 0:
            logger.warning(f"警告: {dipc_file} 中 {chrom}:{region_start}-{region_end} 无坐标数据")

        # 保存坐标文件
        coords_dir = os.path.join(output_dir, "coords", f"chrom_{chrom}")
        coords_file = os.path.join(coords_dir, f'{chrom}_{resolution}bp_{rep_type}_true_coords.npy')
        os.makedirs(coords_dir, exist_ok=True)
        np.save(coords_file, coords)

        # 保存接触对文件
        pairs_dir = os.path.join(output_dir, "hic_pairs", f"chrom_{chrom}")
        pairs_file = os.path.join(pairs_dir, f'{chrom}_{resolution}bp_{rep_type}_hic_pairs.txt')
        os.makedirs(pairs_dir, exist_ok=True)

        with open(pairs_file, 'w') as f:
            for row in hic_pairs:
                if len(row) >= 4:
                    f.write(f'{row[0]} {int(row[1])} {row[2]} {int(row[3])}\n')

        # 检查文件是否有效
        generated_files = [coords_file]
        if os.path.getsize(pairs_file) > 0:
            generated_files.append(pairs_file)
        else:
            os.remove(pairs_file)
            logger.warning(f"警告: 接触对文件为空，已删除 {pairs_file}")

        logger.info(f"处理完成: coords shape={coords.shape}, hic_pairs count={len(hic_pairs)}")
        return generated_files

    except Exception as e:
        log_exception(logger, e, context=f"process_cell - {input_dir}")
        raise