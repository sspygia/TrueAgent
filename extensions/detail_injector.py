# ============================================
# 高频细节引擎 — 从参考照片学习纹理模式
# ============================================
# 原理: 对参考照片做高通滤波提取纹理骨架，
#       然后叠加到程序化输出上
# ============================================

EXTENSION_NAME = "detail_injector"
EXTENSION_DESC = "高频细节引擎 — 从参考照片学习并注入纹理模式"

import os, json
import numpy as np
from PIL import Image

TEXTURE_DIR = r'D:\Ai电脑智能体\v5.9\data\textures'
os.makedirs(TEXTURE_DIR, exist_ok=True)


class TextureAnalyzer:
    """从真实照片提取纹理模式"""
    
    @staticmethod
    def highpass(arr, sigma=3):
        """高通滤波: 总能量 - 低通 = 高频细节"""
        from scipy.ndimage import gaussian_filter
        low = gaussian_filter(arr.astype(float), sigma)
        return arr.astype(float) - low
    
    @staticmethod
    def extract_texture_map(img_path, output_size=(256, 256)):
        """从图片提取纹理特征图
        
        返回:
            detail_map: 高频能量分布图 (灰度)
            orientation: 局部方向场
        """
        img = Image.open(img_path).convert('L')  # 灰度
        arr = np.array(img, dtype=float)
        
        # 高通滤波
        high = TextureAnalyzer.highpass(arr, 2)
        
        # 计算局部能量 (梯度幅值)
        gy, gx = np.gradient(high)
        energy = np.sqrt(gx**2 + gy**2)
        
        # 归一化
        energy = energy / (energy.mean() + 1e-6)
        
        # 缩放到统一大小
        from scipy.ndimage import zoom
        h, w = energy.shape
        scale_y = output_size[1] / h
        scale_x = output_size[0] / w
        energy = zoom(energy, (scale_y, scale_x))
        
        # 方向场 (梯度方向)
        orientation = np.arctan2(gy, gx)
        orientation = zoom(orientation, (scale_y, scale_x))
        
        return {
            'energy': np.clip(energy, 0, 10),
            'orientation': orientation,
            'source': os.path.basename(img_path)
        }
    
    @staticmethod
    def learn_texture_library(ref_dir, output_name='texture_library.npz'):
        """批量学习纹理库"""
        from scipy.ndimage import zoom
        
        files = [f for f in os.listdir(ref_dir) 
                if f.lower().endswith(('.jpg', '.png', '.jpeg'))]
        
        if not files:
            return None
        
        # 提取所有纹理
        all_energy = []
        for f in files[:10]:  # 最多10张
            try:
                tex = TextureAnalyzer.extract_texture_map(os.path.join(ref_dir, f))
                all_energy.append(tex['energy'])
                print(f'    纹理: {f}')
            except Exception as e:
                print(f'    跳过 {f}: {e}')
        
        if not all_energy:
            return None
        
        # 平均纹理模式
        avg_energy = np.mean(all_energy, axis=0)
        
        # 保存
        path = os.path.join(TEXTURE_DIR, output_name)
        np.savez(path, avg_energy=avg_energy, num_sources=len(all_energy))
        
        return {
            'path': path,
            'shape': avg_energy.shape,
            'sources': len(all_energy)
        }


class DetailInjector:
    """高频细节注入器"""
    
    def __init__(self):
        self._texture_cache = {}
        self._load_texture_library()
    
    def _load_texture_library(self):
        """加载预计算纹理库"""
        path = os.path.join(TEXTURE_DIR, 'texture_library.npz')
        if os.path.exists(path):
            data = np.load(path)
            self._texture_lib = data['avg_energy']
            print(f'  [DetailInjector] 加载纹理库: {self._texture_lib.shape}')
        else:
            self._texture_lib = None
    
    def inject(self, arr, strength=0.5, t=0):
        """注入高频细节
        
        参数:
            arr: (H,W,3) uint8 输入图像
            strength: 细节强度 0-1
            t: 时间(用于动画纹理滚动)
        
        返回:
            (H,W,3) uint8 增强后的图像
        """
        h, w = arr.shape[:2]
        result = arr.astype(np.float32)
        
        # 如果没有纹理库, 用 Procedural 噪声替代
        if self._texture_lib is None:
            detail = self._procedural_detail(h, w, t)
        else:
            # 缩放到目标尺寸
            from scipy.ndimage import zoom
            sy, sx = h / self._texture_lib.shape[0], w / self._texture_lib.shape[1]
            detail = zoom(self._texture_lib, (sy, sx))
            # 动画滚动
            if t != 0:
                shift = int(t * 30) % w
                detail = np.roll(detail, shift, axis=1)
        
        # 亮度自适应: 暗处细节少, 亮处细节多
        luminance = result.mean(axis=-1) / 255.0
        detail_weight = detail * (0.3 + 0.7 * luminance)
        
        # 注入细节 (只影响亮度, 不碰色相)
        for c in range(3):
            result[:,:,c] += detail_weight * strength * 20
        
        return np.clip(result, 0, 255).astype(np.uint8)
    
    def _procedural_detail(self, h, w, t=0):
        """备用: 用 Perlin 噪声生成高频细节"""
        try:
            from proc_media import ProcCore
            core = ProcCore()
            ny, nx = np.mgrid[0:h, 0:w]
            nx = nx / w + t * 0.01
            ny = ny / h + t * 0.008
            detail = core.fbm(nx * 50, ny * 45, 3)
            return np.clip(detail * 1.5, 0, 1)
        except ImportError:
            ny, nx = np.mgrid[0:h, 0:w]
            return np.sin(nx * 0.3 + ny * 0.2 + t) * 0.5 + 0.5
    
    def sharpen(self, arr, amount=1.0):
        """锐化 (Unsharp mask)"""
        from scipy.ndimage import gaussian_filter
        blur = gaussian_filter(arr.astype(float), 1.0)
        return np.clip(arr.astype(float) + (arr.astype(float) - blur) * amount, 0, 255).astype(np.uint8)


