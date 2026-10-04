import { afterEach, beforeEach, expect, test, vi } from "vitest";
import {
  cleanup,
  render,
  screen,
  within,
  waitFor,
  act,
} from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const fetchMock = vi.hoisted(() => {
  const mock = vi.fn();
  vi.stubGlobal("fetch", mock);
  return mock;
});
import { TagManager } from "../src/TagManager.js";

type Tag = { id: string; name: string };
let tags: Tag[];
let items: { id: string; tags: string[]; bought: boolean }[];
let failRename: boolean;
let client: QueryClient;
const back = vi.fn();
const logout = vi.fn();
const writes: { path: string; body: unknown; device: string | null }[] = [];
beforeEach(() => {
  tags = [
    { id: "vegetables", name: "Овощи" },
    { id: "soup", name: "Для супа" },
    { id: "unused", name: "Запас" },
  ];
  items = [
    { id: "onion", tags: ["vegetables", "soup"], bought: false },
    { id: "carrot", tags: ["vegetables"], bought: true },
    { id: "tea", tags: [], bought: false },
  ];
  failRename = false;
  writes.length = 0;
  back.mockReset();
  logout.mockReset();
  client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  fetchMock.mockImplementation(async (request: Request) => {
    const path = new URL(request.url).pathname;
    if (request.method === "GET")
      return Response.json(
        tags.map((tag) => ({
          ...tag,
          open_count: items.filter(
            (item) => item.tags.includes(tag.id) && !item.bought,
          ).length,
        })),
      );
    const body = request.method === "DELETE" ? null : await request.json();
    writes.push({ path, body, device: request.headers.get("X-Device-Id") });
    const id = path.split("/")[3];
    if (request.method === "PATCH") {
      if (failRename)
        return Response.json(
          { code: "conflict", message: "Не удалось переименовать тег" },
          { status: 409 },
        );
      const target = tags.find(
        (tag) =>
          tag.id !== id && tag.name.toLowerCase() === body.name.toLowerCase(),
      );
      if (target) {
        tags = tags.filter((tag) => tag.id !== id);
        items = items.map((item) => ({
          ...item,
          tags: [
            ...new Set(item.tags.map((tag) => (tag === id ? target.id : tag))),
          ],
        }));
        return Response.json(target);
      }
      tags = tags.map((tag) =>
        tag.id === id ? { ...tag, name: body.name } : tag,
      );
      return Response.json(tags.find((tag) => tag.id === id));
    }
    if (request.method === "DELETE") {
      tags = tags.filter((tag) => tag.id !== id);
      items = items.map((item) => ({
        ...item,
        tags: item.tags.filter((tag) => tag !== id),
      }));
      return new Response(null, { status: 204 });
    }
    const count = items.filter((item) => item.tags.includes(id)).length;
    items =
      body.action === "mark_bought"
        ? items.map((item) =>
            item.tags.includes(id) ? { ...item, bought: true } : item,
          )
        : items.filter((item) => !item.tags.includes(id));
    return Response.json({ count });
  });
});
afterEach(() => {
  cleanup();
  client.clear();
  fetchMock.mockReset();
  vi.restoreAllMocks();
});
function mount() {
  render(
    <QueryClientProvider client={client}>
      <TagManager
        listId="list"
        listName="Покупки"
        onBack={back}
        onLogout={logout}
      />
    </QueryClientProvider>,
  );
  return userEvent.setup();
}
async function expand(user: ReturnType<typeof userEvent.setup>, name: string) {
  const label = await screen.findByText(name, { selector: "summary > span" });
  await user.click(label);
  return within(label.closest("li")!);
}

test("unused tags remain visible; deleting only the tag preserves every purchase", async () => {
  const user = mount();
  await screen.findByText("Запас");
  const row = await expand(user, "Овощи");
  expect(row.getByText("1 к покупке")).toBeTruthy();
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  await user.click(row.getByRole("button", { name: "Удалить только тег" }));
  expect(writes).toHaveLength(0);
  confirm.mockReturnValue(true);
  await user.click(row.getByRole("button", { name: "Удалить только тег" }));
  await waitFor(() =>
    expect(
      screen.queryByText("Овощи", { selector: "summary > span" }),
    ).toBeNull(),
  );
  expect(items).toHaveLength(3);
  expect(items[0].tags).toEqual(["soup"]);
  expect(writes[0].device).toBeTruthy();
});

