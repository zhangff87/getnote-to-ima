#!/usr/bin/env python3
"""get笔记 -> ima知识库 自动同步"""
import os, sys, json, hashlib, hmac, time, datetime
import urllib.parse, urllib.request
from http.client import HTTPSConnection
from pathlib import Path

C = {
    "gc": os.environ["GETNOTE_CLIENT_ID"],
    "gk": os.environ["GETNOTE_API_KEY"],
    "ic": os.environ["IMA_OPENAPI_CLIENTID"],
    "ik": os.environ["IMA_OPENAPI_APIKEY"],
    "kb": "y1LoQE689w8Sf8kc7guV7nF7fLbFYGfAWU03rs0UCns=",
    "fd": "folder_7479894850170829",
    "fd2": "folder_7479922402550248",
}
SF = "sync_state.json"

def gn(m, p, d=None):
    req = urllib.request.Request(f"https://openapi.biji.com{p}", data=d, method=m)
    req.add_header("Authorization", C["gk"])
    req.add_header("X-Client-ID", C["gc"])
    if d: req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def ima(api, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"https://ima.qq.com/{api}", data=data, method="POST")
    req.add_header("ima-openapi-clientid", C["ic"])
    req.add_header("ima-openapi-apikey", C["ik"])
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())

def h1(k, d):
    if isinstance(k, str): k = k.encode()
    if isinstance(d, str): d = d.encode()
    return hmac.new(k, d, hashlib.sha1).hexdigest()

def up(title, content, ds):
    safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in title)[:40]
    fn = f"{ds}_{safe}.txt"
    tp = f"/tmp/{fn}"
    with open(tp, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n日期：{ds}\n来源：get笔记\n\n---\n\n{content}")
    fs = os.path.getsize(tp)
    r = ima("openapi/wiki/v1/create_media", {
        "media_type": 13, "file_name": fn, "file_size": fs,
        "content_type": "text/plain", "knowledge_base_id": C["kb"],
        "file_ext": "txt", "folder_id": C["fd"]})
    if r.get("code") != 0: print(f"  X create_media失败"); os.remove(tp); return False
    mid, cred = r["data"]["media_id"], r["data"]["cos_credential"]
    with open(tp, "rb") as f: fc = f.read()
    host = f"{cred['bucket']}.cos.{cred['region']}.myqcloud.com"
    pth = f"/{cred['cos_key']}"
    st, et = str(int(time.time())), str(int(time.time()) + 3600)
    kt = f"{st};{et}"
    sk = h1(cred["secret_key"], kt)
    hdrs = {"content-length": str(len(fc)), "host": host}
    hk = sorted(hdrs.keys())
    hs = "&".join([f"{k}={urllib.parse.quote(hdrs[k])}" for k in hk])
    ss = f"sha1\n{kt}\n{hashlib.sha1(f'put\n{pth}\n\n{hs}\n'.encode()).hexdigest()}\n"
    sg = h1(sk, ss)
    auth = "&".join(["q-sign-algorithm=sha1", f"q-ak={cred['secret_id']}",
        f"q-sign-time={kt}", f"q-key-time={kt}",
        "q-header-list=" + ";".join(hk), "q-url-param-list=", f"q-signature={sg}"])
    conn = HTTPSConnection(host, 443)
    conn.request("PUT", pth, body=fc, headers={
        "Content-Type": "text/plain", "Content-Length": hdrs["content-length"],
        "Authorization": auth, "x-cos-security-token": cred["token"]})
    resp = conn.getresponse(); resp.read(); conn.close()
    if resp.status >= 300: print(f"  X COS上传失败"); os.remove(tp); return False
    # 觉察日记→专属文件夹，其他→我的get笔记
    folder = C["fd"] if "觉察日记" in title else C["fd2"]
    r2 = ima("openapi/wiki/v1/add_knowledge", {
    "media_type": 13, "media_id": mid, "title": title,
    "knowledge_base_id": C["kb"], "folder_id": folder})
    os.remove(tp)
    if r2.get("code") == 0: print(f"  V 导入成功: {title}"); return True
    print(f"  X add_knowledge失败"); return False

print("=" * 40)
print("get notes -> ima")
print(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
print("=" * 40)
state = {"last_sync": 0, "synced": []}
if os.path.exists(SF):
    with open(SF) as f: state = json.load(f)
ls = datetime.datetime.fromtimestamp(state["last_sync"]).strftime("%Y-%m-%d %H:%M") if state["last_sync"] else "从未"
print(f"上次同步: {ls}")
notes = gn("GET", "/open/api/v1/resource/note/list?cursor=").get("data", {}).get("notes", [])
sn = set(state["synced"])
nn = [n for n in notes if n.get("note_id") not in sn]
print(f"get notes返回 {len(notes)} 条，未同步 {len(nn)} 条")
if not nn: print("没有新笔记"); sys.exit(0)
ok = 0
for i, n in enumerate(nn, 1):
    nid, t = n.get("note_id", ""), n.get("title", "无标题") or "无标题"
    ct = n.get("create_time", 0)
    ds = datetime.datetime.fromtimestamp(ct).strftime("%Y%m%d") if ct else "unknown"
    print(f"\n[{i}/{len(nn)}] {t}")
    try:
        d = gn("GET", f"/open/api/v1/resource/note/detail?id={nid}")
        nd = d.get("data", {}).get("note", {})
        c = nd.get("content", "") or ""
        if c and up(t, c, ds):
            ok += 1; sn.add(nid)
            state["last_sync"] = max(state.get("last_sync", 0), ct)
            state["synced"] = list(sn)
            with open(SF, "w") as f: json.dump(state, f)
    except Exception as e: print(f"  X 出错: {e}")
print(f"\n完成！成功 {ok}/{len(nn)} 篇")
