# ============================
# 压缩解压技能 — ZIP/TAR 打包与释放
# ============================
EXTENSION_NAME = "compression"
EXTENSION_DESC = "文件和文件夹的压缩与解压（支持 ZIP、TAR、TAR.GZ 格式）"
EXTENSION_TOOLS = ["compress_zip", "extract_zip", "compress_tar", "list_archive"]
EXTENSION_DEPS = ["zipfile", "tarfile", "os"]
EXTENSION_VERSION = "1.0"

import zipfile, tarfile, os

def compress_zip(source_path: str, output_path: str = ""):
    """将文件或文件夹压缩为 ZIP 文件
    
    Args:
        source_path: 要压缩的文件或文件夹路径
        output_path: 输出的 ZIP 文件路径（留空则自动命名）
    """
    if not os.path.exists(source_path):
        return {"success": False, "error": f"路径不存在: {source_path}"}
    if not output_path:
        basename = os.path.basename(source_path.rstrip('/\\'))
        dirname = os.path.dirname(source_path)
        output_path = os.path.join(dirname, basename + ".zip")
    try:
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            if os.path.isfile(source_path):
                zf.write(source_path, os.path.basename(source_path))
                count = 1
            else:
                count = 0
                for root, dirs, files in os.walk(source_path):
                    for f in files:
                        fpath = os.path.join(root, f)
                        arcname = os.path.relpath(fpath, os.path.dirname(source_path))
                        zf.write(fpath, arcname)
                        count += 1
        size = os.path.getsize(output_path)
        return {"success": True, "output": output_path, "files": count, "size": size}
    except Exception as e:
        return {"success": False, "error": str(e)}

def extract_zip(archive_path: str, output_dir: str = ""):
    """解压 ZIP 文件到指定目录
    
    Args:
        archive_path: ZIP 文件路径
        output_dir: 输出目录（留空则解压到同目录下）
    """
    if not os.path.exists(archive_path):
        return {"success": False, "error": f"文件不存在: {archive_path}"}
    if not output_dir:
        output_dir = os.path.splitext(archive_path)[0]
    try:
        os.makedirs(output_dir, exist_ok=True)
        with zipfile.ZipFile(archive_path, 'r') as zf:
            zf.extractall(output_dir)
            count = len(zf.namelist())
        return {"success": True, "output_dir": output_dir, "files": count}
    except Exception as e:
        return {"success": False, "error": str(e)}

def compress_tar(source_path: str, output_path: str = "", mode: str = "gz"):
    """将文件或文件夹压缩为 TAR 文件（支持 gz/bz2/xz 压缩）
    
    Args:
        source_path: 源路径
        output_path: 输出路径（留空自动命名）
        mode: 压缩模式 "gz"(默认) / "bz2" / "xz" / ""(不压缩)
    """
    if not os.path.exists(source_path):
        return {"success": False, "error": f"路径不存在: {source_path}"}
    if not output_path:
        basename = os.path.basename(source_path.rstrip('/\\'))
        dirname = os.path.dirname(source_path)
        ext = ".tar.gz" if mode == "gz" else f".tar.{mode}" if mode else ".tar"
        output_path = os.path.join(dirname, basename + ext)
    try:
        wmode = f"w:{mode}" if mode else "w"
        with tarfile.open(output_path, wmode) as tf:
            tf.add(source_path, arcname=os.path.basename(source_path.rstrip('/\\')))
        size = os.path.getsize(output_path)
        return {"success": True, "output": output_path, "size": size}
    except Exception as e:
        return {"success": False, "error": str(e)}

def list_archive(archive_path: str):
    """列出压缩包内的文件清单
    
    Args:
        archive_path: 压缩文件路径（支持 .zip / .tar / .tar.gz）
    """
    if not os.path.exists(archive_path):
        return {"success": False, "error": f"文件不存在: {archive_path}"}
    try:
        name = archive_path.lower()
        files = []
        if name.endswith('.zip'):
            with zipfile.ZipFile(archive_path, 'r') as zf:
                for info in zf.infolist():
                    files.append({
                        "name": info.filename,
                        "size": info.file_size,
                        "compress_size": info.compress_size,
                        "is_dir": info.filename.endswith('/')
                    })
        elif name.endswith(('.tar', '.tar.gz', '.tar.bz2', '.tar.xz', '.tgz')):
            with tarfile.open(archive_path, 'r') as tf:
                for m in tf.getmembers():
                    files.append({
                        "name": m.name,
                        "size": m.size,
                        "is_dir": m.isdir()
                    })
        else:
            return {"success": False, "error": f"不支持的格式: {archive_path}"}
        return {"success": True, "archive": archive_path, "files": files, "total": len(files)}
    except Exception as e:
        return {"success": False, "error": str(e)}

def setup(ext_mgr, agent):
    ext_mgr.register_tool("compress_zip", compress_zip, "将文件或文件夹压缩为 ZIP")
    ext_mgr.register_tool("extract_zip", extract_zip, "解压 ZIP 文件到指定目录")
    ext_mgr.register_tool("compress_tar", compress_tar, "将文件或文件夹压缩为 TAR.GZ/BZ2/XZ")
    ext_mgr.register_tool("list_archive", list_archive, "列出压缩包内的文件清单")
    ext_mgr.register_skill(EXTENSION_NAME, EXTENSION_DESC, EXTENSION_TOOLS, EXTENSION_DEPS, EXTENSION_VERSION)

if "ext_mgr" in dir():
    setup(ext_mgr, agent)
