// Read real incremental SSE output; completed local answers remain immediate.
export async function assistantStream(
  url,
  body,
  { signal, onDelta, onStatus } = {},
) {
  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok) {
    const result = await response.json().catch(() => ({}));
    throw new Error(
      result.detail?.message ||
        result.detail ||
        `连接失败（${response.status}）`,
    );
  }
  if (!response.body) throw new Error("当前浏览器无法接收逐步回答，请重试。");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "",
    result;
  function consume(frame) {
    const lines = frame.split("\n");
    const type =
      lines
        .find((line) => line.startsWith("event:"))
        ?.slice(6)
        .trim() || "message";
    const data = lines
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n");
    if (!data) return;
    const value = JSON.parse(data);
    if (type === "delta") onDelta?.(value.text || "");
    else if (type === "start" || type === "status")
      onStatus?.(value.message || "正在准备回答…");
    else if (type === "result") result = value;
    else if (type === "error")
      throw new Error(value.message || "回答中断，请重试。");
  }
  try {
    while (true) {
      const chunk = await reader.read();
      buffer += decoder.decode(chunk.value || new Uint8Array(), {
        stream: !chunk.done,
      });
      buffer = buffer.replace(/\r\n/g, "\n");
      let separator;
      while ((separator = buffer.indexOf("\n\n")) >= 0) {
        consume(buffer.slice(0, separator));
        buffer = buffer.slice(separator + 2);
      }
      if (chunk.done) break;
    }
    if (buffer.trim()) consume(buffer);
    if (!result) throw new Error("连接已结束，回答未完成。可以重新发送。");
    return result;
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
