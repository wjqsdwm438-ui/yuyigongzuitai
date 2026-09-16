# 项目环境部署

案例检索需要 Semantica 0.6.8。只有源码、没有项目虚拟环境时，入口使用宿主 Python，会报“Semantica 依赖不可用”。安装包无需部署外部服务；本地案例检索使用无模型的 ContextGraph。

## 安装

在仓库根运行以下 PowerShell 命令，需要已安装 uv 和联网下载权限。Python 运行时、虚拟环境和缓存均留在项目内，不注册全局 Python、不修改 PATH。每一步成功后再执行下一步。

```powershell
$repoRoot = (Get-Location).Path
$env:UV_PYTHON_INSTALL_DIR = Join-Path $repoRoot '.运行时-runtime'
$env:UV_CACHE_DIR = Join-Path $repoRoot '临时-tmp/uv-cache'
uv python install 3.12.13 --no-bin --no-registry
uv venv --allow-existing --python "$repoRoot/.运行时-runtime/cpython-3.12.13-windows-x86_64-none/python.exe" .环境-venv
uv pip install --python .环境-venv/Scripts/python.exe -r 依赖-dependencies/Windows-Python312固定版本.txt
uv pip check --python .环境-venv/Scripts/python.exe
```

`.运行时-runtime`是虚拟环境依赖的正式运行时，不要作为临时缓存删除。环境包含绝对路径，移动仓库后按上述步骤重建。三类本地目录均已忽略 Git 提交。

## 验证与使用

```powershell
.环境-venv/Scripts/python.exe -X utf8 -B 脚本-scripts/验证Semantica.py
.环境-venv/Scripts/python.exe -X utf8 -B -m unittest discover -s 测试-tests -v
python -X utf8 -B 工作台.py --项目 E:/yuyigongzuitai 项目状态
```

业务项目不同于工作台时，将`--项目`改为真实业务根目录。组件验证使用合成材料，覆盖正式导入、中文先例查询、保存与独立进程重载；测试覆盖检索、项目隔离与审阅闭环，不代表原业务案例已诊断。

运行验证报告写入`导出-exports/Semantica运行验证.json`。确认组件可用后，原任务应在原业务项目使用`任务列表`定位并`续接`；如果依赖失败使初始事务回滚、尚无任务记录，则使用原材料重新`处理`，完成语义审阅、`提交审阅`和`导出报告`。
