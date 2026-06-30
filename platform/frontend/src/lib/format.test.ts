import { describe, expect, it } from "vitest";
import { formatBytes, ROLE_LABELS, ROLE_LABELS_BADGE } from "./format";

describe("formatBytes", () => {
  it("bytes < 1024 → B", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1023)).toBe("1023 B");
  });

  it("1024 ≤ bytes < 1MB → KB with 1 decimal", () => {
    expect(formatBytes(1024)).toBe("1.0 KB");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(1048575)).toBe("1024.0 KB");
  });

  it("bytes ≥ 1MB → MB with 1 decimal", () => {
    expect(formatBytes(1048576)).toBe("1.0 MB");
    expect(formatBytes(1572864)).toBe("1.5 MB");
  });
});

describe("ROLE_LABELS", () => {
  it("viewer / analyst の長文ラベル", () => {
    expect(ROLE_LABELS.viewer).toBe("閲覧のみ");
    expect(ROLE_LABELS.analyst).toBe("閲覧 + 解析投稿");
  });
});

describe("ROLE_LABELS_BADGE", () => {
  it("viewer / analyst の短縮ラベル", () => {
    expect(ROLE_LABELS_BADGE.viewer).toBe("閲覧");
    expect(ROLE_LABELS_BADGE.analyst).toBe("解析");
  });
});
