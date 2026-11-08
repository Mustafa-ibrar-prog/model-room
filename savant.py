import urllib.request, re, os
UA = {"User-Agent": "Mozilla/5.0 (compatible; ModelRoom research)"}
os.makedirs("savant", exist_ok=True)
def get(u):
    try:
        r = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60); return r.status, r.read()
    except Exception as e:
        return str(e), b""
st, js = get("https://nflsavant.com/assets/index-D_vWw4bo.js")
print("js", st, len(js))
t = js.decode("utf-8", "ignore")
open("savant/bundle_strings.txt", "w").write("\n".join(sorted(set(re.findall(r'"(/(?:api|data|download|csv)[^"]{0,120})"', t) + re.findall(r'`(/(?:api|data|download)[^`]{0,120})`', t)))))
keys = ["nflverse", "nflfastR", "license", "License", "CC-BY", "Creative Commons", "Terms", "csv", "CSV", "download", "Download", "Next Gen", "FTN", "Pro Football Reference", "PFF", "attribution", "copyright", "©", "Sportradar"]
with open("savant/bundle_context.txt", "w") as f:
    for k in keys:
        for m in list(re.finditer(re.escape(k), t))[:6]:
            f.write(f"--- {k}: " + t[max(0, m.start() - 250): m.end() + 250].replace("\n", " ") + "\n")
# chunks referenced
chunks = sorted(set(re.findall(r'assets/[A-Za-z0-9_\-]+\.js', t)))
open("savant/chunks.txt", "w").write("\n".join(chunks))
for c in chunks:
    if re.search(r'(?i)about|data|download|terms|legal|faq|source', c):
        s2, b = get("https://nflsavant.com/" + c)
        tt = b.decode("utf-8", "ignore")
        with open("savant/bundle_context.txt", "a") as f:
            for k in keys:
                for m in list(re.finditer(re.escape(k), tt))[:6]:
                    f.write(f"--- [{c}] {k}: " + tt[max(0, m.start() - 300): m.end() + 300].replace("\n", " ") + "\n")
print("chunks", len(chunks))
