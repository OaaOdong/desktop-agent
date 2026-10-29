#!/usr/bin/env python
"""示例 MCP server：提供一个 get_weather 工具。

手写实现（不依赖 mcp SDK），只为看清协议本质（P31）：
  读一行 JSON → 看 method → 调函数 → 写一行 JSON（flush）。
真实项目里用 FastMCP 一个装饰器就能吞掉全部样板（P32）。

重要（P29/P34）：stdio 下 stdout 是协议通道，任何 print 都会污染协议；
所以所有调试日志一律写 stderr。
"""
import json
import sys


TOOLS = [
    {
        "name": "get_weather",
        "description": (
            "查询某个城市的实时天气。当用户问冷热、下雨、穿衣、是否适合出行时使用。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "城市名，如：杭州"}
            },
            "required": ["city"],
        },
    }
]

# 假数据；真实实现这里会去调天气 API
_FAKE = {
    "杭州": "多云，22℃，湿度 61%，东南风 2 级",
    "北京": "晴，15℃，湿度 30%，西北风 4 级",
    "上海": "小雨，19℃，湿度 85%，东风 3 级",
}


def handle(method, params, rid):
    if method == "initialize":
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "class-weather", "version": "1.0.0"},
        }
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments", {})
        if name == "get_weather":
            city = args.get("city", "")
            text = _FAKE.get(city, f"暂无 {city} 的数据（示例数据仅含杭州/北京/上海）")
            return {"content": [{"type": "text", "text": f"{city}：{text}"}]}
        return {"content": [{"type": "text", "text": f"未知工具 {name}"}], "isError": True}
    # 通知类（无 id）不需要回复
    return None


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = req.get("method")
        params = req.get("params", {})
        rid = req.get("id")
        # 通知（如 notifications/initialized）没有 id，不回复
        if rid is None:
            continue
        result = handle(method, params, rid)
        if result is None:
            # 对未知 method 给个错误回复，避免客户端一直等
            resp = {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"method not found: {method}"}}
        else:
            resp = {"jsonrpc": "2.0", "id": rid, "result": result}
        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
