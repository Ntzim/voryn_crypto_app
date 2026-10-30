import { describe, expect, it } from "vitest";

import { upstreamHeaders } from "./upstream-headers";

describe("upstreamHeaders", () => {
  it("replaces a client-supplied X-Forwarded-For with the edge's X-Real-IP", () => {
    const out = upstreamHeaders(
      new Headers({ "x-forwarded-for": "203.0.113.7", "x-real-ip": "198.51.100.20" }),
    );
    expect(out.get("x-forwarded-for")).toBe("198.51.100.20");
    expect(out.get("x-real-ip")).toBeNull();
  });

  it("drops every forgeable client-address header", () => {
    const out = upstreamHeaders(
      new Headers({
        forwarded: "for=203.0.113.7",
        "x-forwarded-for": "203.0.113.7",
        "x-client-ip": "203.0.113.7",
        "true-client-ip": "203.0.113.7",
        "cf-connecting-ip": "203.0.113.7",
      }),
    );
    expect([...out.keys()]).toEqual([]);
  });

  it("forwards no address when the trusted header is missing or not an IP", () => {
    expect(upstreamHeaders(new Headers({ "x-forwarded-for": "203.0.113.7" })).has("x-forwarded-for")).toBe(false);
    expect(upstreamHeaders(new Headers({ "x-real-ip": "evil, 1.2.3.4" })).has("x-forwarded-for")).toBe(false);
  });

  it("supports another trusted header and IPv6", () => {
    const out = upstreamHeaders(new Headers({ "fly-client-ip": "2001:db8::1" }), "fly-client-ip");
    expect(out.get("x-forwarded-for")).toBe("2001:db8::1");
  });

  it("can disable address forwarding", () => {
    expect(upstreamHeaders(new Headers({ "x-real-ip": "198.51.100.20" }), "none").has("x-forwarded-for")).toBe(false);
  });

  it("keeps application headers and strips hop-by-hop ones", () => {
    const out = upstreamHeaders(
      new Headers({ cookie: "voryn_session=x", "x-csrf-token": "t", host: "evil.example", connection: "close" }),
    );
    expect(out.get("cookie")).toBe("voryn_session=x");
    expect(out.get("x-csrf-token")).toBe("t");
    expect(out.has("host")).toBe(false);
    expect(out.has("connection")).toBe(false);
  });
});
