"""Two-stage review: fast blocklist, then optional local Ollama judge.
Never a security boundary — network=none / proxy is. Returns (score 0-100, reasons list)."""
import os
import re
import urllib.request
import json

BLOCK = [
    (r"socket\s*\.\s*(socket|create_connection|AF_INET)", "raw sockets"),
    (r"smtplib|sendmail|port\s*25|port\s*587", "email sending"),
    (r"nmap|masscan|port.?scan|hydra|sqlmap", "scanning/bruteforce tools"),
    (r"xmrig|minerd|cgminer|nicehash|stratum\+tcp", "crypto miner"),
    (r"metasploit|msfvenom|mimikatz|bloodhound", "offsec tooling"),
    (r"ngrok|chisel|frp|reverse.?shell|/dev/tcp/", "tunneling/reverse shell"),
    (r"discord.*webhook|telegram.*bot.*token", "webhook exfil pattern"),
    (r"rm\s+-rf\s+/( |$)|mkfs|:?\(\)\{\s*:\|\:&\s*\};:", "destructive command"),
    (r"while\s+True.*requests\.(get|post)", "tight outbound loop"),
    (r"base64\.b64decode\(['\"][A-Za-z0-9+/=]{500,}", "large obfuscated blob"),
    (r"torch\.cuda.*while.*True|while.*True.*\.cuda\(\)", "possible GPU spin loop"),
    (r"(\bnc\b.*-e\s|/dev/tcp/|mkfifo\s+\S+\s*;\s*sh\s+-i|bash\s+-i\s+>&)", "reverse shell"),
]

CAUTION = [
    (r"(curl|wget).+\|\s*(bash|sh)\b", "pipes remote code into shell"),
]

ALLOW_DOMAINS_HINT = "github.com pypi.org files.pythonhosted.org huggingface.co cdn-lfs.huggingface.co"

def heuristic(code: str):
    score = 0
    reasons = []
    for pat, label in BLOCK:
        if re.search(pat, code, re.IGNORECASE):
            score += 35
            reasons.append(f"blocklist hit: {label}")
    for pat, label in CAUTION:
        if re.search(pat, code, re.IGNORECASE):
            score += 15
            reasons.append(f"caution: {label}")
    # outbound imports raise eyebrows in offline mode but ok in proxied
    if re.search(r"\brequests\b|\burllib\b|\bhttpx\b|\bsocket\b", code):
        score += 10
        reasons.append("makes network calls (fine in proxied, blocked in offline)")
    if len(code) > 200_000:
        score += 15
        reasons.append("very large submission (>200k chars)")
    return min(score, 100), reasons

def api_judge(code: str, net: str):
    """External OpenAI-compatible judge. Returns (score, reasons) or None to fall back."""
    key = os.environ.get("REVIEW_API_KEY", "")
    if not key:
        return None
    url = os.environ.get("REVIEW_API_URL", "https://api.openai.com/v1/chat/completions")
    model = os.environ.get("REVIEW_MODEL", "llama3.1:8b")
    sys = (
        "You review untrusted job code+config for a shared homelab. "
        f"Network mode={net} (offline=none, proxied=allowlisted logged proxy). "
        "Flag: malware, miners, spam/scan, tunneling, credential theft, persistence, "
        "destruction, infinite resource burn. Reply ONLY JSON "
        '{"score":0-100,"reasons":["..."]}. Score 0=safe example train script, '
        "100=definite malware/miner. Be lenient on normal ML/code."
    )
    body = {"model": model, "temperature": 0,
            "messages": [{"role": "system", "content": sys},
                         {"role": "user", "content": f"network={net}\n\n{code[:12000]}"}]}
    try:
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}",
                     "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
                     "Accept": "application/json", "Accept-Language": "en-US,en;q=0.9"},
            method="POST")
        with urllib.request.urlopen(req, timeout=45) as r:
            out = json.loads(r.read().decode())
        txt = out["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", txt, re.DOTALL)
        obj = json.loads(m.group(0) if m else txt)
        return int(obj.get("score", 50)), list(obj.get("reasons", []))[:8]
    except Exception:
        return None

def ollama_judge(code: str, net: str) -> tuple[int, list]:
    base = os.environ.get("OLLAMA_URL", "http://localhost:11434")
    model = os.environ.get("REVIEW_MODEL", "llama3.1:8b")
    prompt = (
        "You review untrusted GPU-job code for a shared homelab. "
        f"Network mode={net} (offline=none, proxied=allowlisted logged proxy). "
        "Flag: malware, miners, spam/scan, tunneling, credential theft, persistence, "
        "destruction, infinite resource burn. Reply ONLY JSON "
        '{"score":0-100,"reasons":["..."]}. Score 0=safe example torch train, '
        "100=definite malware/miner. Be lenient on normal ML code.\n\nCODE:\n" + code[:12000]
    )
    try:
        req = urllib.request.Request(
            base + "/api/generate",
            data=json.dumps({"model": model, "prompt": prompt, "stream": False}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            out = json.loads(r.read().decode())
        txt = out.get("response", "{}")
        # model may wrap in code fences
        m = re.search(r"\{.*\}", txt, re.DOTALL)
        obj = json.loads(m.group(0) if m else txt)
        return int(obj.get("score", 50)), list(obj.get("reasons", []))[:8]
    except Exception as e:
        return 0, [f"ollama unavailable, heuristic only ({e.__class__.__name__})"]

def review(code: str, net: str):
    h_score, h_reasons = heuristic(code)
    if h_score >= 70:
        return h_score, h_reasons + ["auto-reject threshold (heuristic)"]
    r = api_judge(code, net)
    if r is not None:
        score, o_reasons = r
        return min(max(h_score, score), 100), h_reasons + [f"ai: {x}" for x in o_reasons]
    o_score, o_reasons = ollama_judge(code, net)
    score = max(h_score, o_score)
    reasons = h_reasons + [f"ai: {r}" for r in o_reasons]
    return min(score, 100), reasons
