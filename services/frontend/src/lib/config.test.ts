import { afterEach, describe, expect, it } from "vitest";
import { serviceUrl } from "./config";

afterEach(() => {
  delete process.env.REGISTRY_URL;
});

describe("serviceUrl", () => {
  it("names the missing variable", () => {
    expect(() => serviceUrl("registry")).toThrow("REGISTRY_URL is not set");
  });
  it("rejects a value that is not http(s), without echoing it", () => {
    process.env.REGISTRY_URL = "ftp://secret-host";
    expect(() => serviceUrl("registry")).toThrow(/REGISTRY_URL must be/);
    expect(() => serviceUrl("registry")).not.toThrow(/secret-host/);
  });
  it("removes a trailing slash", () => {
    process.env.REGISTRY_URL = "http://127.0.0.1:8000/";
    expect(serviceUrl("registry")).toBe("http://127.0.0.1:8000");
  });
});
