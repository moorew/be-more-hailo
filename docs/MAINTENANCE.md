# BMO Maintenance Runbook

## "Nothing works" checklist (start here)

Almost every total-failure mode of BMO traces back to the Hailo-10H NPU being
unavailable — without it there is no LLM (hailo-ollama), no NPU Whisper STT,
and no VLM. Check in this order:

```bash
ls -l /dev/hailo0                      # must exist
lsmod | grep hailo                     # hailo1x_pci must be loaded
journalctl -k | grep -i hailo | tail   # firmware must report "loaded"
curl -s http://localhost:8000/api/tags # hailo-ollama must list models
```

If `/dev/hailo0` is missing, the kernel module didn't load — almost always
because **a kernel upgrade ran without rebuilding the DKMS module**.

## Recovering the Hailo driver after a kernel upgrade

```bash
dkms status                            # is hailo1x_pci built for $(uname -r)?
sudo dpkg --configure -a               # finish any interrupted upgrade first
sudo dkms build   hailo1x_pci/5.3.0 -k "$(uname -r)"
sudo dkms install hailo1x_pci/5.3.0 -k "$(uname -r)"
sudo modprobe hailo1x_pci
sudo systemctl restart bmo-ollama
```

If the DKMS build fails, read `/var/lib/dkms/hailo1x_pci/*/build/make.log`.

### Known source patch (applied 2026-07-09)

Kernels ≥ 6.15 removed `del_timer_sync()`. The hailo1x_pci **5.3.0** source
does not compile until you patch
`/usr/src/hailo1x_pci-5.3.0/linux/vdma/monitor.c`:

```c
-    del_timer_sync(&monitor->timer);
+    timer_delete_sync(&monitor->timer);   // available since kernel 6.2
```

**This patch lives outside the repo.** Reinstalling or upgrading the
`hailort-pcie-driver` package overwrites it — re-apply if the build breaks
again with `implicit declaration of function 'del_timer_sync'`.

## Symptom → cause map

| Symptom | Likely cause |
|---|---|
| Every request times out; hailo-ollama logs `HAILO_OUT_OF_PHYSICAL_DEVICES(74)` | Driver not loaded (above), or another process holds the single NPU |
| LLM works but STT is slow | NPU Whisper failed → CPU whisper.cpp fallback active (check agent logs) |
| BMO silent but faces animate | Volume/mute state in `settings.json`, or `output_device` index drifted (`aplay -l`) |
| Wake word never triggers | Mic index drifted (`arecord -l` vs `core/config.py`), or another process holds the mic |

## Dev workflow

```bash
source venv/bin/activate
ruff check .          # lint (config in pyproject.toml)
pytest                # unit tests in tests/unit/
```
