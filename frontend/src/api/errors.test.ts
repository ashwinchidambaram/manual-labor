import { describe, expect, it } from "vitest";
import { ApiError, unwrap } from "./client";

describe("ApiError keeps the server body", () => {
  it("exposes the parsed 409 body for callers that need conflict details", () => {
    const body = { detail: { conflict: { field: "text", server: "x" } }, code: "conflict" };
    try {
      unwrap({ error: body, response: new Response(null, { status: 409 }) });
      expect.unreachable();
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      const err = e as ApiError;
      expect(err.status).toBe(409);
      expect(err.code).toBe("conflict");
      expect(err.body).toEqual(body);
    }
  });
});