test("rename saves a new name and asks before merging into an existing tag", async () => {
  const user = mount();
  const row = await expand(user, "Для супа");
  await user.click(row.getByRole("button", { name: "Переименовать" }));
  const input = screen.getByLabelText(/Новое название тега/);
  await user.clear(input);
  await user.type(input, "Для борща");
  await user.click(screen.getByRole("button", { name: "Сохранить название" }));
  await screen.findByText("Для борща", { selector: "summary > span" });
  await user.click(row.getByRole("button", { name: "Переименовать" }));
  await user.clear(screen.getByLabelText(/Новое название тега/));
  await user.type(screen.getByLabelText(/Новое название тега/), "овощи");
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  await user.click(screen.getByRole("button", { name: "Сохранить название" }));
  expect(writes).toHaveLength(1);
  expect(confirm.mock.calls[0][0]).toContain("Объединить");
  confirm.mockReturnValue(true);
  await user.click(screen.getByRole("button", { name: "Сохранить название" }));
  await screen.findByText("Теги объединены: Овощи");
  expect(items[0].tags).toEqual(["vegetables"]);
  expect(tags.map((tag) => tag.name)).toEqual(["Овощи", "Запас"]);
});

test("failed rename keeps the draft for retry; leaving requires discarding it", async () => {
  const user = mount();
  const row = await expand(user, "Запас");
  await user.click(row.getByRole("button", { name: "Переименовать" }));
  await user.clear(screen.getByLabelText(/Новое название тега/));
  await user.type(screen.getByLabelText(/Новое название тега/), "На неделю");
  failRename = true;
  await user.click(screen.getByRole("button", { name: "Сохранить название" }));
  await screen.findByText("Не удалось переименовать тег");
  expect(
    (screen.getByLabelText(/Новое название тега/) as HTMLInputElement).value,
  ).toBe("На неделю");
  vi.spyOn(window, "confirm").mockReturnValue(false);
  await user.click(screen.getByRole("button", { name: "← К списку" }));
  expect(back).not.toHaveBeenCalled();
  failRename = false;
  await user.click(screen.getByRole("button", { name: "Сохранить название" }));
  await screen.findByText("Тег переименован: На неделю");
});

test("bulk actions require confirmation and include bought items when deleting", async () => {
  const user = mount();
  const row = await expand(user, "Овощи");
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  await user.click(
    row.getByRole("button", { name: "Отметить все купленными" }),
  );
  expect(writes).toHaveLength(0);
  confirm.mockReturnValue(true);
  await user.click(
    row.getByRole("button", { name: "Отметить все купленными" }),
  );
  await row.findByText("0 к покупке");
  expect(items.map((item) => item.bought)).toEqual([true, true, false]);
  expect(writes[0].body).toEqual({ action: "mark_bought" });
  await waitFor(() =>
    expect(
      (
        row.getByRole("button", {
          name: "Удалить все покупки с тегом",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false),
  );
  confirm.mockReturnValue(false);
  await user.click(
    row.getByRole("button", { name: "Удалить все покупки с тегом" }),
  );
  expect(writes).toHaveLength(1);
  expect(confirm.mock.lastCall?.[0]).toContain("включая купленные");
  confirm.mockReturnValue(true);
  await user.click(
    row.getByRole("button", { name: "Удалить все покупки с тегом" }),
  );
  await screen.findByText("Удалено покупок: 2");
  expect(items.map((item) => item.id)).toEqual(["tea"]);
  expect(tags).toHaveLength(3);
});

test("live tag deletion preserves the rename draft and disables saving", async () => {
  const user = mount();
  const row = await expand(user, "Запас");
  await user.click(row.getByRole("button", { name: "Переименовать" }));
  await user.type(screen.getByLabelText(/Новое название тега/), " дома");
  tags = tags.filter((tag) => tag.id !== "unused");
  await act(() => client.invalidateQueries({ queryKey: ["get", "/api/tags"] }));
  await screen.findByText(/Тег удалён или объединён/);
  expect(
    (
      screen.getByRole("button", {
        name: "Сохранить название",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(
    (screen.getByLabelText(/Новое название тега/) as HTMLInputElement).value,
  ).toBe("Запас дома");
  expect(writes).toHaveLength(0);
});
