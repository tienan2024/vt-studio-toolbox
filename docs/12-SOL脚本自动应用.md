# SOL 脚本自动应用

最后更新：2026-11-12

## 使用

在“脚本生成与测试”配置产品规则，打开“变量清单 → 打开SOL”，选择流程和脚本，再点击“应用脚本到 SOL”。预览窗口明确显示目标流程/模块ID、沿用的变量和新增变量、VM安装目录、新方案路径。确认后导入当前生成的全部主脚本，通过VM原生编译并独立重载校验，再创建新的SOL。原方案及已有输出文件均不覆盖。此次不会执行检测流程。

受保护方案需在预览窗口再次输入密码：读取变量后不会保留密码。新方案保持原密码保护，密码只通过子进程stdin传入，不进入命令行参数、配置、应用日志或任务文件。应用需要本机完整VisionMaster x64 SDK及.NET Framework编译器，已验证VM4.4.0；未安装VM仍可读取变量、生成/复制/保存代码。

输入/输出同名同类型时保留原上游/下游绑定，不删除原变量。不使用AI时可自动补充未绑定的aiResult、Label_name兼容输入；其他必需输入缺失则拒绝应用，不能猜测上游。已有输出名称集合必须与生成脚本的四项输出一致，改名不能使原下游读取到过期变量。可先“使用此模块变量”确认映射，再切回SOL来源应用。

应用时禁用配置和目标编辑，后台显示阶段；完成/失败后恢复操作。关闭主窗口会等待任务完成。请先保存并关闭VisionMaster，避免其与SDK同时使用安装目录下的脚本编译环境。工具箱应用任务使用跨进程互斥锁，不中断用户其他进程。SDK阶段每次最多120秒，异常不交付方案；磁盘失败会删除本次创建的不完整输出。

## 保存与验证

全量SDK另存会正常重写模型临时路径、AssemblyGuid、图像源当前路径及存图UI缓存。工具不会直接交付这种全量另存：先让VM生成目标模块的完整原生参数记录，然后仅回填该记录，其他模块记录以及原ZIP资源文件保持原样。只组合已核验的版本7外层记录边界，不构造或猜改模块内部参数二进制。未知版本拒绝写入，版本5仍可只读检查。

封装使用本机VM自带SharpZipLib，保留原ZIP传统密码保护，不携带/分发厂商DLL。检查完整外层记录长度、非目标记录逐字节一致、VmServer拓扑/绑定元数据一致、其他资源条目CRC/长度与加密状态一致及目标完整UTF-8源码。封装副本再由独立SDK进程重新加载、检查端口并另存验证文件；确认源码仍在后才独占创建最终新文件。原文件SHA-256在前后核对。SDK加载/编译成功不等于现场相机、通信、模型及检测结果验证通过。

实现：sol_apply.py负责计划、互斥、临时文件、SDK适配器编译及验证；vm_bridge/SolScriptHost.cs使用VM原生动态端口、ShellContent文件导入、AddInputParam/AddOutputParam注册、SetShellContent编译及SaveAs。使用公开Modules集合递归获取模块ID，处理SDK模块对象懒加载，不通过名称猜目标。适配器不调用Run或SilentExecute；不会接管已打开的VM界面。

## CLI

```powershell
VTStudioCLI.exe script-apply --sol input.sol --module-id 9 --config product.json --output output-new.sol --vm-apps "D:\VM\VisionMaster4.4.0\Applications" --password-stdin
```

加密方案的密码从stdin单行读取；不提供--password参数。非加密方案省略--password-stdin，不交互提问。--config缺省为示例产品，--preserve-from可保留已有脚本两个USER CODE区。返回输出路径、目标ID、原生compile结果、reloaded/source_verified/other_records_unchanged/bindings_unchanged/source_unchanged及flows_run=false；不覆盖，失败退出1，参数错误退出2。

## 已验证

临时目录优先系统TEMP；估计空间不足时使用VM安装盘的VTStudioToolboxTemp，或用环境VT_TOOLBOX_TEMP显式指定。至少预留256MB或源文件五倍加128MB，临时方案、模块帧及适配器用后清理，不把凭据写入临时JSON。空间不足不会交付不完整输出。

用户提供的加密方案，模块9：原生编译0 Errors/0 Warnings，独立重载成功，完整生成源码一致，其他模块记录和绑定不变，原文件不变；结果保存在本机忽略的verification/native_script_apply_result.json。未运行产线检测流程，也未把示例规则自动作为生产配置部署。
