import json
import uuid
import os
import base64
import requests
import websocket # uv add websocket-client
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from dotenv import load_dotenv

load_dotenv()

# [수정 포인트] 로컬 테스트 시에는 Azure VM의 공인 IP를 입력하세요.
# .env 파일에 AZURE_IP_ADDRESS=20.xxx.xxx.xxx 로 저장하거나 직접 수정하세요.
VM_IP = os.getenv("AZURE_IP_ADDRESS", "127.0.0.1") # <- 여기에 실제 Azure IP Address 입력
MCP_TRANSPORT = os.getenv("MCP_TRANSPORT")

# COMFY_ADDR = f"{VM_IP}:8188"

# AZURE_DOMAIN 있으면 HTTPS로, 없으면 로컬 IP로
AZURE_DOMAIN = os.getenv("AZURE_DOMAIN", "")
if AZURE_DOMAIN:
    COMFY_BASE_URL = f"https://{AZURE_DOMAIN}"
    COMFY_ADDR = f"{AZURE_DOMAIN}"  # WebSocket용은 별도 처리
else:
    COMFY_BASE_URL = f"http://{VM_IP}:8188"
    COMFY_ADDR = f"{VM_IP}:8188"

if MCP_TRANSPORT == "sse":
    mcp = FastMCP("Comfy-Remote-Test",
                  host="0.0.0.0",
                  port=8000,
                  transport_security=TransportSecuritySettings(
                      enable_dns_rebinding_protection=False  # 외부 IP 접근 허용
                  )
    )
else:
    mcp = FastMCP("Comfy-Remote-Test")

@mcp.tool()
def generate_image(prompt: str) -> str:
    """Azure VM의 ComfyUI를 원격 제어하여 이미지를 생성합니다."""
    client_id = str(uuid.uuid4())
    
    try:
        # 1. WebSocket 연결 (원격 VM 주소로)
        ws = websocket.WebSocket()
        # ws.connect(f"ws://{COMFY_ADDR}/ws?clientId={client_id}")
        ws_scheme = "wss" if AZURE_DOMAIN else "ws"
        ws.connect(f"{ws_scheme}://{COMFY_ADDR}/ws?clientId={client_id}")

        # 2. Workflow 파일 로드 (로컬 PC에 이 파일이 있어야 함)
        with open("Workflow1-API.json", "r", encoding="utf-8") as f:
            workflow = json.load(f)
        
        # FLUX 워크플로우에 맞게 프롬프트 주입 (노드 ID "6" 기준)
        workflow["3"]["inputs"]["text"] = prompt

        # 3. API 요청 (원격 VM 주소로)
        # res = requests.post(f"http://{COMFY_ADDR}/prompt", json={"prompt": workflow, "client_id": client_id})
        res = requests.post(f"{COMFY_BASE_URL}/prompt", json={"prompt": workflow, "client_id": client_id})
        res.raise_for_status()
        prompt_id = res.json()['prompt_id']

        # 4. 완료 대기 (WebSocket)
        while True:
            out = ws.recv()
            if isinstance(out, str):
                message = json.loads(out)
                if message['type'] == 'executing':
                    if message['data']['node'] is None and message['data']['prompt_id'] == prompt_id:
                        break 
            else: continue

        # 5. 생성된 이미지 다운로드
        # history = requests.get(f"http://{COMFY_ADDR}/history/{prompt_id}").json()
        history = requests.get(f"{COMFY_BASE_URL}/history/{prompt_id}").json()
        outputs = history[prompt_id]['outputs']
        
        for node_id in outputs:
            if 'images' in outputs[node_id]:
                filename = outputs[node_id]['images'][0]['filename']

                # 이미지 자체를 리턴할 때
                # img_res = requests.get(f"http://{COMFY_ADDR}/view", params={"filename": filename})
                # b64_str = base64.b64encode(img_res.content).decode('utf-8')
                # return f"data:image/png;base64,{b64_str}"

                # 이미지 URL을 리턴할 때
                image_url = f"{COMFY_BASE_URL}/view?filename={filename}&type=output"
                return f"이미지가 생성되었습니다: {image_url}"

        return "이미지 데이터를 찾을 수 없습니다."

    except Exception as e:
        return f"원격 연결 실패 ({COMFY_ADDR}): {str(e)}"

if __name__ == "__main__":
    if MCP_TRANSPORT == "sse":
        # 1. Azure VM용: SSE 모드 활성화 + 외부 접속 허용(0.0.0.0)
        print(f"🚀 Running in SSE mode on {VM_IP}:8000")
        mcp.run(transport='streamable-http')
    else:
        # 2. 로컬 테스트용: 기본 stdio 모드 (Inspector 접속용)
        print("🛠️ Running in Local stdio mode (Use MCP Inspector)")
        mcp.run()
