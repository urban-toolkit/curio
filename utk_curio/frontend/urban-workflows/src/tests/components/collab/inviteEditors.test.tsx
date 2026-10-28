/**
 * Share > Invite editors: the owner names an account by its username, sees the
 * dataflow's editors, and removes one. The server says why an invite is
 * refused, and the dialog shows its sentence. Remove is an icon, so it carries
 * Curio's tooltip (`data-tooltip`) and a name of its own.
 */
import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const mockList = jest.fn();
const mockAdd = jest.fn();
const mockRemove = jest.fn();
jest.mock("../../../api/projectEditorsApi", () => ({
  projectEditorsApi: {
    list: (...args: unknown[]) => mockList(...args),
    add: (...args: unknown[]) => mockAdd(...args),
    remove: (...args: unknown[]) => mockRemove(...args),
  },
}));
jest.mock("../../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));

import InviteEditorsDialog from "../../../components/collab/InviteEditorsDialog";
import { ShareMenu } from "../../../components/menus/top/ShareMenu";

const BOB = { user_id: 2, username: "bob", name: "Bob", added_at: "2026-10-28T00:00:00" };

beforeEach(() => {
  mockList.mockReset().mockResolvedValue([]);
  mockAdd.mockReset();
  mockRemove.mockReset();
});

describe("the Invite editors dialog", () => {
  test("adds an editor by username, lists them, and removes them", async () => {
    mockAdd.mockResolvedValue([BOB]);
    mockRemove.mockResolvedValue([]);
    render(<InviteEditorsDialog projectId="p1" onClose={jest.fn()} />);
    expect(await screen.findByText("No editors yet.")).toBeTruthy();
    expect(mockList).toHaveBeenCalledWith("p1");

    fireEvent.change(screen.getByLabelText("Username"), { target: { value: " bob " } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Add" }));
    });
    expect(mockAdd).toHaveBeenCalledWith("p1", "bob");
    const row = await screen.findByText("Bob");
    expect(row.closest("[data-editor]")?.getAttribute("data-editor")).toBe("bob");
    expect((screen.getByLabelText("Username") as HTMLInputElement).value).toBe("");

    const remove = screen.getByRole("button", { name: "Remove bob" });
    expect(remove.getAttribute("data-tooltip")).toBe("Remove editor");
    expect(remove.hasAttribute("title")).toBe(false);
    await act(async () => {
      fireEvent.click(remove);
    });
    expect(mockRemove).toHaveBeenCalledWith("p1", 2);
    expect(await screen.findByText("No editors yet.")).toBeTruthy();
  });

  test("shows why the server refused an invite, and keeps what was typed", async () => {
    mockAdd.mockRejectedValue(new Error("No account is named 'zed'."));
    render(<InviteEditorsDialog projectId="p1" onClose={jest.fn()} />);
    await screen.findByText("No editors yet.");

    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "zed" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Add" }));
    });

    expect((await screen.findByRole("alert")).textContent).toBe("No account is named 'zed'.");
    expect((screen.getByLabelText("Username") as HTMLInputElement).value).toBe("zed");
  });

  test("Add waits for a username", async () => {
    render(<InviteEditorsDialog projectId="p1" onClose={jest.fn()} />);
    await screen.findByText("No editors yet.");
    expect((screen.getByRole("button", { name: "Add" }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("the Share menu", () => {
  const share = (onInviteEditors?: () => void) => {
    const onClose = jest.fn();
    render(
      <MemoryRouter>
        <ShareMenu id="p1" includeOpenDashboard open onToggle={jest.fn()} onClose={onClose}
          onInviteEditors={onInviteEditors} />
      </MemoryRouter>,
    );
    return onClose;
  };

  test("offers Invite editors where it is given a way to open them", async () => {
    const open = jest.fn();
    const onClose = share(open);
    fireEvent.click(screen.getByRole("button", { name: "Invite editors" }));
    await waitFor(() => expect(open).toHaveBeenCalled());
    expect(onClose).toHaveBeenCalled();
  });

  test("offers no Invite editors anywhere else", () => {
    share(undefined);
    expect(screen.queryByText("Invite editors")).toBeNull();
    expect(screen.getByText("Copy dataflow link")).toBeTruthy();
  });
});
