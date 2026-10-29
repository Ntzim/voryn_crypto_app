export type SseEvent = { event: string; data: unknown };

/**
 * Incremental Server-Sent Events parser: feed it decoded text chunks as they arrive and it
 * emits each complete event. `data` lines are joined and parsed as JSON.
 */
export function createSseParser(onEvent: (event: SseEvent) => void): (chunk: string) => void {
  let buffer = "";
  return (chunk) => {
    buffer = (buffer + chunk).replace(/\r\n?/g, "\n");
    let end: number;
    while ((end = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      let event = "message";
      const data: string[] = [];
      for (const line of block.split("\n")) {
        if (!line || line.startsWith(":")) continue;
        const colon = line.indexOf(":");
        const field = colon === -1 ? line : line.slice(0, colon);
        const value = colon === -1 ? "" : line.slice(colon + 1).replace(/^ /, "");
        if (field === "event") event = value;
        else if (field === "data") data.push(value);
      }
      if (data.length) onEvent({ event, data: JSON.parse(data.join("\n")) as unknown });
    }
  };
}
