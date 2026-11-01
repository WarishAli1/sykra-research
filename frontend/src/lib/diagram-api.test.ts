import { describe, expect, it, vi } from "vitest";
import { createFlowchartDocument } from "@/features/studio/core/document";
import { diagramApi } from "./diagram-api";

describe("diagram persistence API", () => {
  it("loads and saves a validated document payload", async () => {
    const document = createFlowchartDocument();
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ id: "saved", title: document.title, document }), { status: 200 }),
    );
    const result = await diagramApi.create("session", document);
    expect(result.id).toBe("saved");
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/diagrams"),
      expect.objectContaining({ method: "POST" }),
    );
    fetchMock.mockRestore();
  });
});
