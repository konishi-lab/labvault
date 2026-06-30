import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { SharedRecordSummary } from "@/lib/api";
import { SharedRecordsList } from "./shared-records-list";

// S1 TEST15 (2026-06-30): UX1 / UX3 のリグレッション防止。
// 期待挙動:
//   - currentTeam とは違う team の record をクリック →
//     setCurrentTeam(item.team, {persist:false}) が呼ばれる (UX3)
//   - currentTeam と同じ team の record をクリック →
//     setCurrentTeam は呼ばれない (UX1)
//   - いずれの場合も router.push(`/records/${id}`) が走る

const pushMock = vi.fn();
const setCurrentTeamMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    setCurrentTeam: setCurrentTeamMock,
    currentTeam: "konishi-lab",
    teams: [{ team_id: "konishi-lab", role: "member" }],
  }),
}));

function makeItem(
  overrides: Partial<SharedRecordSummary> & { id: string; team: string },
): SharedRecordSummary {
  return {
    title: "Sample record",
    type: "experiment",
    status: "active",
    tags: [],
    created_by: "owner@example.com",
    created_at: "2026-06-01T00:00:00Z",
    updated_by: "owner@example.com",
    updated_at: "2026-06-15T12:00:00Z",
    parent_id: null,
    template_name: null,
    role: "viewer",
    ...overrides,
  };
}

beforeEach(() => {
  pushMock.mockReset();
  setCurrentTeamMock.mockReset();
});

describe("SharedRecordsList", () => {
  it("renders empty hint when items=[]", () => {
    render(<SharedRecordsList items={[]} hasMore={false} />);
    expect(
      screen.getByText(/共有された record はまだありません/),
    ).toBeInTheDocument();
  });

  it("switches team with persist:false when clicking other-team item (UX1+UX3)", async () => {
    const user = userEvent.setup();
    const items = [
      makeItem({ id: "AB3F7K", team: "other-team", title: "other team rec" }),
    ];
    render(<SharedRecordsList items={items} hasMore={false} />);
    await user.click(screen.getByRole("button", { name: /other team rec/ }));
    expect(setCurrentTeamMock).toHaveBeenCalledWith("other-team", {
      persist: false,
    });
    expect(pushMock).toHaveBeenCalledWith("/records/AB3F7K");
  });

  it("does NOT call setCurrentTeam when item belongs to currentTeam", async () => {
    const user = userEvent.setup();
    const items = [
      makeItem({ id: "ZZ9X8Q", team: "konishi-lab", title: "same team rec" }),
    ];
    render(<SharedRecordsList items={items} hasMore={false} />);
    await user.click(screen.getByRole("button", { name: /same team rec/ }));
    expect(setCurrentTeamMock).not.toHaveBeenCalled();
    expect(pushMock).toHaveBeenCalledWith("/records/ZZ9X8Q");
  });

  it("renders 🏠 chip for own-team item, 🌐 for other-team", () => {
    const items = [
      makeItem({ id: "HOME11", team: "konishi-lab", title: "home" }),
      makeItem({ id: "AWAY11", team: "other-team", title: "away" }),
    ];
    render(<SharedRecordsList items={items} hasMore={false} />);
    expect(screen.getByText("🏠")).toBeInTheDocument();
    expect(screen.getByText("🌐")).toBeInTheDocument();
  });

  it("shows '+ もっと絞り込んでください' suffix when hasMore", () => {
    const items = [makeItem({ id: "HAS123", team: "konishi-lab" })];
    render(<SharedRecordsList items={items} hasMore={true} />);
    expect(screen.getByText(/もっと絞り込んでください/)).toBeInTheDocument();
  });
});
