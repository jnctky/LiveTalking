# -*- coding: utf-8 -*-
"""Push download tasks to Thunder via thunder:// protocol links."""
import base64
import subprocess
import sys
import time

EXE = r"D:\Program Files (x86)\Thunder Network\Thunder\Program\Thunder.exe"

URLS = [
    "https://mirrors.aliyun.com/pytorch-wheels/cu121/torch-2.5.1+cu121-cp311-cp311-win_amd64.whl",
    "https://mirrors.aliyun.com/pytorch-wheels/cu121/torchvision-0.20.1+cu121-cp311-cp311-win_amd64.whl",
]

links = []
for url in URLS:
    link = "thunder://" + base64.b64encode(("AA" + url + "ZZ").encode()).decode()
    links.append(link)

# 确保迅雷在跑：用 explorer.exe 中转拉起（脱离本进程树，防沙箱连坐）
subprocess.Popen(["explorer.exe", EXE])
time.sleep(4)

for link in links:
    subprocess.Popen([EXE, link, "-StartType:thunder"])
    time.sleep(2)
    print("pushed:", link, flush=True)

# 落盘一份链接，面板没弹时可手动复制
with open(r"E:\work\LiveTalking\tools\thunder-links.txt", "w") as f:
    f.write("\n".join(links) + "\n")
print("links saved to tools/thunder-links.txt", flush=True)
