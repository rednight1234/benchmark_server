# api/benchmark.py
import numpy as np
from scipy.stats import pearsonr, spearmanr
from scipy.spatial.distance import pdist, squareform
from scipy.spatial import procrustes
from sklearn.metrics import mean_squared_error
from .logger import setup_logger, log_exception
import matplotlib.pyplot as plt
from io import BytesIO
import base64
logger = setup_logger('main')

def clean_coords(pred_coords, true_coords):
    """返回清洗后的坐标对"""
    pred_valid_mask = ~np.isnan(pred_coords).any(axis=1)
    true_valid_mask = np.any(true_coords != 0, axis=1)
    valid_mask = pred_valid_mask & true_valid_mask
    n_total = len(true_coords)
    n_true_valid = int(np.sum(true_valid_mask))
    n_pred_valid = int(np.sum(pred_valid_mask))
    n_both_valid = int(np.sum(true_valid_mask & pred_valid_mask))
    coverage_info = {
        'n_points_total': n_total,
        'n_points_true_valid': n_true_valid,
        'n_points_pred_valid': n_pred_valid,
        'n_points_evaluated': n_both_valid
    }
    return pred_coords[valid_mask], true_coords[valid_mask], coverage_info

def compute_distance_correlation(pred_coords, true_coords):
    pred_dist = squareform(pdist(pred_coords))
    true_dist = squareform(pdist(true_coords))
    triu_idx = np.triu_indices(len(pred_coords), k=1)
    pcc, _ = pearsonr(pred_dist[triu_idx], true_dist[triu_idx])
    scc, _ = spearmanr(pred_dist[triu_idx], true_dist[triu_idx])
    mse = mean_squared_error(pred_dist[triu_idx], true_dist[triu_idx])
    return pcc, scc, mse


def align_and_benchmark(pred_coords, true_coords):
    """对齐后计算指标"""
    # 过滤全零行
    logger.info(f"预测形状:{pred_coords.shape}, 实际形状:{true_coords.shape}")
    pred, true, coverage_info = clean_coords(pred_coords, true_coords)
    if len(pred) < 3:
        return {'error': '有效坐标点少于3个'}, None
    try:
        aligned_true, aligned_pred, _ = procrustes(true, pred)
        pcc, scc, mse = compute_distance_correlation(aligned_pred, aligned_true)

        # 生成对比图
        fig, axes = plt.subplots(1, 2, figsize=(12, 5))
        # 左图：真实 vs 对齐后的预测
        axes[0].scatter(aligned_true[:, 0], aligned_true[:, 1], c='blue', s=5, alpha=0.6, label='True')
        axes[0].scatter(aligned_pred[:, 0], aligned_pred[:, 1], c='red', s=5, alpha=0.6, label='Predicted')
        axes[0].set_title('2D Projection (XY)')
        axes[0].legend()
        # 右图：距离散点图
        pred_dist = squareform(pdist(aligned_pred))
        true_dist = squareform(pdist(aligned_true))
        triu_idx = np.triu_indices(len(aligned_pred), k=1)
        axes[1].scatter(true_dist[triu_idx], pred_dist[triu_idx], s=2, alpha=0.5)
        axes[1].plot([0, true_dist[triu_idx].max()], [0, true_dist[triu_idx].max()], 'r--')
        axes[1].set_xlabel('True distances')
        axes[1].set_ylabel('Predicted distances')
        axes[1].set_title('Distance scatter')
        plt.tight_layout()

        buf = BytesIO()
        plt.savefig(buf, format='png', dpi=150)
        buf.seek(0)
        img_base64 = base64.b64encode(buf.read()).decode('utf-8')
        plt.close(fig)

        metrics = {
            'Distance_Pearson': pcc,
            'Distance_Spearman': scc,
            'Distance_MSE': mse
        }
        return {'eval_status':'success','metrics':metrics}, img_base64, coverage_info
    except Exception as e:
        return {
            'eval_status': 'failed',
            'error': str(e),
            'metrics': None
        }, None, coverage_info

