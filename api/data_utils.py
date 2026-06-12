import os
from collections import Counter

def analyze_pairs_file(file_path: str) -> dict:
    """分析 pairs 文件，返回统计信息"""
    stats = {
        'file_name': os.path.basename(file_path),
        'total_lines': 0,
        'chromosomes': Counter(),
        'positions': {'min': float('inf'), 'max': 0},
        'format_ok': True,
        'error': ''
    }
    try:
        with open(file_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split()
                if len(parts) < 4:
                    continue
                chr1, pos1, chr2, pos2 = parts[0], int(parts[1]), parts[2], int(parts[3])
                stats['chromosomes'][chr1] += 1
                stats['chromosomes'][chr2] += 1
                stats['positions']['min'] = min(stats['positions']['min'], pos1, pos2)
                stats['positions']['max'] = max(stats['positions']['max'], pos1, pos2)
                stats['total_lines'] += 1
        if stats['total_lines'] == 0:
            stats['format_ok'] = False
            stats['error'] = 'No valid contact pairs found.'
    except Exception as e:
        stats['format_ok'] = False
        stats['error'] = str(e)
    return stats