# ============================================================
# 全场景增强管线 v4
# ============================================================

def enhance_all(scene_fn, w, h, t=0, strength=0.3):
    """场景+细节注入+锐化"""
    arr = scene_fn(w, h, t)
    injector = DetailInjector()
    arr = injector.inject(arr, strength=strength, t=t)
    arr = injector.sharpen(arr, 0.5)
    return arr


# ============================================================
# 水面重写 v2 — 多层波+反射+泡沫
# ============================================================

def v4_water(w, h, t=0):
    """v4水面: 多层波浪 + 高频细节 + 动态反射"""
    try:
        from proc_media import ProcCore
        core = ProcCore()
    except ImportError:
        return np.zeros((h, w, 3), dtype=np.uint8)
    
    ny, nx = np.mgrid[0:h, 0:w]
    nx = nx/w; ny = ny/h
    
    # 多层波浪 (从低频到高频)
    waves = np.zeros_like(nx)
    for i in range(6):
        freq = 3 + i * 3
        speed = 0.08 + i * 0.05
        phase = i * 1.7
        w = core.fbm(nx*freq + t*speed + phase, ny*freq*0.8 + t*speed*0.7 + phase*0.5, 3)
        waves += w * (0.5 ** i)
    
    waves = waves / waves.max()
    
    # 参考色 (89, 131, 150) → (0.35, 0.51, 0.59)
    deep = np.array([0.25, 0.42, 0.52])     # 深水
    shallow = np.array([0.40, 0.56, 0.62])  # 浅水
    foam = np.array([0.70, 0.75, 0.80])     # 泡沫/反光
    
    r = deep[0] + (shallow[0]-deep[0])*waves + foam[0]*np.clip((waves-0.6)*5,0,1)*0.3
    g = deep[1] + (shallow[1]-deep[1])*waves + foam[1]*np.clip((waves-0.6)*5,0,1)*0.3
    b = deep[2] + (shallow[2]-deep[2])*waves + foam[2]*np.clip((waves-0.6)*5,0,1)*0.3
    
    # 天空倒影
    sky = np.clip((1-ny)*0.5, 0, 0.4)
    r += sky * 0.3; g += sky * 0.4; b += sky * 0.6
    
    colors = np.stack([r,g,b], axis=-1)
    
    result = np.clip(colors * 255, 0, 255).astype(np.uint8)
    
    # 注入高频细节
    try:
        injector = DetailInjector()
        result = injector.inject(result, strength=0.6, t=t)
        result = injector.sharpen(result, 0.8)
    except:
        pass
    
    return result


# ============================================================
# 学习纹理库
# ============================================================

def setup(ext_mgr, agent):
    # 从参考目录学习纹理
    ref_dir = r'D:\Ai电脑智能体\v5.9\data\outputs\references'
    if os.path.exists(ref_dir):
        result = TextureAnalyzer.learn_texture_library(ref_dir)
        if result:
            print(f'  [DetailInjector] 纹理库: {result["shape"]} ({result["sources"]}张参考)')
    
    injector = DetailInjector()
    agent._detail_injector = injector
    
    # 注册v4水面
    agent._v4_water = v4_water
    
    print(f'  [扩展] {EXTENSION_NAME}: 高频细节引擎已加载')
    print(f'    注入 → sharpen → 输出 (完整管线)')
    print(f'    水面v4: 6层波+倒影+泡沫+纹理注入', flush=True)


if 'ext_mgr' in dir() and 'agent' in dir():
    setup(ext_mgr, agent)