def generate_chromatin_trajectory(pred_coords, true_coords=None, title="Chromatin 3D Structure"):
    """
    生成染色质三维轨迹图。
    左图：预测结构（颜色渐变表示基因组位置）
    右图（可选）：叠加真实结构
    """
    if true_coords is not None:
        # 确保尺寸一致
        pred_coords, true_coords, _= clean_coords(pred_coords, true_coords)
        n = min(len(pred_coords), len(true_coords))
        pred = pred_coords[:n]
        true = true_coords[:n]
        # 普氏对齐：平移+旋转+缩放
        mtx1, mtx2, disparity = procrustes(true, pred)
        # mtx1: 标准化后的真实坐标
        # mtx2: 对齐后的预测坐标（已缩放到与真实坐标相同的尺度）
        pred_aligned = mtx2
        true_aligned = mtx1
    else:
        pred_aligned = pred_coords
        true_aligned = None
    if true_aligned is not None:
        fig, axes = plt.subplots(1, 2, figsize=(14, 6), subplot_kw={'projection': '3d'})
        ax1, ax2 = axes
    else:
        fig, ax1 = plt.subplots(1, 1, figsize=(8, 7), subplot_kw={'projection': '3d'})
        ax2 = None
    # 颜色映射：从浅蓝到深蓝，表示基因组位置从起始到结束
    n_points = len(pred_aligned)
    colors = plt.cm.Blues(np.linspace(0.3, 1.0, n_points))

    # 左图：预测结构
    for i in range(n_points - 1):
        ax1.plot3D(pred_aligned[i:i+2, 0], pred_aligned[i:i+2, 1], pred_aligned[i:i+2, 2],
                   color=colors[i], linewidth=0.8, alpha=0.8)
    ax1.set_title(f'{title} - Predicted Structure(aligned)')
    ax1.set_xlabel('X')
    ax1.set_ylabel('Y')
    ax1.set_zlabel('Z')

    # 右图：叠加真实结构
    if true_coords is not None:
        # 绘制预测结构（半透明）
        for i in range(n_points - 1):
            ax2.plot3D(pred_aligned[i:i+2, 0], pred_aligned[i:i+2, 1], pred_aligned[i:i+2, 2],
                       color=colors[i], linewidth=0.8, alpha=0.4)
        # 绘制真实结构（橙色）
        for i in range(len(true_coords) - 1):
            ax2.plot3D(true_aligned[i:i+2, 0], true_aligned[i:i+2, 1], true_aligned[i:i+2, 2],
                       color='darkorange', linewidth=0.8, alpha=0.8)
        ax2.set_title(f'{title} - Overlay with True Structure')
        ax2.legend(['Predicted', 'True'])

    plt.tight_layout()
    buf = BytesIO()
    plt.savefig(buf, format='png', dpi=200)
    buf.seek(0)
    plt.close(fig)
    return buf

def generate_comparison_charts(eval_results):
    """根据多个模型的评估结果生成对比柱状图并返回 base64 字符串"""
    import matplotlib.pyplot as plt
    from io import BytesIO
    import base64

    models = list(eval_results.keys())
    if not models:
        return {}
    
    # 获取第一个模型的所有指标名称（跳过没有有效评估结果的模型）
    first_model_metrics = None
    for m in models:
        if 'metrics' in eval_results[m] and eval_results[m]['metrics']:
            first_model_metrics = eval_results[m]['metrics']
            break
    
    if first_model_metrics is None:
        return {'error': '所有模型均无有效评估结果'}
    
    metrics_names = list(first_model_metrics.keys())

    # 生成柱状图
    fig, axes = plt.subplots(1, len(metrics_names), figsize=(5 * len(metrics_names), 4))
    if len(metrics_names) == 1:
        axes = [axes]

    for i, metric in enumerate(metrics_names):
        values = []
        for m in models:
            if 'metrics' in eval_results[m] and metric in eval_results[m]['metrics']:
                values.append(eval_results[m]['metrics'][metric])
            else:
                values.append(0)  # 缺失指标时填0
        axes[i].bar(models, values)
        axes[i].set_title(metric)
        axes[i].tick_params(axis='x', rotation=45)

    plt.tight_layout()
    buf = BytesIO()
    plt.savefig(buf, format='png', dpi=150)
    buf.seek(0)
    bar_chart = base64.b64encode(buf.read()).decode()
    plt.close(fig)

    # 构建指标表格（包含覆盖率）
    metrics_table = {}
    for m in models:
        if 'metrics' in eval_results[m]:
            metrics_table[m] = dict(eval_results[m]['metrics'])
            # 添加覆盖率信息
            if 'coverage' in eval_results[m]:
                metrics_table[m]['Evaluated Points'] = eval_results[m]['coverage'].get('n_evaluated', 0)
        else:
            metrics_table[m] = {'Error': '评估失败'}

    return {
        'metrics_table': metrics_table,
        'bar_chart': f"data:image/png;base64,{bar_chart}",
        'individual_results': eval_results
    }