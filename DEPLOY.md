# DEPLOY

> **状态**:in progress — 内容随代码状态同步更新。基本启动方式见 [INSTALL.md](INSTALL.md)。

## Local deployment

- 默认端口:`127.0.0.1:8765`(通过 `PCC_LIVE_PORT` 覆盖)
- 默认绑定本地回环;`0.0.0.0` 需显式 `PCC_LIVE_ALLOW_LAN=1`

## Firewall

- 仅本地回环:无需防火墙配置
- LAN 暴露:启用 `PCC_LIVE_ALLOW_LAN=1` 后,需在系统防火墙放行 `8765`

## Model cache

- FunASR(`iic/SenseVoiceSmall`):`~/.cache/modelscope/`(~220 MB,首次下载后离线可用)
- BGE-M3 embeddings(若启用):`~/Library/Caches/.../chroma/onnx_models/all-MiniLM-L6-v2/`
