import { describe, expect, it } from "vitest";

import { createSseParser, type SseEvent } from "./sse";

describe("createSseParser", () => {
  it("emits events split across arbitrary chunks", () => {
    const events: SseEvent[] = [];
    const feed = createSseParser((e) => events.push(e));
    const stream = 'event: start\ndata: {"conversation_id":"c1"}\n\nevent: delta\ndata: {"text":"Olá, "}\n\n: keep-alive\n\nevent: delta\r\ndata: {"text":"mundo"}\r\n\r\n';
    for (let i = 0; i < stream.length; i += 7) feed(stream.slice(i, i + 7));
    expect(events).toEqual([
      { event: "start", data: { conversation_id: "c1" } },
      { event: "delta", data: { text: "Olá, " } },
      { event: "delta", data: { text: "mundo" } },
    ]);
  });

  it("waits for the blank line before emitting", () => {
    const events: SseEvent[] = [];
    const feed = createSseParser((e) => events.push(e));
    feed('event: done\ndata: {"sources":[]}\n');
    expect(events).toHaveLength(0);
    feed("\n");
    expect(events).toEqual([{ event: "done", data: { sources: [] } }]);
  });
});
